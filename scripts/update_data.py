#!/usr/bin/env python3
"""Generate static valuation JSON for GitHub Pages.

The script intentionally fetches public data at build time instead of relying on
browser-side third-party API calls.  That keeps the published page same-origin,
reproducible, and compatible with GitHub Pages.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Allow both `python scripts/update_data.py` and package-style test imports.
    from .valuation_core import (
        DEFAULT_ASSUMPTIONS,
        build_reverse_dcf,
        build_sensitivity,
        calculate_dcf,
        calculate_relative_valuation,
        classify_quality,
        derive_growth_rate,
        normalize_fcf,
        summarize_sensitivity,
    )
except ImportError:  # pragma: no cover - exercised when run as a script
    from valuation_core import (
        DEFAULT_ASSUMPTIONS,
        build_reverse_dcf,
        build_sensitivity,
        calculate_dcf,
        calculate_relative_valuation,
        classify_quality,
        derive_growth_rate,
        normalize_fcf,
        summarize_sensitivity,
    )

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1mo&interval=1d"
DEFAULT_USER_AGENT = os.environ.get("SEC_USER_AGENT", "")
TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,14}$")
DEFAULT_TICKERS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "JPM",
    "MA",
    "JNJ",
    "LLY",
    "UNH",
    "XOM",
    "WMT",
    "COST",
    "PG",
    "KO",
    "CAT",
    "NEE",
    "PLD",
    "LIN",
]

METHODOLOGY_REFERENCES = [
    {
        "key": "cfa-free-cash-flow",
        "title": "CFA Institute Free Cash Flow Valuation",
        "url": "https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation",
        "use": "FCFF/FCFE 현금흐름 기반 절대가치와 민감도 해석 기준",
    },
    {
        "key": "cfa-market-multiples",
        "title": "CFA Institute Market-Based Valuation: Price and Enterprise Value Multiples",
        "url": "https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples",
        "use": "PER/PBR/P/S/P/FCF 배수 비교의 조건과 한계",
    },
    {
        "key": "cfa-equity-valuation-tools",
        "title": "CFA Institute Equity Valuation: Concepts and Basic Tools",
        "url": "https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/equity-valuation-concepts-basic-tools",
        "use": "복수 가치평가 모델, 입력값 판단, 단순성 원칙",
    },
    {
        "key": "damodaran-terminal-value",
        "title": "Aswath Damodaran, Terminal Value Approaches",
        "url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/termvalapproaches.htm",
        "use": "안정성장 터미널 가치와 영구성장률 점검",
    },
    {
        "key": "damodaran-terminal-reinvestment",
        "title": "Aswath Damodaran, Closure in Valuation: Estimating Terminal Value",
        "url": "https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/termvalue.pdf",
        "use": "영구성장률, 재투자율, 자본수익률의 경제적 일관성",
    },
    {
        "key": "fama-french-1992",
        "title": "Fama and French (1992), The Cross-Section of Expected Stock Returns",
        "url": "https://doi.org/10.1111/j.1540-6261.1992.tb04398.x",
        "use": "규모와 book-to-market 등 상대가치 신호가 위험/수익률 해석과 연결될 수 있음을 환기",
    },
    {
        "key": "investor-edgar",
        "title": "Investor.gov Using EDGAR to Research Investments",
        "url": "https://www.investor.gov/introduction-investing/getting-started/researching-investments/using-edgar-research-investments",
        "use": "공시 원문 확인과 데이터 품질 검증",
    },
    {
        "key": "sec-edgar-apis",
        "title": "SEC EDGAR Application Programming Interfaces",
        "url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        "use": "SEC submissions/companyfacts JSON 원천과 정적 데이터 갱신",
    },
]

MODEL_POLICY = {
    "forecastVariablePolicy": "Keep explicit forecast variables sparse: normalized FCF, growth, discount rate, terminal growth, cash/debt, shares, and comparison multiples.",
    "dcfMethod": "FCFF-style DCF with Gordon stable-growth terminal value and terminal-value diagnostics.",
    "relativeMethod": "PER/PBR headline range with P/S and P/FCF as auxiliary cross-checks only.",
    "decisionOwner": "The user, not the model, owns final valuation judgment and must verify assumptions and comparable multiples.",
}

SCHEMA_REVISION = "1.1"
SCHEMA_CAPABILITIES = [
    "dcfSensitivitySummary",
    "reverseDcf",
    "relativeQualityGate",
]

SECTOR_LABELS = {
    "Technology": "기술",
    "Communication Services": "커뮤니케이션",
    "Consumer Discretionary": "임의소비재",
    "Consumer Staples": "필수소비재",
    "Financials": "금융",
    "Healthcare": "헬스케어",
    "Energy": "에너지",
    "Industrials": "산업재",
    "Utilities": "유틸리티",
    "Real Estate": "부동산",
    "Materials": "소재",
    "Other": "기타",
}

TICKER_CLASSIFICATION_OVERRIDES = {
    "AAPL": ("Technology", ["Consumer Tech", "Devices", "Services"]),
    "MSFT": ("Technology", ["Cloud", "AI", "Software"]),
    "NVDA": ("Technology", ["AI", "Semiconductors", "Accelerated Computing"]),
    "GOOGL": ("Communication Services", ["Search", "Advertising", "AI"]),
    "META": ("Communication Services", ["Social", "Advertising", "AI"]),
    "AMZN": ("Consumer Discretionary", ["E-commerce", "Cloud", "Logistics"]),
    "TSLA": ("Consumer Discretionary", ["EV", "Autonomy", "Manufacturing"]),
    "JPM": ("Financials", ["Banking", "Credit", "Capital Markets"]),
    "V": ("Financials", ["Payments", "Network", "Consumer Spending"]),
    "MA": ("Financials", ["Payments", "Network", "Consumer Spending"]),
    "JNJ": ("Healthcare", ["Pharma", "MedTech", "Defensive"]),
    "LLY": ("Healthcare", ["Pharma", "GLP-1", "Innovation"]),
    "UNH": ("Healthcare", ["Managed Care", "Insurance", "Healthcare Services"]),
    "XOM": ("Energy", ["Oil & Gas", "Commodity", "Cash Flow"]),
    "WMT": ("Consumer Staples", ["Retail", "Scale", "Defensive"]),
    "COST": ("Consumer Staples", ["Retail", "Membership", "Scale"]),
    "PG": ("Consumer Staples", ["Brands", "Household", "Defensive"]),
    "KO": ("Consumer Staples", ["Beverages", "Brands", "Defensive"]),
    "CAT": ("Industrials", ["Machinery", "Infrastructure", "Cycle"]),
    "NEE": ("Utilities", ["Utility", "Renewables", "Dividend"]),
    "PLD": ("Real Estate", ["REIT", "Logistics", "Real Assets"]),
    "LIN": ("Materials", ["Industrial Gas", "Materials", "Pricing Power"]),
}

SIC_SECTOR_RULES = [
    ((1000, 1499), "Energy"),
    ((2000, 2099), "Consumer Staples"),
    ((2800, 2899), "Healthcare"),
    ((3500, 3699), "Technology"),
    ((3700, 3799), "Industrials"),
    ((4800, 4899), "Communication Services"),
    ((4900, 4999), "Utilities"),
    ((5300, 5399), "Consumer Discretionary"),
    ((5400, 5499), "Consumer Staples"),
    ((5800, 5899), "Consumer Discretionary"),
    ((6000, 6499), "Financials"),
    ((6500, 6799), "Real Estate"),
    ((7000, 7399), "Technology"),
]

TAG_GROUPS = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "operatingIncome": ["OperatingIncomeLoss"],
    "netIncome": ["NetIncomeLoss", "ProfitLoss"],
    "operatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capitalExpenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "debtCurrent": ["LongTermDebtCurrent", "ShortTermBorrowings", "ShortTermDebtCurrent"],
    "debtNoncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"],
    "sharesDiluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "sharesBasic": ["WeightedAverageNumberOfSharesOutstandingBasic"],
}

USD_UNIT_PREFERENCE = ("USD",)
SHARE_UNIT_PREFERENCE = ("shares",)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def infer_sector_from_sic(sic: str | int | None) -> str:
    try:
        sic_number = int(str(sic))
    except (TypeError, ValueError):
        return "Other"
    for (lower, upper), sector in SIC_SECTOR_RULES:
        if lower <= sic_number <= upper:
            return sector
    return "Other"


def classify_company(ticker: str, submissions: dict[str, Any], ticker_meta: dict[str, Any]) -> dict[str, Any]:
    """Attach broad sector/theme metadata for navigation, not for model fitting."""

    override = TICKER_CLASSIFICATION_OVERRIDES.get(ticker)
    source = "ticker-override"
    if override:
        sector, themes = override
    else:
        sector = infer_sector_from_sic(submissions.get("sic"))
        source = "sic-range" if sector != "Other" else "unclassified"
        themes = []

    if not themes:
        description = " ".join(
            str(value or "")
            for value in [ticker_meta.get("name"), submissions.get("sicDescription"), submissions.get("entityType")]
        ).lower()
        theme_rules = [
            ("bank", "Banking"),
            ("insurance", "Insurance"),
            ("semiconductor", "Semiconductors"),
            ("software", "Software"),
            ("pharmaceutical", "Pharma"),
            ("retail", "Retail"),
            ("real estate", "Real Assets"),
            ("utility", "Utility"),
            ("oil", "Oil & Gas"),
            ("gas", "Oil & Gas"),
        ]
        themes = [label for needle, label in theme_rules if needle in description]
    if not themes:
        themes = [sector]

    deduped_themes = list(dict.fromkeys(themes[:4]))
    return {
        "sector": sector,
        "sectorLabel": SECTOR_LABELS.get(sector, sector),
        "themeTags": deduped_themes,
        "classificationSource": source,
    }


def request_json(url: str, user_agent: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return json.loads(body.decode("utf-8"))


def load_ticker_map(user_agent: str) -> dict[str, dict[str, Any]]:
    payload = request_json(SEC_TICKERS_URL, user_agent)
    fields = payload.get("fields", [])
    data = payload.get("data", [])
    result = {}
    for row in data:
        item = dict(zip(fields, row))
        ticker = str(item.get("ticker", "")).upper()
        if ticker:
            result[ticker] = {
                "cik": str(item.get("cik", "")).zfill(10),
                "name": item.get("name"),
                "ticker": ticker,
                "exchange": item.get("exchange"),
            }
    return result


def unit_values(concept: dict[str, Any], preferred_units: tuple[str, ...]) -> list[tuple[str, dict[str, Any]]]:
    units = concept.get("units", {}) if concept else {}
    values: list[tuple[str, dict[str, Any]]] = []
    for unit in preferred_units:
        if unit in units:
            values.extend((unit, fact) for fact in units[unit])
    return values


def choose_fact_value(facts: dict[str, Any], tags: list[str], preferred_units: tuple[str, ...], *, fy: int | None = None, annual: bool = True) -> tuple[float | None, str | None, dict[str, Any] | None, str | None]:
    candidates = []
    for tag in tags:
        for unit, fact in unit_values(facts.get(tag, {}), preferred_units):
            if fact.get("val") is None:
                continue
            if annual:
                if fact.get("form") not in {"10-K", "10-K/A", "20-F", "40-F", "20-F/A", "40-F/A"}:
                    continue
                if fact.get("fp") not in {"FY", None}:
                    continue
            if fy is not None and fact.get("fy") != fy:
                continue
            filed = fact.get("filed") or fact.get("end") or ""
            candidates.append((str(filed), tag, fact, unit))
    if not candidates:
        return None, None, None, None
    candidates.sort(key=lambda item: item[0])
    _, tag, fact, unit = candidates[-1]
    try:
        return float(fact["val"]), tag, fact, unit
    except (TypeError, ValueError):
        return None, tag, fact, unit


def available_fiscal_years(facts: dict[str, Any]) -> list[int]:
    years = set()
    for tag in TAG_GROUPS["revenue"] + TAG_GROUPS["netIncome"] + TAG_GROUPS["operatingCashFlow"]:
        for _, fact in unit_values(facts.get(tag, {}), USD_UNIT_PREFERENCE):
            fy = fact.get("fy")
            if fact.get("form") in {"10-K", "10-K/A", "20-F", "40-F", "20-F/A", "40-F/A"} and isinstance(fy, int):
                years.add(fy)
    return sorted(years)


def build_annual_rows(companyfacts: dict[str, Any], max_years: int = 5) -> tuple[list[dict[str, Any]], list[str]]:
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    warnings = []
    rows = []
    for fy in available_fiscal_years(us_gaap)[-max_years:]:
        row: dict[str, Any] = {"fy": fy}
        row_sources = {}
        for key, tags in TAG_GROUPS.items():
            if key in {"sharesOutstanding"}:
                continue
            units = SHARE_UNIT_PREFERENCE if key.startswith("shares") else USD_UNIT_PREFERENCE
            value, tag, fact, unit = choose_fact_value(us_gaap, tags, units, fy=fy, annual=True)
            if value is not None:
                row[key] = value
                row_sources[key] = {"tag": tag, "unit": unit, "filed": fact.get("filed"), "form": fact.get("form"), "end": fact.get("end")}
        if row.get("operatingCashFlow") is not None and row.get("capitalExpenditures") is not None:
            row["freeCashFlow"] = row["operatingCashFlow"] - abs(row["capitalExpenditures"])
            row["freeCashFlowStatus"] = "reported_capex"
        elif row.get("operatingCashFlow") is not None:
            row["freeCashFlowStatus"] = "missing_capex_excluded"
            warnings.append(f"{fy}년 CAPEX 태그가 없어 해당 연도는 FCF 정규화에서 제외했습니다.")
        row["sourceTags"] = row_sources
        rows.append(row)
    if not rows:
        warnings.append("SEC annual facts에서 사용 가능한 연간 재무제표 행을 찾지 못했습니다.")
    return rows, warnings


def latest_period_value(companyfacts: dict[str, Any], key: str) -> tuple[float | None, str | None]:
    us_gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    units = SHARE_UNIT_PREFERENCE if key.startswith("shares") else USD_UNIT_PREFERENCE
    value, tag, _, _ = choose_fact_value(us_gaap, TAG_GROUPS[key], units, fy=None, annual=False)
    return value, tag


def fetch_market_snapshot(ticker: str, user_agent: str) -> tuple[dict[str, Any], list[str]]:
    warnings = []
    url = YAHOO_CHART_URL.format(ticker=urllib.parse.quote(ticker))
    try:
        payload = request_json(url, user_agent, timeout=20)
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            raise ValueError("empty Yahoo chart result")
        meta = result.get("meta", {})
        timestamp = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        closes = [value for value in quote.get("close", []) if value is not None]
        price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
        as_of = None
        if timestamp:
            as_of = datetime.fromtimestamp(timestamp[-1], tz=timezone.utc).date().isoformat()
        return {
            "price": float(price) if price is not None else None,
            "currency": meta.get("currency") or "USD",
            "asOf": as_of,
            "source": "Yahoo chart endpoint (best effort)",
            "sourceUrl": url,
            "confidence": "best-effort",
        }, warnings
    except Exception as exc:  # noqa: BLE001 - surfaced as data-quality warning
        warnings.append(f"시장가격 스냅샷 수집 실패: {exc}")
        return {
            "price": None,
            "currency": "USD",
            "asOf": None,
            "source": "Unavailable",
            "sourceUrl": url,
            "confidence": "missing",
        }, warnings


def build_company_payload(
    ticker: str,
    ticker_meta: dict[str, Any],
    user_agent: str,
    verbose: bool = False,
    manual_price: float | None = None,
) -> dict[str, Any]:
    cik = ticker_meta["cik"]
    if verbose:
        print(f"Fetching {ticker} CIK{cik}")
    submissions_url = SEC_SUBMISSIONS_URL.format(cik=cik)
    companyfacts_url = SEC_COMPANYFACTS_URL.format(cik=cik)
    submissions = request_json(submissions_url, user_agent)
    companyfacts = request_json(companyfacts_url, user_agent)
    classification = classify_company(ticker, submissions, ticker_meta)
    market, market_warnings = fetch_market_snapshot(ticker, user_agent)
    if manual_price is not None:
        market = {
            **market,
            "price": float(manual_price),
            "source": "Manual override",
            "sourceUrl": None,
            "confidence": "manual",
        }

    annual_rows, annual_warnings = build_annual_rows(companyfacts)
    latest = sorted(annual_rows, key=lambda row: row.get("fy") or 0)[-1] if annual_rows else {}

    warnings = list(annual_warnings) + list(market_warnings)
    shares = latest.get("sharesDiluted") or latest.get("sharesBasic")
    if not shares:
        shares, shares_tag = latest_period_value(companyfacts, "sharesDiluted")
        if not shares:
            shares, shares_tag = latest_period_value(companyfacts, "sharesBasic")
        if shares:
            warnings.append(f"최근 연간 희석주식수 대신 최신 사용 가능 주식수 태그({shares_tag})를 사용했습니다.")
    if not shares or shares <= 0:
        warnings.append("주식수 데이터가 없어 주당 가치평가가 제한됩니다.")

    cash = latest.get("cash") or 0.0
    debt = (latest.get("debtCurrent") or 0.0) + (latest.get("debtNoncurrent") or 0.0)
    recent_rows = sorted(annual_rows, key=lambda row: row.get("fy") or 0, reverse=True)[:3]
    recent_confirmed_fcf = [row for row in recent_rows if row.get("freeCashFlow") is not None]
    base_fcf = normalize_fcf(annual_rows)
    if len(recent_confirmed_fcf) < 2:
        base_fcf = None
        warnings.append("최근 3년 중 CAPEX가 확인된 FCF가 2개 미만이어서 DCF를 수동 확인 대상으로 격하했습니다.")
    if base_fcf is None:
        warnings.append("자유현금흐름을 산출할 수 없어 DCF 기준값이 제한됩니다.")

    growth_rate = derive_growth_rate(annual_rows)
    assumptions = dict(DEFAULT_ASSUMPTIONS)
    assumptions.update({
        "growthRate": growth_rate,
        "baseFreeCashFlow": base_fcf,
        "cash": cash,
        "debt": debt,
        "sharesOutstanding": shares,
        "note": "기본값은 SEC 과거 재무제표에서 보수적으로 유도했으며 사용자가 직접 수정해야 합니다.",
        "modelPolicy": MODEL_POLICY,
    })

    dcf = None
    sensitivity = []
    sensitivity_summary = None
    reverse_dcf = None
    if base_fcf is not None and shares and shares > 0:
        try:
            dcf = calculate_dcf(
                base_fcf=base_fcf,
                shares_outstanding=shares,
                cash=cash,
                debt=debt,
                growth_rate=assumptions["growthRate"],
                discount_rate=assumptions["discountRate"],
                terminal_growth_rate=assumptions["terminalGrowthRate"],
                projection_years=assumptions["projectionYears"],
            )
            sensitivity = build_sensitivity(
                base_fcf=base_fcf,
                shares_outstanding=shares,
                cash=cash,
                debt=debt,
                growth_rate=assumptions["growthRate"],
                projection_years=assumptions["projectionYears"],
            )
            sensitivity_summary = summarize_sensitivity(
                sensitivity,
                base_value=dcf.get("perShareValue") if dcf else None,
                market_price=market.get("price"),
            )
            reverse_dcf = build_reverse_dcf(
                market_price=market.get("price"),
                base_fcf=base_fcf,
                shares_outstanding=shares,
                cash=cash,
                debt=debt,
                growth_rate=assumptions["growthRate"],
                discount_rate=assumptions["discountRate"],
                terminal_growth_rate=assumptions["terminalGrowthRate"],
                projection_years=assumptions["projectionYears"],
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"DCF 산출 실패: {exc}")
    else:
        warnings.append("DCF 산출에 필요한 FCF 또는 주식수 데이터가 부족합니다.")
        reverse_dcf = build_reverse_dcf(
            market_price=market.get("price"),
            base_fcf=base_fcf,
            shares_outstanding=shares,
            cash=cash,
            debt=debt,
            growth_rate=assumptions["growthRate"],
            discount_rate=assumptions["discountRate"],
            terminal_growth_rate=assumptions["terminalGrowthRate"],
            projection_years=assumptions["projectionYears"],
        )

    relative = None
    if shares and shares > 0:
        try:
            relative = calculate_relative_valuation(
                price=market.get("price"),
                revenue=latest.get("revenue"),
                net_income=latest.get("netIncome"),
                equity=latest.get("equity"),
                free_cash_flow=latest.get("freeCashFlow"),
                shares_outstanding=shares,
                benchmark_pe=assumptions["benchmarkPe"],
                benchmark_pb=assumptions["benchmarkPb"],
                benchmark_ps=assumptions["benchmarkPs"],
                benchmark_pfcf=assumptions["benchmarkPfcf"],
                benchmark_source="illustrative-default",
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"상대가치 산출 실패: {exc}")
    else:
        warnings.append("상대가치 산출에 필요한 주식수 데이터가 부족합니다.")

    method_comparison = {
        "dcfPerShare": dcf.get("perShareValue") if dcf else None,
        "relativePerShare": relative.get("range", {}).get("mid") if relative else None,
        "relativeConfirmed": False,
        "note": "DCF와 PER/PBR 상대가치는 평균내지 않습니다. 상대가치는 사용자 배수 확인 전 예시값입니다.",
    }

    required_missing = not annual_rows or not shares or base_fcf is None
    quality_status = classify_quality(warnings, fatal_missing=required_missing)
    entity_name = companyfacts.get("entityName") or submissions.get("name") or ticker_meta.get("name")
    generated_at = now_iso()

    return {
        "schemaVersion": 1,
        "schemaRevision": SCHEMA_REVISION,
        "schemaCapabilities": SCHEMA_CAPABILITIES,
        "generatedAt": generated_at,
        "company": {
            "ticker": ticker,
            "cik": cik,
            "name": entity_name,
            "exchange": ticker_meta.get("exchange") or submissions.get("exchanges", [None])[0],
            "sector": classification["sector"],
            "sectorLabel": classification["sectorLabel"],
            "themeTags": classification["themeTags"],
            "classificationSource": classification["classificationSource"],
            "sic": submissions.get("sic"),
            "sicDescription": submissions.get("sicDescription"),
            "entityType": submissions.get("entityType"),
            "currency": market.get("currency") or "USD",
        },
        "sources": {
            "sec": {
                "confidence": "baseline",
                "submissionsUrl": submissions_url,
                "companyfactsUrl": companyfacts_url,
                "note": "SEC EDGAR companyfacts/submissions에서 추출한 공개 재무제표 데이터입니다.",
            },
            "market": market,
            "methodology": METHODOLOGY_REFERENCES,
        },
        "market": market,
        "financials": {
            "currency": "USD",
            "annual": annual_rows,
            "latest": latest,
        },
        "assumptions": assumptions,
        "valuations": {
            "dcf": dcf,
            "dcfSensitivity": sensitivity,
            "dcfSensitivitySummary": sensitivity_summary,
            "reverseDcf": reverse_dcf,
            "relative": relative,
            "methodComparison": method_comparison,
        },
        "quality": {
            "status": quality_status,
            "warnings": warnings,
            "guardrails": [
                "이 결과는 투자 의견이 아니라 사용자의 판단을 돕는 계산 보조 자료입니다.",
                "DCF는 성장률·할인율·영구성장률 가정에 매우 민감합니다.",
                "터미널 가치 비중이 높을수록 안정성장 가정을 더 보수적으로 검토하세요.",
                "상대가치는 비교 배수 선택에 따라 크게 달라집니다.",
                "PER/PBR은 수익성, 성장률, 위험, 회계 품질이 유사한 비교군에서만 해석력이 커집니다.",
                "SEC 재무 데이터와 시장가격 스냅샷의 신뢰도를 분리해서 확인하세요.",
            ],
        },
    }


def compact_index_item(payload: dict[str, Any]) -> dict[str, Any]:
    company = payload["company"]
    market = payload["market"]
    valuations = payload["valuations"]
    return {
        "ticker": company["ticker"],
        "name": company.get("name"),
        "exchange": company.get("exchange"),
        "sector": company.get("sector"),
        "sectorLabel": company.get("sectorLabel"),
        "themeTags": company.get("themeTags") or [],
        "currency": company.get("currency"),
        "price": market.get("price"),
        "priceAsOf": market.get("asOf"),
        "qualityStatus": payload.get("quality", {}).get("status"),
        "companyFile": f"companies/{company['ticker']}.json",
        "dcfPerShare": (valuations.get("dcf") or {}).get("perShareValue"),
        "dcfFragility": (valuations.get("dcfSensitivitySummary") or {}).get("fragility"),
        "reverseDcfStatus": (valuations.get("reverseDcf") or {}).get("status"),
        "generatedAt": payload.get("generatedAt"),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def build_public_summary(index: dict[str, Any], output: Path) -> dict[str, Any]:
    """Build the compact cross-project summary consumed by quant-dashboard.

    The full valuation workspace intentionally keeps ticker-level company files
    in ``companies/*.json``.  This contract gives the hub enough context for a
    fast first paint and ticker/theme dossier without weakening the local
    "the user owns judgment" model.
    """

    tickers = index.get("tickers") if isinstance(index.get("tickers"), list) else []
    generated_at = index.get("generatedAt")
    sectors = sorted({str(item.get("sectorLabel") or item.get("sector")) for item in tickers if item.get("sectorLabel") or item.get("sector")})
    theme_counts: dict[str, int] = {}
    for item in tickers:
        for theme in item.get("themeTags") or []:
            theme_counts[str(theme)] = theme_counts.get(str(theme), 0) + 1
    primary_entities = []
    for item in tickers:
        primary_entities.append(
            {
                "symbol": item.get("ticker"),
                "name": item.get("name"),
                "label": f"{item.get('ticker')} · {item.get('sectorLabel') or item.get('sector') or '분류 N/A'}",
                "sector": item.get("sector"),
                "sectorLabel": item.get("sectorLabel"),
                "themes": item.get("themeTags") or [],
                "metrics": {
                    "price": item.get("price"),
                    "priceAsOf": item.get("priceAsOf"),
                    "dcfPerShare": item.get("dcfPerShare"),
                    "dcfFragility": item.get("dcfFragility"),
                    "reverseDcfStatus": item.get("reverseDcfStatus"),
                    "qualityStatus": item.get("qualityStatus"),
                },
                "signals": [
                    "DCF 절대가치와 PER/PBR 상대가치는 평균내지 않습니다.",
                    "상대가치 비교 배수는 사용자가 확인하기 전까지 의사결정 요약값이 아닙니다.",
                    "Reverse DCF는 목표가가 아니라 시장가격이 요구하는 성장 기대를 보여줍니다.",
                ],
                "warnings": ["SEC XBRL/가격 스냅샷의 기준일과 데이터 품질을 분리해서 확인하세요."],
                "detailPath": item.get("companyFile"),
            }
        )
    detail_path = output / "index.json"
    return {
        "schemaVersion": 1,
        "schemaRevision": SCHEMA_REVISION,
        "capabilities": SCHEMA_CAPABILITIES,
        "contract": "quant-research-summary",
        "projectId": "valuation",
        "projectName": "기업 가치평가 Lab",
        "generatedAt": generated_at,
        "dataAsOf": max((str(item.get("priceAsOf")) for item in tickers if item.get("priceAsOf")), default=None),
        "timezone": "UTC",
        "detailUrl": "https://sonchanggi.github.io/valuation/",
        "detailDataUrl": "https://sonchanggi.github.io/valuation/data/index.json",
        "status": {
            "state": "ok" if tickers else "degraded",
            "label": f"{len(tickers)}개 기업 가치평가 캐시",
            "cadence": "scheduled 14:15/16:15 KST Tue-Sat plus reviewed workflow_dispatch",
            "expectedFreshnessDays": 14,
        },
        "coverage": {
            "entityCount": len(tickers),
            "sectorCount": len(sectors),
            "sectors": sectors,
            "topThemes": [
                {"theme": theme, "count": count}
                for theme, count in sorted(theme_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:12]
            ],
        },
        "highlights": [
            {"label": "지원 티커", "value": len(tickers), "description": "SEC 공시 기반 정적 valuation 캐시"},
            {"label": "섹터", "value": len(sectors), "description": "섹터/테마 필터 지원"},
            {
                "label": "방법론",
                "value": len(index.get("methodologyReferences") or []),
                "description": "DCF, 상대가치, 진단 참고문헌",
            },
        ],
        "primaryEntities": primary_entities,
        "limitations": [
            "모형은 판단 주체가 아니라 계산 보조 도구입니다.",
            "DCF는 성장률·할인율·영구성장률에 민감합니다.",
            "PER/PBR 비교군은 사용자가 산업·성장률·ROE 유사성을 확인해야 합니다.",
        ],
        "sources": [
            {"label": "SEC EDGAR company facts", "url": "https://data.sec.gov/"},
            {"label": "Yahoo Chart best-effort price snapshot", "url": "https://query1.finance.yahoo.com/"},
        ],
        "automation": {
            "workflowUrl": "https://github.com/SonChangGi/valuation/actions/workflows/data-refresh.yml",
            "manualUpdateLabel": "GitHub Actions data-refresh 수동 실행",
            "tokenPolicy": "Static page keeps no secrets; SEC_USER_AGENT is required only in Actions/CLI.",
        },
        "payload": {
            "summaryBytes": None,
            "detailBytes": detail_path.stat().st_size if detail_path.exists() else None,
        },
    }


def parse_price_overrides(values: list[str]) -> dict[str, float]:
    overrides = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"Invalid --price-override {item!r}; expected TICKER=PRICE")
        ticker, value = item.split("=", 1)
        ticker = normalize_ticker(ticker)
        overrides[ticker] = float(value)
    return overrides


def normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise SystemExit(f"Invalid ticker {value!r}; expected 1-15 chars matching {TICKER_PATTERN.pattern}")
    return ticker


def normalize_tickers(values: list[str]) -> list[str]:
    tickers = []
    for raw in values:
        for part in re.split(r"[\s,]+", raw.strip()):
            if part:
                tickers.append(normalize_ticker(part))
    return list(dict.fromkeys(tickers))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS, help="Tickers to generate")
    parser.add_argument("--output", default="docs/data", help="Output data directory")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="SEC-compliant descriptive User-Agent with contact")
    parser.add_argument("--sleep", type=float, default=0.15, help="Delay between SEC/company requests")
    parser.add_argument("--price-override", action="append", default=[], help="Manual market price override, e.g. AAPL=190.25")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.user_agent.strip():
        raise SystemExit("SEC User-Agent is required. Set SEC_USER_AGENT or pass --user-agent with a descriptive contact.")

    tickers = normalize_tickers(args.tickers)
    if not tickers:
        raise SystemExit("At least one ticker is required")
    output = Path(args.output)
    price_overrides = parse_price_overrides(args.price_override)

    ticker_map = load_ticker_map(args.user_agent)
    companies = []
    errors = []
    for ticker in tickers:
        meta = ticker_map.get(ticker)
        if not meta:
            errors.append({"ticker": ticker, "error": "SEC ticker/CIK mapping not found"})
            continue
        try:
            payload = build_company_payload(
                ticker,
                meta,
                args.user_agent,
                verbose=args.verbose,
                manual_price=price_overrides.get(ticker),
            )
            write_json(output / "companies" / f"{ticker}.json", payload)
            companies.append(compact_index_item(payload))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            errors.append({"ticker": ticker, "error": str(exc)})
        time.sleep(max(0, args.sleep))

    index = {
        "schemaVersion": 1,
        "schemaRevision": SCHEMA_REVISION,
        "schemaCapabilities": SCHEMA_CAPABILITIES,
        "project": "valuation",
        "title": "Stock Valuation Workspace",
        "generatedAt": now_iso(),
        "basePath": "/valuation/",
        "dataPolicy": "Static JSON generated from public SEC fundamentals and best-effort market price snapshots.",
        "methodologyReferences": METHODOLOGY_REFERENCES,
        "modelPolicy": MODEL_POLICY,
        "tickers": companies,
        "errors": errors,
    }
    write_json(output / "index.json", index)
    summary = build_public_summary(index, output)
    write_json(output / "summary.json", summary)
    if args.verbose:
        print(f"Wrote {len(companies)} companies to {output}")
        if errors:
            print(json.dumps(errors, ensure_ascii=False, indent=2))
    if not companies:
        raise SystemExit("No company payloads generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
