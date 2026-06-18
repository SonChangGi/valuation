#!/usr/bin/env python3
"""Offline validation for generated static valuation data and site assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_COMPANY_TOP_KEYS = {"schemaVersion", "generatedAt", "company", "sources", "market", "financials", "assumptions", "valuations", "quality"}
REQUIRED_COMPANY_FIELDS = {"ticker", "cik", "name", "currency"}
REQUIRED_VALUATION_KEYS = {"dcf", "dcfSensitivity", "relative", "blendedRange"}


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


def validate_company(path: Path) -> list[str]:
    warnings: list[str] = []
    payload = read_json(path)
    missing = REQUIRED_COMPANY_TOP_KEYS - set(payload)
    require(not missing, f"{path}: missing top-level keys {sorted(missing)}")
    require(payload.get("schemaVersion") == 1, f"{path}: schemaVersion must be 1")

    company = payload["company"]
    missing_company = REQUIRED_COMPANY_FIELDS - set(company)
    require(not missing_company, f"{path}: missing company fields {sorted(missing_company)}")
    require(company["ticker"].isupper(), f"{path}: ticker should be uppercase")
    require(str(company["cik"]).isdigit() and len(str(company["cik"])) == 10, f"{path}: CIK must be zero-padded 10 digits")

    financials = payload["financials"]
    require(isinstance(financials.get("annual"), list), f"{path}: financials.annual must be a list")
    require(financials.get("latest") is not None, f"{path}: financials.latest required")
    if not financials["annual"]:
        warnings.append(f"{path}: no annual rows")

    assumptions = payload["assumptions"]
    for key in ["projectionYears", "growthRate", "discountRate", "terminalGrowthRate", "benchmarkPe", "benchmarkPb"]:
        require(key in assumptions, f"{path}: assumptions.{key} required")
    require(assumptions["projectionYears"] >= 1, f"{path}: projection years must be positive")
    require(assumptions["discountRate"] > assumptions["terminalGrowthRate"], f"{path}: discountRate must exceed terminalGrowthRate")

    valuations = payload["valuations"]
    missing_valuations = REQUIRED_VALUATION_KEYS - set(valuations)
    require(not missing_valuations, f"{path}: missing valuations {sorted(missing_valuations)}")
    if valuations.get("dcf"):
        require("perShareValue" in valuations["dcf"], f"{path}: DCF perShareValue required when DCF exists")
        require(len(valuations.get("dcfSensitivity") or []) >= 1, f"{path}: DCF sensitivity matrix required")
    else:
        warnings.append(f"{path}: DCF missing")
    if valuations.get("relative"):
        relative = valuations["relative"]
        rows = relative.get("rows", [])
        labels = {row.get("label") for row in rows}
        require({"PER", "PBR"}.issubset(labels), f"{path}: PER and PBR rows are required")
        require((relative.get("range") or {}).get("basis") == "PER/PBR headline only", f"{path}: headline relative range must be PER/PBR only")
        require("auxiliaryRange" in relative, f"{path}: auxiliary relative range required for P/S and P/FCF")
    else:
        warnings.append(f"{path}: relative valuation missing")

    quality = payload["quality"]
    require("status" in quality and "warnings" in quality and "guardrails" in quality, f"{path}: quality fields missing")
    require(any("투자" in text or "판단" in text for text in quality.get("guardrails", [])), f"{path}: judgment/investment guardrail required")

    return warnings


def validate_index(data_dir: Path) -> list[Path]:
    index_path = data_dir / "index.json"
    require(index_path.exists(), f"{index_path}: missing")
    index = read_json(index_path)
    require(index.get("schemaVersion") == 1, f"{index_path}: schemaVersion must be 1")
    require(index.get("basePath") == "/valuation/", f"{index_path}: basePath should be /valuation/")
    tickers = index.get("tickers")
    require(isinstance(tickers, list) and tickers, f"{index_path}: tickers must be a non-empty list")
    company_paths = []
    for item in tickers:
        for key in ["ticker", "name", "companyFile", "qualityStatus"]:
            require(key in item, f"{index_path}: ticker item missing {key}")
        company_path = data_dir / item["companyFile"]
        require(company_path.exists(), f"{index_path}: referenced company file missing: {company_path}")
        company_paths.append(company_path)
    return company_paths


def validate_static_files(root: Path) -> None:
    html = root / "docs" / "index.html"
    css = root / "docs" / "assets" / "styles.css"
    app = root / "docs" / "assets" / "app.js"
    model = root / "docs" / "assets" / "valuation-model.js"
    for path in [html, css, app, model]:
        require(path.exists(), f"{path}: missing static asset")
    html_text = html.read_text(encoding="utf-8")
    for needle in ["Stock Valuation Workspace", "티커", "가치평가", "사용자의 판단", "data/index.json"]:
        require(needle in html_text, f"{html}: missing expected copy/reference {needle!r}")
    require("sonchanggi.github.io/quant-dashboard" in html_text, f"{html}: should reference dashboard only as navigation/reference")
    app_text = app.read_text(encoding="utf-8")
    require("fetch('data/index.json')" in app_text or 'fetch("data/index.json")' in app_text, f"{app}: should load same-origin data/index.json")
    require("query1.finance.yahoo" not in app_text and "data.sec.gov" not in app_text, f"{app}: browser app must not fetch third-party finance APIs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="docs/data")
    parser.add_argument("--check-static", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    company_paths = validate_index(data_dir)
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
