#!/usr/bin/env python3
"""Decide whether scheduled valuation data refresh should regenerate docs/data.

The GitHub Actions schedule is staggered in KST after the expected U.S. close.
Scheduled runs should retry only while the committed static JSON is missing,
broken, generated before the current KST cutoff, or does not cover the latest
expected U.S. regular-session date. Manual dispatch remains a reviewed force
refresh path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_SUMMARY_PATH = Path("docs/data/summary.json")
DEFAULT_PRIMARY_CRONS = ("15 5 * * 2-6",)
DEFAULT_FALLBACK_CRONS = ("15 7 * * 2-6",)
DEFAULT_TIMEZONE = "Asia/Seoul"
DEFAULT_CUTOFF_HOUR_KST = 14
DEFAULT_CUTOFF_MINUTE_KST = 15


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", default=os.getenv("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--event-schedule", default=os.getenv("GITHUB_EVENT_SCHEDULE", ""))
    parser.add_argument("--summary-file", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--primary-cron", action="append", default=[])
    parser.add_argument("--fallback-cron", action="append", default=[])
    parser.add_argument("--now", help="Optional ISO timestamp for deterministic tests, e.g. 2026-06-30T05:30:00Z")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    now = parse_datetime(args.now) if args.now else dt.datetime.now(dt.UTC)
    result = decide_update(
        event_name=args.event_name,
        event_schedule=args.event_schedule,
        primary_crons=tuple(args.primary_cron or DEFAULT_PRIMARY_CRONS),
        fallback_crons=tuple(args.fallback_cron or DEFAULT_FALLBACK_CRONS),
        now_utc=now,
        timezone=args.timezone,
        summary_file=args.summary_file,
    )
    write_github_output(result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def decide_update(
    *,
    event_name: str,
    event_schedule: str = "",
    primary_crons: tuple[str, ...] = DEFAULT_PRIMARY_CRONS,
    fallback_crons: tuple[str, ...] = DEFAULT_FALLBACK_CRONS,
    now_utc: dt.datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    summary_file: Path = DEFAULT_SUMMARY_PATH,
) -> dict[str, str]:
    now_utc = ensure_utc(now_utc or dt.datetime.now(dt.UTC))
    event = (event_name or "").strip()
    schedule = (event_schedule or "").strip()
    local_now = now_utc.astimezone(ZoneInfo(timezone))
    expected = latest_expected_us_session_date(now_utc, timezone)
    cutoff = dt.datetime.combine(
        local_now.date(),
        dt.time(DEFAULT_CUTOFF_HOUR_KST, DEFAULT_CUTOFF_MINUTE_KST),
        tzinfo=ZoneInfo(timezone),
    )
    base = {
        "event_name": event or "unknown",
        "event_schedule": schedule or "none",
        "expected_data_as_of": expected.isoformat(),
        "cutoff_kst": cutoff.isoformat(),
        "timezone": timezone,
    }

    if event != "schedule":
        return {**base, "should_update": "true", "freshness_reason": "manual_or_non_schedule_refreshes"}
    if schedule not in primary_crons and schedule not in fallback_crons:
        return {**base, "should_update": "true", "freshness_reason": "unknown_schedule_refreshes_conservatively"}

    try:
        payload = load_payload(summary_file)
        generated_kst = parse_datetime(str(payload.get("generatedAt") or "")).astimezone(ZoneInfo(timezone))
        data_as_of = parse_date(payload.get("dataAsOf"))
    except Exception as exc:  # noqa: BLE001 - scheduled retries should repair missing/broken data.
        return {
            **base,
            "should_update": "true",
            "freshness_reason": f"freshness_check_failed:{type(exc).__name__}",
            "actual_data_as_of": "unknown",
            "actual_generated_kst": "unknown",
        }

    fresh_for_window = generated_kst >= cutoff and data_as_of >= expected
    return {
        **base,
        "should_update": "false" if fresh_for_window else "true",
        "freshness_reason": "fresh_for_kst_window_and_expected_us_session" if fresh_for_window else "stale_or_before_kst_window",
        "actual_data_as_of": data_as_of.isoformat(),
        "actual_generated_kst": generated_kst.isoformat(),
    }


def load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary JSON must be an object")
    return payload


def parse_date(value: Any) -> dt.date:
    if not value:
        raise ValueError("missing date")
    return dt.date.fromisoformat(str(value)[:10])


def parse_datetime(value: str) -> dt.datetime:
    if not value:
        raise ValueError("missing datetime")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ensure_utc(parsed)


def latest_expected_us_session_date(now_utc: dt.datetime, timezone: str = DEFAULT_TIMEZONE) -> dt.date:
    local_today = ensure_utc(now_utc).astimezone(ZoneInfo(timezone)).date()
    candidate = local_today - dt.timedelta(days=1)
    while not is_us_market_trading_day(candidate):
        candidate -= dt.timedelta(days=1)
    return candidate


def is_us_market_trading_day(day: dt.date) -> bool:
    if day.weekday() >= 5:
        return False
    holidays: set[dt.date] = set()
    for year in (day.year - 1, day.year, day.year + 1):
        holidays.update(nyse_holidays(year))
    return day not in holidays


def nyse_holidays(year: int) -> set[dt.date]:
    holidays = {
        observed_fixed(year, 1, 1),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_sunday(year) - dt.timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_fixed(year, 6, 19),
        observed_fixed(year, 7, 4),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_fixed(year, 12, 25),
    }
    if year < 2022:
        holidays.discard(observed_fixed(year, 6, 19))
    return holidays


def observed_fixed(year: int, month: int, day: int) -> dt.date:
    actual = dt.date(year, month, day)
    if actual.weekday() == 5:
        return actual - dt.timedelta(days=1)
    if actual.weekday() == 6:
        return actual + dt.timedelta(days=1)
    return actual


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> dt.date:
    day = dt.date(year, month, 1)
    while day.weekday() != weekday:
        day += dt.timedelta(days=1)
    return day + dt.timedelta(days=7 * (nth - 1))


def last_weekday(year: int, month: int, weekday: int) -> dt.date:
    day = dt.date(year + int(month == 12), 1 if month == 12 else month + 1, 1) - dt.timedelta(days=1)
    while day.weekday() != weekday:
        day -= dt.timedelta(days=1)
    return day


def easter_sunday(year: int) -> dt.date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def write_github_output(result: dict[str, str]) -> None:
    output = os.getenv("GITHUB_OUTPUT")
    if not output:
        return
    with Path(output).open("a", encoding="utf-8") as fh:
        for key, value in result.items():
            safe = str(value).replace("\n", " ")
            fh.write(f"{key}={safe}\n")


if __name__ == "__main__":
    raise SystemExit(main())
