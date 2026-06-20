#!/usr/bin/env python3
"""Offline validation for generated static valuation data and site assets."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    from .valuation_core import calculate_dcf, calculate_relative_valuation
except ImportError:  # pragma: no cover - exercised when run as a script
    from valuation_core import calculate_dcf, calculate_relative_valuation

REQUIRED_COMPANY_TOP_KEYS = {"schemaVersion", "generatedAt", "company", "sources", "market", "financials", "assumptions", "valuations", "quality"}
REQUIRED_COMPANY_FIELDS = {"ticker", "cik", "name", "currency", "sector", "sectorLabel", "themeTags"}
REQUIRED_VALUATION_KEYS = {"dcf", "dcfSensitivity", "dcfSensitivitySummary", "reverseDcf", "relative", "methodComparison"}
REQUIRED_SCHEMA_CAPABILITIES = {"dcfSensitivitySummary", "reverseDcf", "relativeQualityGate"}
MONETARY_FIELDS = {"revenue", "operatingIncome", "netIncome", "operatingCashFlow", "capitalExpenditures", "equity", "assets", "liabilities", "cash", "debtCurrent", "debtNoncurrent"}
SHARE_FIELDS = {"sharesDiluted", "sharesBasic"}


class ValidationFailure(AssertionError):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"{path}: invalid JSON: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationFailure(message)


def require_close(actual: float | None, expected: float | None, message: str, tolerance: float = 1e-6) -> None:
    if actual is None or expected is None:
        require(actual is expected, message)
        return
    require(math.isfinite(float(actual)), f"{message}: actual is not finite")
    require(math.isfinite(float(expected)), f"{message}: expected is not finite")
    scale = max(1.0, abs(float(expected)))
    require(abs(float(actual) - float(expected)) <= tolerance * scale, f"{message}: {actual} != {expected}")


def require_finite_numbers(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            require_finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            require_finite_numbers(child, f"{path}[{index}]")
    elif isinstance(value, float):
        require(math.isfinite(value), f"{path}: numeric value must be finite")


def validate_company(path: Path) -> list[str]:
    warnings: list[str] = []
    payload = read_json(path)
    missing = REQUIRED_COMPANY_TOP_KEYS - set(payload)
    require(not missing, f"{path}: missing top-level keys {sorted(missing)}")
    require(payload.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1")
    capabilities = set(payload.get("schemaCapabilities") or [])
    require(REQUIRED_SCHEMA_CAPABILITIES.issubset(capabilities), f"{path}: missing schema capabilities {sorted(REQUIRED_SCHEMA_CAPABILITIES - capabilities)}")

    company = payload["company"]
    missing_company = REQUIRED_COMPANY_FIELDS - set(company)
    require(not missing_company, f"{path}: missing company fields {sorted(missing_company)}")
    require(company["ticker"].isupper(), f"{path}: ticker should be uppercase")
    require(str(company["cik"]).isdigit() and len(str(company["cik"])) == 10, f"{path}: CIK must be zero-padded 10 digits")
    require(isinstance(company.get("themeTags"), list) and company["themeTags"], f"{path}: themeTags must be a non-empty list")
    require(payload.get("sources", {}).get("methodology"), f"{path}: methodology references are required")

    financials = payload["financials"]
    require(isinstance(financials.get("annual"), list), f"{path}: financials.annual must be a list")
    require(financials.get("latest") is not None, f"{path}: financials.latest required")
    if not financials["annual"]:
        warnings.append(f"{path}: no annual rows")
    for row in financials["annual"]:
        source_tags = row.get("sourceTags", {})
        for key in MONETARY_FIELDS & set(row):
            unit = (source_tags.get(key) or {}).get("unit")
            require(unit == "USD", f"{path}: {key} must have USD unit provenance")
        for key in SHARE_FIELDS & set(row):
            unit = (source_tags.get(key) or {}).get("unit")
            require(unit == "shares", f"{path}: {key} must have shares unit provenance")
        if row.get("freeCashFlow") is not None:
            require(row.get("freeCashFlowStatus") == "reported_capex", f"{path}: freeCashFlow requires reported_capex status")
            require("operatingCashFlow" in row and "capitalExpenditures" in row, f"{path}: freeCashFlow requires OCF and CAPEX")

    assumptions = payload["assumptions"]
    for key in ["projectionYears", "growthRate", "discountRate", "terminalGrowthRate", "benchmarkPe", "benchmarkPb"]:
        require(key in assumptions, f"{path}: assumptions.{key} required")
    require(assumptions["projectionYears"] >= 1, f"{path}: projection years must be positive")
    require(assumptions["discountRate"] > assumptions["terminalGrowthRate"], f"{path}: discountRate must exceed terminalGrowthRate")

    valuations = payload["valuations"]
    missing_valuations = REQUIRED_VALUATION_KEYS - set(valuations)
    require(not missing_valuations, f"{path}: missing valuations {sorted(missing_valuations)}")
    require("blendedRange" not in valuations, f"{path}: blendedRange must not be published")
    if valuations.get("dcf"):
        expected_dcf = calculate_dcf(
            base_fcf=assumptions["baseFreeCashFlow"],
            shares_outstanding=assumptions["sharesOutstanding"],
            cash=assumptions.get("cash") or 0,
            debt=assumptions.get("debt") or 0,
            growth_rate=assumptions["growthRate"],
            discount_rate=assumptions["discountRate"],
            terminal_growth_rate=assumptions["terminalGrowthRate"],
            projection_years=assumptions["projectionYears"],
        )
        require("perShareValue" in valuations["dcf"], f"{path}: DCF perShareValue required when DCF exists")
        require("diagnostics" in valuations["dcf"], f"{path}: DCF diagnostics required")
        require("terminalValueWeight" in valuations["dcf"]["diagnostics"], f"{path}: DCF terminal value weight required")
        require_close(valuations["dcf"]["perShareValue"], expected_dcf["perShareValue"], f"{path}: DCF perShareValue mismatch")
        require(len(valuations.get("dcfSensitivity") or []) >= 1, f"{path}: DCF sensitivity matrix required")
        sensitivity_summary = valuations.get("dcfSensitivitySummary") or {}
        require(sensitivity_summary.get("fragility") in {"stable", "sensitive", "fragile", "unavailable"}, f"{path}: DCF sensitivity fragility required")
        require("rangeToBase" in sensitivity_summary, f"{path}: DCF sensitivity rangeToBase required")
        reverse_dcf = valuations.get("reverseDcf") or {}
        require(reverse_dcf.get("status") in {"available", "not_available"}, f"{path}: reverseDcf status required")
        require("interpretation" in reverse_dcf, f"{path}: reverseDcf interpretation required")
    else:
        warnings.append(f"{path}: DCF missing")
    if valuations.get("relative"):
        relative = valuations["relative"]
        rows = relative.get("rows", [])
        labels = {row.get("label") for row in rows}
        require({"PER", "PBR"}.issubset(labels), f"{path}: PER and PBR rows are required")
        require((relative.get("range") or {}).get("basis") == "PER/PBR headline only", f"{path}: headline relative range must be PER/PBR only")
        require((relative.get("range") or {}).get("confirmed") is False, f"{path}: generated relative defaults must be unconfirmed")
        require("auxiliaryRange" in relative, f"{path}: auxiliary relative range required for P/S and P/FCF")
        require("qualitySignals" in relative and "diagnostics" in relative, f"{path}: relative quality signals and diagnostics required")
        quality_gate = relative.get("diagnostics", {}).get("qualityGate") or {}
        require(quality_gate.get("status") in {"limited", "needs_user_review", "usable_with_caution", "usable"}, f"{path}: relative quality gate required")
        require(isinstance(quality_gate.get("checks"), list) and quality_gate["checks"], f"{path}: relative quality gate checks required")
        expected_relative = calculate_relative_valuation(
            price=payload["market"].get("price"),
            revenue=financials["latest"].get("revenue"),
            net_income=financials["latest"].get("netIncome"),
            equity=financials["latest"].get("equity"),
            free_cash_flow=financials["latest"].get("freeCashFlow"),
            shares_outstanding=assumptions["sharesOutstanding"],
            benchmark_pe=assumptions["benchmarkPe"],
            benchmark_pb=assumptions["benchmarkPb"],
            benchmark_ps=assumptions["benchmarkPs"],
            benchmark_pfcf=assumptions["benchmarkPfcf"],
            benchmark_source=relative.get("benchmarkSource", "illustrative-default"),
        )
        require_close(relative["range"]["mid"], expected_relative["range"]["mid"], f"{path}: relative midpoint mismatch")
    else:
        warnings.append(f"{path}: relative valuation missing")
    method = valuations["methodComparison"]
    require(method.get("relativeConfirmed") is False, f"{path}: generated methodComparison relative value must be unconfirmed")

    quality = payload["quality"]
    require("status" in quality and "warnings" in quality and "guardrails" in quality, f"{path}: quality fields missing")
    require(any("투자" in text or "판단" in text for text in quality.get("guardrails", [])), f"{path}: judgment/investment guardrail required")
    require_finite_numbers(payload, str(path))

    return warnings


def validate_index(data_dir: Path) -> list[Path]:
    index_path = data_dir / "index.json"
    require(index_path.exists(), f"{index_path}: missing")
    index = read_json(index_path)
    require(index.get("schemaVersion") == 1, f"{index_path}: schemaVersion must be 1")
    capabilities = set(index.get("schemaCapabilities") or [])
    require(REQUIRED_SCHEMA_CAPABILITIES.issubset(capabilities), f"{index_path}: missing schema capabilities {sorted(REQUIRED_SCHEMA_CAPABILITIES - capabilities)}")
    require(index.get("basePath") == "/valuation/", f"{index_path}: basePath should be /valuation/")
    require(index.get("methodologyReferences"), f"{index_path}: methodologyReferences required")
    require(index.get("modelPolicy"), f"{index_path}: modelPolicy required")
    tickers = index.get("tickers")
    require(isinstance(tickers, list) and tickers, f"{index_path}: tickers must be a non-empty list")
    company_paths = []
    for item in tickers:
        for key in ["ticker", "name", "companyFile", "qualityStatus", "sector", "sectorLabel", "themeTags"]:
            require(key in item, f"{index_path}: ticker item missing {key}")
        require(isinstance(item.get("themeTags"), list) and item["themeTags"], f"{index_path}: ticker item themeTags required")
        require("relativeMid" not in item, f"{index_path}: unconfirmed relative midpoint must not be published in index")
        company_path = data_dir / item["companyFile"]
        require(company_path.exists(), f"{index_path}: referenced company file missing: {company_path}")
        company_paths.append(company_path)
    return company_paths


def validate_public_summary(data_dir: Path) -> None:
    summary_path = data_dir / "summary.json"
    require(summary_path.exists(), f"{summary_path}: missing")
    summary = read_json(summary_path)
    require(summary.get("schemaVersion") == 1, f"{summary_path}: schemaVersion must be 1")
    capabilities = set(summary.get("capabilities") or [])
    require(REQUIRED_SCHEMA_CAPABILITIES.issubset(capabilities), f"{summary_path}: missing capabilities {sorted(REQUIRED_SCHEMA_CAPABILITIES - capabilities)}")
    require(summary.get("contract") == "quant-research-summary", f"{summary_path}: contract mismatch")
    require(summary.get("projectId") == "valuation", f"{summary_path}: projectId mismatch")
    require(summary.get("generatedAt"), f"{summary_path}: generatedAt required")
    require(summary.get("status", {}).get("state") in {"ok", "degraded", "stale"}, f"{summary_path}: invalid status.state")
    entities = summary.get("primaryEntities")
    require(isinstance(entities, list) and entities, f"{summary_path}: primaryEntities required")
    for entity in entities:
        require(entity.get("symbol"), f"{summary_path}: entity symbol required")
        require(isinstance(entity.get("themes"), list), f"{summary_path}: entity themes must be a list")
    limitations = summary.get("limitations") or []
    require(any("판단" in str(item) for item in limitations), f"{summary_path}: user-judgment limitation required")


def validate_static_files(root: Path) -> None:
    html = root / "docs" / "index.html"
    css = root / "docs" / "assets" / "styles.css"
    app = root / "docs" / "assets" / "app.js"
    assumptions = root / "docs" / "assets" / "assumptions.js"
    model = root / "docs" / "assets" / "valuation-model.js"
    for path in [html, css, app, assumptions, model]:
        require(path.exists(), f"{path}: missing static asset")
    html_text = html.read_text(encoding="utf-8")
    for needle in ["Stock Valuation Workspace", "가치평가를 근거 있게", "티커", "가치평가", "사용자의 판단", "data/index.json", "Content-Security-Policy", "DCF와 상대가치는 평균내지 않습니다"]:
        require(needle in html_text, f"{html}: missing expected copy/reference {needle!r}")
    require("sonchanggi.github.io/quant-dashboard" in html_text, f"{html}: should reference dashboard only as navigation/reference")
    app_text = app.read_text(encoding="utf-8")
    require("fetch('data/index.json')" in app_text or 'fetch("data/index.json")' in app_text, f"{app}: should load same-origin data/index.json")
    require("query1.finance.yahoo" not in app_text and "data.sec.gov" not in app_text, f"{app}: browser app must not fetch third-party finance APIs")
    for path in [html, app, assumptions, model]:
        text = path.read_text(encoding="utf-8")
        require("blendedRange" not in text, f"{path}: DCF and relative valuations must not be blended")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="docs/data")
    parser.add_argument("--check-static", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    company_paths = validate_index(data_dir)
    validate_public_summary(data_dir)
    warnings = []
    for path in company_paths:
        warnings.extend(validate_company(path))
    if args.check_static:
        validate_static_files(Path.cwd())
    if warnings:
        print("Validation warnings:")
        for warning in warnings:
            print(f"- {warning}")
    print(f"Validated {len(company_paths)} company file(s) in {data_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationFailure as exc:
        print(f"VALIDATION FAILED: {exc}")
        raise SystemExit(1)
