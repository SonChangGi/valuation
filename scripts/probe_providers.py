#!/usr/bin/env python3
"""Read-only smoke tests for Valuation v2 data-source candidates.

This is an audit utility, not a production adapter.  It calls only documented
official endpoints, keeps responses in memory, prints normalized probe
metadata, never writes provider payloads, and never prints API keys.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import socket
import ssl
import sys
import time
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TARGETS = {
    "MSFT": {
        "cik": "0000789019",
        "filing": {
            "accession": "000095017025100235",
            "document": "msft-20250630.htm",
            "form": "10-K",
            "period_end": "2025-06-30",
        },
    },
    "NVDA": {
        "cik": "0001045810",
        "filing": {
            "accession": "000104581026000021",
            "document": "nvda-20260125.htm",
            "form": "10-K",
            "period_end": "2026-01-25",
        },
    },
    "MU": {
        "cik": "0000723125",
        "filing": {
            "accession": "000072312526000015",
            "document": "mu-20260528.htm",
            "form": "10-Q",
            "period_end": "2026-05-28",
        },
    },
}

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_ARCHIVE_DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"
SEC_ARCHIVE_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/index.json"
SEC_STRICT_ENDPOINTS = (
    "submissions",
    "companyfacts",
    "archive",
)
SEC_STRICT_JSON_CONTENT_TYPES = {"application/json"}
SEC_STRICT_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
SEC_STRICT_MAX_ATTEMPTS = 3
SEC_STRICT_MIN_INTERVAL_SECONDS = 0.6
SEC_STRICT_BACKOFF_SECONDS = (1.0, 2.0)
TREASURY_CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve&"
    "field_tdr_date_value={year}&page&_format=csv"
)
DAMODARAN_ERP_XLS_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xls"
DAMODARAN_CURRENT_ERP_XLSX_URL = (
    "https://pages.stern.nyu.edu/~adamodar/pc/implprem/ERPJuly26.xlsx"
)

DEFAULT_USER_AGENT = "valuation-v2-provider-audit/1.0"
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()

CONCEPTS: dict[str, list[tuple[str, str]]] = {
    "shares_outstanding_actual": [("dei", "EntityCommonStockSharesOutstanding")],
    "diluted_weighted_average_shares": [
        ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")
    ],
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
    ],
    "net_income": [
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
    ],
    "operating_income": [("us-gaap", "OperatingIncomeLoss")],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities")
    ],
    "capital_expenditures": [
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsForProceedsFromOtherPropertyPlantAndEquipment"),
    ],
    "cash": [
        ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
        ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
    ],
    "investments": [
        ("us-gaap", "ShortTermInvestments"),
        ("us-gaap", "MarketableSecuritiesCurrent"),
        ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
        ("us-gaap", "MarketableSecuritiesNoncurrent"),
    ],
    "debt": [
        ("us-gaap", "LongTermDebtCurrent"),
        ("us-gaap", "LongTermDebtNoncurrent"),
        ("us-gaap", "LongTermDebt"),
        ("us-gaap", "ShortTermBorrowings"),
    ],
    "lease_liabilities": [
        ("us-gaap", "OperatingLeaseLiabilityCurrent"),
        ("us-gaap", "OperatingLeaseLiabilityNoncurrent"),
        ("us-gaap", "FinanceLeaseLiabilityCurrent"),
        ("us-gaap", "FinanceLeaseLiabilityNoncurrent"),
    ],
    "noncontrolling_interest": [
        ("us-gaap", "MinorityInterest"),
        ("us-gaap", "NoncontrollingInterestInConsolidatedEntity"),
        ("us-gaap", "NetIncomeLossAttributableToNoncontrollingInterest"),
    ],
    "depreciation_and_amortization": [
        ("us-gaap", "DepreciationDepletionAndAmortization"),
        ("us-gaap", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"),
        ("us-gaap", "Depreciation"),
    ],
    "interest_expense": [
        ("us-gaap", "InterestExpenseNonOperating"),
        ("us-gaap", "InterestExpense"),
        ("us-gaap", "InterestAndDebtExpense"),
    ],
    "tax_expense": [("us-gaap", "IncomeTaxExpenseBenefit")],
    "eps_diluted_gaap": [("us-gaap", "EarningsPerShareDiluted")],
}


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_bytes(
    url: str,
    *,
    timeout: float,
    user_agent: str = DEFAULT_USER_AGENT,
    max_bytes: int = 12_000_000,
) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/csv,application/vnd.ms-excel,text/html;q=0.8,*/*;q=0.2",
        },
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                return {
                    "ok": False,
                    "access_status": "response_too_large",
                    "http_status": response.status,
                    "bytes_read": len(body),
                }
            return {
                "ok": True,
                "access_status": "ok",
                "http_status": response.status,
                "content_type": response.headers.get_content_type(),
                "body": body,
                "bytes_read": len(body),
            }
    except HTTPError as exc:
        return {
            "ok": False,
            "access_status": f"http_{exc.code}",
            "http_status": exc.code,
            "content_type": (
                exc.headers.get_content_type() if exc.headers is not None else None
            ),
            "error_type": type(exc).__name__,
        }
    except (TimeoutError, socket.timeout) as exc:
        return {
            "ok": False,
            "access_status": "timeout",
            "http_status": None,
            "content_type": None,
            "error_type": type(exc).__name__,
        }
    except URLError as exc:
        timed_out = isinstance(exc.reason, (TimeoutError, socket.timeout))
        return {
            "ok": False,
            "access_status": "timeout" if timed_out else "network_error",
            "http_status": None,
            "content_type": None,
            "error_type": type(exc).__name__,
        }
    except OSError as exc:
        return {
            "ok": False,
            "access_status": "network_error",
            "http_status": None,
            "content_type": None,
            "error_type": type(exc).__name__,
        }


def fetch_json(url: str, *, timeout: float, user_agent: str = DEFAULT_USER_AGENT) -> dict[str, Any]:
    result = fetch_bytes(url, timeout=timeout, user_agent=user_agent)
    if not result["ok"]:
        return result
    try:
        result["data"] = json.loads(result.pop("body"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        result.pop("body", None)
        result["ok"] = False
        result["access_status"] = "invalid_json"
    return result


def fetch_github_repository_variable(
    name: str, *, timeout: float
) -> tuple[str, str]:
    """Read one repository variable in memory without emitting its value."""

    if os.environ.get("SEC_USER_AGENT_CONFIGURED") != "true":
        return "", "missing_user_agent"
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
        return "", "repository_variable_runtime_unavailable"
    url = f"https://api.github.com/repos/{repository}/actions/variables/{name}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            body = response.read(262_145)
            if len(body) > 262_144:
                return "", "repository_variable_response_too_large"
    except HTTPError as exc:
        return "", f"repository_variable_http_{exc.code}"
    except (TimeoutError, socket.timeout):
        return "", "repository_variable_timeout"
    except (OSError, URLError):
        return "", "repository_variable_network_error"
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "", "repository_variable_invalid_json"
    if not isinstance(payload, dict) or payload.get("name") != name:
        return "", "repository_variable_invalid_schema"
    value = payload.get("value")
    if not isinstance(value, str) or not value.strip():
        return "", "missing_user_agent"
    return value, "ok"


def public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"body", "data"}}


def _normalized_cik(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text.isdigit() or len(text) > 10:
        return None
    return text.zfill(10)


def _validate_submissions(
    payload: Any, *, ticker: str, expected_cik: str
) -> str:
    if not isinstance(payload, dict):
        return "invalid_schema"
    if _normalized_cik(payload.get("cik")) != expected_cik:
        return "identity_mismatch"
    tickers = payload.get("tickers")
    if not isinstance(tickers, list) or ticker not in tickers:
        return "identity_mismatch"
    if not isinstance(payload.get("name"), str) or not payload["name"].strip():
        return "invalid_schema"
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        return "invalid_schema"
    required = ("form", "accessionNumber", "primaryDocument")
    values = [recent.get(key) for key in required]
    if any(not isinstance(items, list) or not items for items in values):
        return "invalid_schema"
    if len({len(items) for items in values}) != 1:
        return "invalid_schema"
    if not all(
        isinstance(accession, str)
        and re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
        for accession in values[1]
    ):
        return "invalid_schema"
    return "passed"


def _validate_companyfacts(payload: Any, *, expected_cik: str) -> str:
    if not isinstance(payload, dict):
        return "invalid_schema"
    if _normalized_cik(payload.get("cik")) != expected_cik:
        return "identity_mismatch"
    if not isinstance(payload.get("entityName"), str) or not payload["entityName"].strip():
        return "invalid_schema"
    facts = payload.get("facts")
    if not isinstance(facts, dict) or not facts:
        return "invalid_schema"
    for namespace in facts.values():
        if not isinstance(namespace, dict):
            continue
        for concept in namespace.values():
            units = concept.get("units") if isinstance(concept, dict) else None
            if isinstance(units, dict) and any(
                isinstance(entries, list) and entries for entries in units.values()
            ):
                return "passed"
    return "invalid_schema"


def _inline_fact_value(text: str, concept: str) -> str | None:
    match = re.search(
        rf"<ix:(?:nonNumeric|nonFraction)\b[^>]*\bname=[\"']dei:{re.escape(concept)}[\"'][^>]*>(.*?)</ix:(?:nonNumeric|nonFraction)\s*>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    value = unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    return " ".join(value.replace("\xa0", " ").split())


def _normalized_date(value: str) -> str | None:
    for date_format in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _validate_archive_document(
    body: bytes,
    *,
    expected_cik: str,
    expected_form: str,
    expected_period_end: str,
) -> str:
    try:
        text = body.decode("utf-8", errors="replace")
    except AttributeError:
        return "invalid_schema"
    lower = text.lower()
    if "<html" not in lower or ("<ix:" not in lower and "xmlns:ix=" not in lower):
        return "invalid_schema"
    cik = _inline_fact_value(text, "EntityCentralIndexKey")
    form = _inline_fact_value(text, "DocumentType")
    period_end = _inline_fact_value(text, "DocumentPeriodEndDate")
    if cik is None or form is None or period_end is None:
        return "invalid_schema"
    if (
        _normalized_cik(cik) != expected_cik
        or form.strip().upper() != expected_form
        or _normalized_date(period_end) != expected_period_end
    ):
        return "identity_mismatch"
    return "passed"


class _SecRequestPacer:
    def __init__(
        self,
        *,
        min_interval: float,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.min_interval = min_interval
        self.monotonic = monotonic
        self.sleep = sleep
        self.last_request_started: float | None = None

    def wait(self) -> None:
        now = self.monotonic()
        if self.last_request_started is not None:
            remaining = self.min_interval - (now - self.last_request_started)
            if remaining > 0:
                self.sleep(remaining)
        self.last_request_started = self.monotonic()


def _strict_transport_result(
    transport: Callable[..., dict[str, Any]],
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int,
) -> dict[str, Any]:
    try:
        return transport(
            url,
            timeout=timeout,
            user_agent=user_agent,
            max_bytes=max_bytes,
        )
    except (TimeoutError, socket.timeout):
        return {
            "ok": False,
            "access_status": "timeout",
            "http_status": None,
            "content_type": None,
        }
    except (OSError, URLError):
        return {
            "ok": False,
            "access_status": "network_error",
            "http_status": None,
            "content_type": None,
        }


def _strict_fetch_with_retry(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int,
    transport: Callable[..., dict[str, Any]],
    pacer: _SecRequestPacer,
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> tuple[dict[str, Any], int]:
    started = monotonic()
    result: dict[str, Any] = {}
    for attempt in range(SEC_STRICT_MAX_ATTEMPTS):
        pacer.wait()
        result = _strict_transport_result(
            transport,
            url,
            timeout=timeout,
            user_agent=user_agent,
            max_bytes=max_bytes,
        )
        status = result.get("http_status")
        retryable = (
            status in {429, 500, 502, 503, 504}
            or result.get("access_status") in {"timeout", "network_error"}
        )
        if not retryable or attempt == SEC_STRICT_MAX_ATTEMPTS - 1:
            break
        sleep(SEC_STRICT_BACKOFF_SECONDS[attempt])
    return result, max(0, round((monotonic() - started) * 1000))


def _strict_failure_schema(result: dict[str, Any]) -> str:
    status = result.get("http_status")
    if status == 403:
        return "not_checked_http_403"
    if status == 429:
        return "not_checked_http_429"
    if result.get("access_status") == "timeout":
        return "not_checked_timeout"
    if status is not None:
        return "not_checked_http_error"
    return "not_checked_network_error"


def _strict_record(
    *,
    ticker: str,
    endpoint: str,
    result: dict[str, Any] | None,
    schema_status: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    passed = schema_status == "passed"
    return {
        "ticker": ticker,
        "endpoint": endpoint,
        "http_status": result.get("http_status") if result else None,
        "content_type": result.get("content_type") if result else None,
        "schema_status": schema_status,
        "elapsed_ms": elapsed_ms,
        "gate_status": "passed" if passed else "failed",
    }


def run_sec_strict_gate(
    *,
    user_agent: str,
    timeout: float = 20.0,
    transport: Callable[..., dict[str, Any]] = fetch_bytes,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], str, int]:
    """Probe only SEC access and return sanitized fail-closed gate records."""

    records: list[dict[str, Any]] = []
    if not user_agent.strip():
        for ticker in TARGETS:
            for endpoint in SEC_STRICT_ENDPOINTS:
                records.append(
                    _strict_record(
                        ticker=ticker,
                        endpoint=endpoint,
                        result=None,
                        schema_status="missing_user_agent",
                        elapsed_ms=0,
                    )
                )
        return records, "blocked", 2

    pacer = _SecRequestPacer(
        min_interval=SEC_STRICT_MIN_INTERVAL_SECONDS,
        monotonic=monotonic,
        sleep=sleep,
    )
    circuit_open = False

    for ticker, metadata in TARGETS.items():
        cik = metadata["cik"]
        filing = metadata["filing"]
        accession = filing["accession"]
        endpoints = (
            (
                "submissions",
                SEC_SUBMISSIONS_URL.format(cik=cik),
                SEC_STRICT_JSON_CONTENT_TYPES,
                12_000_000,
            ),
            (
                "companyfacts",
                SEC_COMPANYFACTS_URL.format(cik=cik),
                SEC_STRICT_JSON_CONTENT_TYPES,
                12_000_000,
            ),
            (
                "archive",
                SEC_ARCHIVE_DOCUMENT_URL.format(
                    cik_int=int(cik),
                    accession=accession,
                    document=filing["document"],
                ),
                SEC_STRICT_HTML_CONTENT_TYPES,
                15_000_000,
            ),
        )

        for endpoint, url, allowed_content_types, max_bytes in endpoints:
            if circuit_open:
                records.append(
                    _strict_record(
                        ticker=ticker,
                        endpoint=endpoint,
                        result=None,
                        schema_status="not_checked_circuit_open",
                        elapsed_ms=0,
                    )
                )
                continue

            result, elapsed_ms = _strict_fetch_with_retry(
                url,
                timeout=timeout,
                user_agent=user_agent,
                max_bytes=max_bytes,
                transport=transport,
                pacer=pacer,
                monotonic=monotonic,
                sleep=sleep,
            )
            if result.get("http_status") == 403:
                circuit_open = True
            if not result.get("ok") or result.get("http_status") != 200:
                schema_status = _strict_failure_schema(result)
            elif result.get("content_type") not in allowed_content_types:
                schema_status = "invalid_content_type"
            elif endpoint in {"submissions", "companyfacts"}:
                try:
                    payload = json.loads(result.get("body", b""))
                except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                    schema_status = "invalid_json"
                else:
                    schema_status = (
                        _validate_submissions(payload, ticker=ticker, expected_cik=cik)
                        if endpoint == "submissions"
                        else _validate_companyfacts(payload, expected_cik=cik)
                    )
            else:
                schema_status = _validate_archive_document(
                    result.get("body", b""),
                    expected_cik=cik,
                    expected_form=filing["form"],
                    expected_period_end=filing["period_end"],
                )

            records.append(
                _strict_record(
                    ticker=ticker,
                    endpoint=endpoint,
                    result=result,
                    schema_status=schema_status,
                    elapsed_ms=elapsed_ms,
                )
            )

    passed = (
        len(records) == len(TARGETS) * len(SEC_STRICT_ENDPOINTS)
        and all(record["gate_status"] == "passed" for record in records)
    )
    return records, "passed" if passed else "blocked", 0 if passed else 1


def print_sec_strict_gate(records: list[dict[str, Any]], gate_status: str) -> None:
    for record in records:
        print(
            " ".join(
                (
                    f"ticker={record['ticker']}",
                    f"endpoint={record['endpoint']}",
                    f"http_status={record['http_status'] if record['http_status'] is not None else 'none'}",
                    f"content_type={record['content_type'] or 'none'}",
                    f"schema={record['schema_status']}",
                    f"elapsed_ms={record['elapsed_ms']}",
                    f"gate_status={record['gate_status']}",
                )
            )
        )
    total_elapsed_ms = sum(record["elapsed_ms"] for record in records)
    print(
        "ticker=ALL endpoint=gate http_status=none content_type=none "
        f"schema={gate_status} elapsed_ms={total_elapsed_ms} gate_status={gate_status}"
    )


def concept_probe(companyfacts: dict[str, Any], specs: list[tuple[str, str]]) -> dict[str, Any]:
    facts_root = companyfacts.get("facts", {})
    matched_tags: list[str] = []
    forms: set[str] = set()
    latest_filed: str | None = None
    earliest_filed: str | None = None
    fact_count = 0

    for namespace, tag in specs:
        concept = facts_root.get(namespace, {}).get(tag)
        if not isinstance(concept, dict):
            continue
        matched_tags.append(f"{namespace}:{tag}")
        for entries in concept.get("units", {}).values():
            if not isinstance(entries, list):
                continue
            for fact in entries:
                if not isinstance(fact, dict):
                    continue
                fact_count += 1
                if fact.get("form"):
                    forms.add(str(fact["form"]))
                filed = fact.get("filed")
                if isinstance(filed, str) and (latest_filed is None or filed > latest_filed):
                    latest_filed = filed
                if isinstance(filed, str) and (earliest_filed is None or filed < earliest_filed):
                    earliest_filed = filed

    return {
        "available": bool(matched_tags),
        "matched_tags": matched_tags,
        "fact_count": fact_count,
        "annual_10k": "10-K" in forms or "10-K/A" in forms,
        "quarterly_10q": "10-Q" in forms or "10-Q/A" in forms,
        "forms": sorted(forms),
        "earliest_filed": earliest_filed,
        "latest_filed": latest_filed,
        "coverage_scope": "at least one matching historical fact; current-period availability is not asserted",
    }


def recent_filings(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    recent = submissions.get("filings", {}).get("recent", {})
    keys = ["form", "accessionNumber", "primaryDocument", "filingDate", "reportDate"]
    lengths = [len(recent.get(key, [])) for key in keys]
    if not lengths or min(lengths) == 0:
        return []
    rows: list[dict[str, Any]] = []
    for index in range(min(lengths)):
        rows.append({key: recent[key][index] for key in keys})
    return rows


def latest_form(rows: list[dict[str, Any]], forms: set[str]) -> dict[str, Any] | None:
    return next((row for row in rows if row.get("form") in forms), None)


def probe_sec_filing_document(
    row: dict[str, Any] | None, cik: str, *, timeout: float, user_agent: str
) -> dict[str, Any]:
    if not row:
        return {"access_status": "not_found", "available": False}
    accession = str(row["accessionNumber"]).replace("-", "")
    url = SEC_ARCHIVE_DOCUMENT_URL.format(
        cik_int=int(cik), accession=accession, document=row["primaryDocument"]
    )
    result = fetch_bytes(
        url, timeout=timeout, user_agent=user_agent, max_bytes=15_000_000
    )
    summary = public_result(result)
    summary.update(
        {
            "form": row["form"],
            "filing_date": row["filingDate"],
            "report_date": row["reportDate"],
            "source_url": url,
            "available": bool(result["ok"]),
        }
    )
    if result["ok"]:
        lower = result["body"].lower()
        summary["inline_xbrl_detected"] = b"<ix:" in lower or b"xmlns:ix=" in lower
        summary["xbrl_dimension_marker_detected"] = (
            b"xbrldi:explicitmember" in lower or b"xbrldi:typedmember" in lower
        )
    return summary


def probe_sec_exhibit_index(
    row: dict[str, Any] | None, cik: str, *, timeout: float, user_agent: str
) -> dict[str, Any]:
    if not row:
        return {"access_status": "not_found", "available": False}
    accession = str(row["accessionNumber"]).replace("-", "")
    url = SEC_ARCHIVE_INDEX_URL.format(cik_int=int(cik), accession=accession)
    result = fetch_json(url, timeout=timeout, user_agent=user_agent)
    summary = public_result(result)
    summary.update(
        {
            "form": row["form"],
            "filing_date": row["filingDate"],
            "source_url": url,
            "available": bool(result["ok"]),
        }
    )
    if result["ok"]:
        items = result["data"].get("directory", {}).get("item", [])
        names = [str(item.get("name", "")) for item in items if isinstance(item, dict)]
        pattern = re.compile(r"(?:ex(?:hibit)?[-_ ]?99|99[-_ ]?1|earnings|release)", re.I)
        summary["exhibit_99_candidate_files"] = sorted(name for name in names if pattern.search(name))
        summary["directory_item_count"] = len(names)
    return summary


def probe_sec(*, timeout: float) -> dict[str, Any]:
    if not SEC_USER_AGENT:
        return {
            "access_status": "not_tested_missing_user_agent",
            "core_api_access_status": "not_tested_missing_user_agent",
            "filing_archive_access_status": "not_tested_missing_user_agent",
            "authentication": "none; SEC_USER_AGENT with a real contact is required",
            "rate_limit": "SEC fair-access maximum 10 requests/second",
            "tested_tickers": [],
            "field_coverage": {},
        }

    ticker_results: dict[str, Any] = {}
    field_tickers: dict[str, list[str]] = {field: [] for field in CONCEPTS}
    statement_fields = [
        "annual_income_statement",
        "quarterly_income_statement",
        "annual_cash_flow_statement",
        "quarterly_cash_flow_statement",
    ]
    field_tickers.update({field: [] for field in statement_fields})

    for ticker, metadata in TARGETS.items():
        cik = metadata["cik"]
        submissions_url = SEC_SUBMISSIONS_URL.format(cik=cik)
        facts_url = SEC_COMPANYFACTS_URL.format(cik=cik)
        submissions = fetch_json(
            submissions_url, timeout=timeout, user_agent=SEC_USER_AGENT
        )
        time.sleep(0.12)
        companyfacts = fetch_json(
            facts_url, timeout=timeout, user_agent=SEC_USER_AGENT
        )
        time.sleep(0.12)

        ticker_result: dict[str, Any] = {
            "cik": cik,
            "submissions": {**public_result(submissions), "source_url": submissions_url},
            "companyfacts": {**public_result(companyfacts), "source_url": facts_url},
            "concepts": {},
        }

        if companyfacts["ok"]:
            coverage = {
                field: concept_probe(companyfacts["data"], specs)
                for field, specs in CONCEPTS.items()
            }
            ticker_result["concepts"] = coverage
            for field, item in coverage.items():
                if item["available"]:
                    field_tickers[field].append(ticker)

            annual_income = all(
                coverage[field]["annual_10k"] for field in ("revenue", "net_income")
            )
            quarterly_income = all(
                coverage[field]["quarterly_10q"] for field in ("revenue", "net_income")
            )
            annual_cf = all(
                coverage[field]["annual_10k"]
                for field in ("operating_cash_flow", "capital_expenditures")
            )
            quarterly_cf = all(
                coverage[field]["quarterly_10q"]
                for field in ("operating_cash_flow", "capital_expenditures")
            )
            statement_availability = {
                "annual_income_statement": annual_income,
                "quarterly_income_statement": quarterly_income,
                "annual_cash_flow_statement": annual_cf,
                "quarterly_cash_flow_statement": quarterly_cf,
            }
            ticker_result["statement_availability"] = statement_availability
            for field, available in statement_availability.items():
                if available:
                    field_tickers[field].append(ticker)

        if submissions["ok"]:
            rows = recent_filings(submissions["data"])
            ticker_result["recent_forms"] = sorted({str(row["form"]) for row in rows})
            ticker_result["filing_html"] = {
                "latest_10k": probe_sec_filing_document(
                    latest_form(rows, {"10-K", "10-K/A"}),
                    cik,
                    timeout=timeout,
                    user_agent=SEC_USER_AGENT,
                ),
                "latest_10q": probe_sec_filing_document(
                    latest_form(rows, {"10-Q", "10-Q/A"}),
                    cik,
                    timeout=timeout,
                    user_agent=SEC_USER_AGENT,
                ),
            }
            time.sleep(0.12)
            ticker_result["latest_8k_index"] = probe_sec_exhibit_index(
                latest_form(rows, {"8-K", "8-K/A"}),
                cik,
                timeout=timeout,
                user_agent=SEC_USER_AGENT,
            )
            time.sleep(0.12)

        ticker_results[ticker] = ticker_result

    all_core_ok = all(
        item["submissions"].get("ok") and item["companyfacts"].get("ok")
        for item in ticker_results.values()
    )
    any_ok = any(
        item["submissions"].get("ok") or item["companyfacts"].get("ok")
        for item in ticker_results.values()
    )
    archive_results = [
        result
        for item in ticker_results.values()
        for result in (
            item.get("filing_html", {}).get("latest_10k", {}),
            item.get("filing_html", {}).get("latest_10q", {}),
            item.get("latest_8k_index", {}),
        )
        if result
    ]
    all_archive_ok = bool(archive_results) and all(result.get("ok") for result in archive_results)
    any_archive_ok = any(result.get("ok") for result in archive_results)
    overall_ok = all_core_ok and all_archive_ok
    return {
        "access_status": "ok" if overall_ok else ("partial" if any_ok or any_archive_ok else "unavailable"),
        "core_api_access_status": "ok" if all_core_ok else ("partial" if any_ok else "unavailable"),
        "filing_archive_access_status": (
            "ok" if all_archive_ok else ("partial" if any_archive_ok else "unavailable")
        ),
        "authentication": "none; descriptive User-Agent required",
        "rate_limit": "SEC fair-access maximum 10 requests/second; probe is sequential and throttled",
        "tested_tickers": list(TARGETS),
        "field_coverage": {
            field: {
                "available_tickers": tickers,
                "missing_tickers": [ticker for ticker in TARGETS if ticker not in tickers],
            }
            for field, tickers in field_tickers.items()
        },
        "period_notes": {
            "actual_shares": "instantaneous common shares outstanding",
            "diluted_shares": "duration-based diluted weighted-average shares; never substitute for actual shares",
            "quarterly_cash_flow": "10-Q cash-flow facts are commonly year-to-date; standalone quarters require explicit derivation",
        },
        "ticker_results": ticker_results,
    }


def probe_treasury(*, timeout: float) -> dict[str, Any]:
    year = datetime.now(timezone.utc).year
    url = TREASURY_CSV_URL.format(year=year)
    result = fetch_bytes(url, timeout=timeout, max_bytes=2_000_000)
    summary = {
        **public_result(result),
        "authentication": "none",
        "tested_tickers": [],
        "source_url": url,
    }
    if result["ok"]:
        try:
            rows = list(csv.DictReader(io.StringIO(result["body"].decode("utf-8-sig"))))
            first = rows[0]
            summary.update(
                {
                    "access_status": "ok",
                    "observation_count": len(rows),
                    "latest_observation": {
                        "date": first.get("Date"),
                        "ten_year_percent": first.get("10 Yr"),
                    },
                    "period_definition": "daily par yield curve, nominal constant maturity, percent",
                }
            )
        except (UnicodeDecodeError, csv.Error, IndexError):
            summary["ok"] = False
            summary["access_status"] = "invalid_csv"
    return summary


def probe_damodaran(*, timeout: float) -> dict[str, Any]:
    historical_workbook = fetch_bytes(
        DAMODARAN_ERP_XLS_URL, timeout=timeout, max_bytes=2_000_000
    )
    current_workbook = fetch_bytes(
        DAMODARAN_CURRENT_ERP_XLSX_URL, timeout=timeout, max_bytes=2_000_000
    )
    historical_summary = {
        **public_result(historical_workbook),
        "source_url": DAMODARAN_ERP_XLS_URL,
    }
    if historical_workbook["ok"]:
        signature_ok = historical_workbook["body"].startswith(
            bytes.fromhex("D0CF11E0")
        )
        historical_summary.update(
            {
                "access_status": "ok" if signature_ok else "unexpected_file_format",
                "legacy_xls_signature": signature_ok,
            }
        )

    current_summary = {
        **public_result(current_workbook),
        "source_url": DAMODARAN_CURRENT_ERP_XLSX_URL,
    }
    if current_workbook["ok"]:
        signature_ok = current_workbook["body"].startswith(b"PK")
        current_summary.update(
            {
                "access_status": "ok" if signature_ok else "unexpected_file_format",
                "xlsx_signature": signature_ok,
            }
        )

    both_ok = bool(historical_workbook.get("ok") and current_workbook.get("ok"))
    return {
        "access_status": "ok" if both_ok else "partial",
        "authentication": "none",
        "tested_tickers": [],
        "period_definition": "explicitly dated US implied ERP; the probe validates official downloads but does not parse or publish workbook values",
        "current_workbook": current_summary,
        "historical_workbook": historical_summary,
    }


def missing_key_result(env_name: str) -> dict[str, Any]:
    return {
        "access_status": "not_tested_no_key",
        "authentication": f"API key via {env_name}",
        "tested_tickers": [],
    }


def inspect_json_response(result: dict[str, Any], expected_keys: set[str]) -> dict[str, Any]:
    summary = public_result(result)
    if not result["ok"]:
        return summary
    data = result["data"]
    if isinstance(data, dict):
        error_keys = [
            key
            for key in ("Error Message", "Information", "Note", "message")
            if key in data and key not in expected_keys
        ]
        status_value = data.get("status")
        if (
            isinstance(status_value, str)
            and status_value.lower() not in {"ok", "success"}
            and "status" not in expected_keys
        ):
            error_keys.append("status")
        summary["payload_status"] = "provider_error" if error_keys else "recognized"
        summary["recognized_keys"] = sorted(expected_keys.intersection(data))
        summary["provider_error_keys"] = error_keys
        for key in expected_keys:
            if isinstance(data.get(key), list):
                records = data[key]
                summary["record_count"] = len(records)
                dates = sorted(
                    str(record[date_key])
                    for record in records
                    if isinstance(record, dict)
                    for date_key in ("fiscalDateEnding", "date", "reportedDate")
                    if record.get(date_key)
                )
                if dates:
                    summary["earliest_record_date"] = dates[0]
                    summary["latest_record_date"] = dates[-1]
                break
    elif isinstance(data, list):
        summary["payload_status"] = "recognized" if data else "empty"
        summary["record_count"] = len(data)
    else:
        summary["payload_status"] = "unexpected_shape"
    return summary


def probe_alpha_vantage(*, timeout: float, include_keyed: bool) -> dict[str, Any]:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not key:
        results: dict[str, Any] = {}
        for ticker in TARGETS:
            query = urlencode(
                {"function": "SHARES_OUTSTANDING", "symbol": ticker, "apikey": "demo"}
            )
            result = fetch_json(f"https://www.alphavantage.co/query?{query}", timeout=timeout)
            results[ticker] = inspect_json_response(result, {"data"})
        return {
            "access_status": "demo_partial",
            "authentication": "official demo key; full target/field tests require ALPHA_VANTAGE_API_KEY",
            "tested_tickers": list(TARGETS),
            "tested_fields": ["basic_and_diluted_shares_history"],
            "unavailable_reason_other_fields": "not_tested_no_key",
            "ticker_results": results,
        }
    if not include_keyed:
        return {
            "access_status": "not_run_keyed_probe_opt_in_required",
            "authentication": "API key present but --include-keyed was not supplied",
            "tested_tickers": [],
        }
    results: dict[str, Any] = {}
    for ticker in TARGETS:
        ticker_results: dict[str, Any] = {}
        for name, function, expected in (
            ("daily_adjusted", "TIME_SERIES_DAILY_ADJUSTED", {"Time Series (Daily)"}),
            ("earnings_estimates", "EARNINGS_ESTIMATES", {"annualEstimates", "quarterlyEstimates"}),
        ):
            query = urlencode({"function": function, "symbol": ticker, "apikey": key})
            result = fetch_json(f"https://www.alphavantage.co/query?{query}", timeout=timeout)
            ticker_results[name] = inspect_json_response(result, expected)
        results[ticker] = ticker_results
    return {
        "access_status": "tested_with_key",
        "authentication": "API key",
        "tested_tickers": list(TARGETS),
        "ticker_results": results,
    }


def probe_fmp(*, timeout: float, include_keyed: bool) -> dict[str, Any]:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        return missing_key_result("FMP_API_KEY")
    if not include_keyed:
        return {
            "access_status": "not_run_keyed_probe_opt_in_required",
            "authentication": "API key present but --include-keyed was not supplied",
            "tested_tickers": [],
        }
    results: dict[str, Any] = {}
    for ticker in TARGETS:
        ticker_results: dict[str, Any] = {}
        endpoints = {
            "income_statement": f"https://financialmodelingprep.com/stable/income-statement?symbol={ticker}&apikey={key}",
            "cash_flow": f"https://financialmodelingprep.com/stable/cash-flow-statement?symbol={ticker}&apikey={key}",
            "analyst_estimates": f"https://financialmodelingprep.com/stable/analyst-estimates?symbol={ticker}&period=annual&page=0&limit=2&apikey={key}",
        }
        for name, url in endpoints.items():
            ticker_results[name] = inspect_json_response(fetch_json(url, timeout=timeout), set())
        results[ticker] = ticker_results
    return {
        "access_status": "tested_with_key",
        "authentication": "API key",
        "tested_tickers": list(TARGETS),
        "ticker_results": results,
    }


def probe_twelve_data(*, timeout: float, include_keyed: bool) -> dict[str, Any]:
    key = os.environ.get("TWELVE_DATA_API_KEY")
    if not key:
        return missing_key_result("TWELVE_DATA_API_KEY")
    if not include_keyed:
        return {
            "access_status": "not_run_keyed_probe_opt_in_required",
            "authentication": "API key present but --include-keyed was not supplied",
            "tested_tickers": [],
        }
    results: dict[str, Any] = {}
    for ticker in TARGETS:
        endpoints = {
            "daily": f"https://api.twelvedata.com/time_series?symbol={ticker}&interval=1day&outputsize=5&apikey={key}",
            "income_statement": f"https://api.twelvedata.com/income_statement?symbol={ticker}&period=annual&outputsize=2&apikey={key}",
        }
        results[ticker] = {
            name: inspect_json_response(fetch_json(url, timeout=timeout), {"values", "income_statement"})
            for name, url in endpoints.items()
        }
    return {
        "access_status": "tested_with_key",
        "authentication": "API key",
        "tested_tickers": list(TARGETS),
        "ticker_results": results,
    }


def static_candidates() -> dict[str, dict[str, Any]]:
    return {
        "issuer_ir": {
            "access_status": "not_tested_rejected_automated_ingestion",
            "authentication": "none",
            "tested_tickers": [],
            "reason": "Use official pages only as human-readable links; automated ingestion/public redistribution rights are prohibited or unclear. Use SEC-hosted exhibits instead.",
        },
        "fred": {
            "access_status": "not_tested_rejected_terms",
            "authentication": "API key required, but no key is needed for this project",
            "tested_tickers": [],
            "reason": "Current FRED terms prohibit storing, caching or archiving FRED Content and providing it to third parties, which conflicts with committed static JSON.",
        },
        "nasdaq_data_link": {
            "access_status": "not_tested_no_key",
            "authentication": "API key via NASDAQ_DATA_LINK_API_KEY",
            "tested_tickers": [],
            "reason": "No dataset with confirmed public-display rights was selected; licenses are dataset-specific.",
        },
        "yahoo_finance": {
            "access_status": "not_tested_rejected",
            "authentication": "no documented Yahoo Finance public API selected",
            "tested_tickers": [],
            "reason": "Automated access and redistribution rights are not established for the undocumented endpoint.",
        },
        "yfinance": {
            "access_status": "not_tested_rejected",
            "authentication": "unofficial adapter",
            "tested_tickers": [],
            "reason": "Library code license is not a data redistribution license.",
        },
        "finance_datareader": {
            "access_status": "not_tested_rejected",
            "authentication": "crawler adapter",
            "tested_tickers": [],
            "reason": "Underlying source automation and redistribution rights are not established.",
        },
        "tradingview": {
            "access_status": "not_tested_rejected",
            "authentication": "not applicable",
            "tested_tickers": [],
            "reason": "Ingestion and non-display machine processing are out of scope and prohibited by policy.",
        },
        "finviz": {
            "access_status": "not_tested_rejected",
            "authentication": "no public documented ingestion API selected",
            "tested_tickers": [],
            "reason": "Public API contract and redistribution grant were not found.",
        },
    }


def build_report(*, timeout: float, include_keyed: bool, selected: set[str] | None) -> dict[str, Any]:
    probes = {
        "sec": lambda: probe_sec(timeout=timeout),
        "us_treasury": lambda: probe_treasury(timeout=timeout),
        "damodaran": lambda: probe_damodaran(timeout=timeout),
        "alpha_vantage": lambda: probe_alpha_vantage(timeout=timeout, include_keyed=include_keyed),
        "financial_modeling_prep": lambda: probe_fmp(timeout=timeout, include_keyed=include_keyed),
        "twelve_data": lambda: probe_twelve_data(timeout=timeout, include_keyed=include_keyed),
    }
    providers: dict[str, Any] = {}
    for name, probe in probes.items():
        if selected is None or name in selected:
            providers[name] = probe()
    for name, result in static_candidates().items():
        if selected is None or name in selected:
            providers[name] = result
    return {
        "schema_version": "valuation-provider-probe-v1",
        "tested_at": iso_now(),
        "mode": "read_only_audit",
        "targets": list(TARGETS),
        "raw_responses_persisted": False,
        "api_keys_printed": False,
        "providers": providers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--sec-strict-gate",
        action="store_true",
        help="Run the fail-closed MSFT/NVDA/MU SEC runner access gate only",
    )
    parser.add_argument(
        "--sec-user-agent-from-repository-variable",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--include-keyed",
        action="store_true",
        help="Run optional commercial-provider probes when their environment keys are present",
    )
    parser.add_argument(
        "--providers",
        help="Comma-separated provider IDs; default runs all safe probes and records rejected candidates",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    args = parser.parse_args()

    if args.sec_strict_gate:
        if args.providers or args.include_keyed:
            parser.error("--sec-strict-gate cannot be combined with provider audit options")
        user_agent = os.environ.get("SEC_USER_AGENT", "")
        user_agent_status = "ok" if user_agent.strip() else "missing_user_agent"
        if args.sec_user_agent_from_repository_variable:
            user_agent, user_agent_status = fetch_github_repository_variable(
                "SEC_USER_AGENT", timeout=args.timeout
            )
        records, gate_status, exit_code = run_sec_strict_gate(
            user_agent=user_agent,
            timeout=args.timeout,
        )
        if not user_agent and user_agent_status != "missing_user_agent":
            for record in records:
                record["schema_status"] = user_agent_status
        print_sec_strict_gate(records, gate_status)
        return exit_code

    if args.sec_user_agent_from_repository_variable:
        parser.error(
            "--sec-user-agent-from-repository-variable requires --sec-strict-gate"
        )

    selected = None
    if args.providers:
        selected = {value.strip() for value in args.providers.split(",") if value.strip()}
    report = build_report(timeout=args.timeout, include_keyed=args.include_keyed, selected=selected)
    json.dump(
        report,
        sys.stdout,
        ensure_ascii=False,
        indent=None if args.compact else 2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
