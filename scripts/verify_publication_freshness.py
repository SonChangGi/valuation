#!/usr/bin/env python3
"""Fail unless Valuation publication contains broad, current market snapshots."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

try:
    from .check_data_freshness import latest_expected_us_session_date, parse_datetime
except ImportError:  # pragma: no cover - direct script execution
    from check_data_freshness import latest_expected_us_session_date, parse_datetime


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-file", type=Path, default=Path("docs/data/summary.json"))
    parser.add_argument("--timezone", default="Asia/Seoul")
    parser.add_argument("--now", help="Optional deterministic ISO timestamp")
    parser.add_argument("--min-market-coverage-ratio", type=float, default=0.90)
    parser.add_argument("--min-entities", type=int, default=10)
    parser.add_argument("--max-generated-lag-hours", type=float, default=36.0)
    return parser.parse_args(argv)


def read_summary(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary must be a JSON object")
    return payload


def parse_date(value: Any) -> dt.date:
    if not value:
        raise ValueError("missing date")
    return dt.date.fromisoformat(str(value)[:10])


def assess_publication(
    payload: dict[str, Any],
    *,
    now_utc: dt.datetime | None = None,
    timezone: str = "Asia/Seoul",
    min_market_coverage_ratio: float = 0.90,
    min_entities: int = 10,
    max_generated_lag_hours: float = 36.0,
) -> dict[str, Any]:
    if not 0 < min_market_coverage_ratio <= 1:
        raise ValueError("min_market_coverage_ratio must be in (0, 1]")
    now = now_utc or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    now = now.astimezone(dt.UTC)
    expected = latest_expected_us_session_date(now, timezone)
    generated_at = parse_datetime(str(payload.get("generatedAt") or ""))
    generated_lag_hours = (now - generated_at).total_seconds() / 3600
    data_as_of = parse_date(payload.get("dataAsOf"))
    entities = payload.get("primaryEntities") if isinstance(payload.get("primaryEntities"), list) else []
    dated_entities = []
    for entity in entities:
        metrics = entity.get("metrics") if isinstance(entity, dict) and isinstance(entity.get("metrics"), dict) else {}
        try:
            market_date = parse_date(metrics.get("priceAsOf"))
        except (TypeError, ValueError):
            continue
        if market_date >= expected:
            dated_entities.append(entity)
    coverage_ratio = len(dated_entities) / len(entities) if entities else 0.0
    problems = []
    if len(entities) < min_entities:
        problems.append(f"entity coverage {len(entities)} < {min_entities}")
    if generated_lag_hours < -1:
        problems.append("generatedAt is in the future")
    if generated_lag_hours > max_generated_lag_hours:
        problems.append(f"generatedAt lag {generated_lag_hours:.1f}h > {max_generated_lag_hours:.1f}h")
    if data_as_of < expected:
        problems.append(f"dataAsOf {data_as_of} < expected session {expected}")
    if coverage_ratio < min_market_coverage_ratio:
        problems.append(
            f"fresh market coverage {len(dated_entities)}/{len(entities)} "
            f"({coverage_ratio:.1%}) < {min_market_coverage_ratio:.1%}"
        )
    return {
        "status": "pass" if not problems else "fail",
        "generatedAt": generated_at.isoformat(),
        "generatedLagHours": round(generated_lag_hours, 3),
        "dataAsOf": data_as_of.isoformat(),
        "expectedDataAsOf": expected.isoformat(),
        "entityCount": len(entities),
        "freshMarketEntityCount": len(dated_entities),
        "freshMarketCoverageRatio": coverage_ratio,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = parse_datetime(args.now) if args.now else None
    report = assess_publication(
        read_summary(args.summary_file),
        now_utc=now,
        timezone=args.timezone,
        min_market_coverage_ratio=args.min_market_coverage_ratio,
        min_entities=args.min_entities,
        max_generated_lag_hours=args.max_generated_lag_hours,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
