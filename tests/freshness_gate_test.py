import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_data_freshness import decide_update


class ValuationFreshnessGateTest(unittest.TestCase):
    def write_summary(self, payload):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "summary.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(tmp.cleanup)
        return path

    def test_scheduled_retry_skips_when_summary_is_fresh_for_kst_window(self):
        path = self.write_summary({"generatedAt": "2026-06-30T05:30:00Z", "dataAsOf": "2026-06-29"})

        result = decide_update(
            event_name="schedule",
            event_schedule="15 7 * * 2-6",
            now_utc=dt.datetime(2026, 6, 30, 7, 0, tzinfo=dt.UTC),
            summary_file=path,
        )

        self.assertEqual(result["should_update"], "false")
        self.assertEqual(result["freshness_reason"], "fresh_for_kst_window_and_expected_us_session")

    def test_scheduled_retry_runs_when_data_as_of_is_stale(self):
        path = self.write_summary({"generatedAt": "2026-06-30T05:30:00Z", "dataAsOf": "2026-06-26"})

        result = decide_update(
            event_name="schedule",
            event_schedule="15 7 * * 2-6",
            now_utc=dt.datetime(2026, 6, 30, 7, 0, tzinfo=dt.UTC),
            summary_file=path,
        )

        self.assertEqual(result["should_update"], "true")
        self.assertEqual(result["freshness_reason"], "stale_or_before_kst_window")

    def test_manual_dispatch_forces_reviewed_refresh(self):
        path = self.write_summary({"generatedAt": "2026-06-30T05:30:00Z", "dataAsOf": "2026-06-29"})

        result = decide_update(
            event_name="workflow_dispatch",
            now_utc=dt.datetime(2026, 6, 30, 7, 0, tzinfo=dt.UTC),
            summary_file=path,
        )

        self.assertEqual(result["should_update"], "true")
        self.assertEqual(result["freshness_reason"], "manual_or_non_schedule_refreshes")

    def test_us_market_holiday_uses_prior_regular_session(self):
        path = self.write_summary({"generatedAt": "2026-07-06T05:30:00Z", "dataAsOf": "2026-07-02"})

        result = decide_update(
            event_name="schedule",
            event_schedule="15 5 * * 2-6",
            now_utc=dt.datetime(2026, 7, 6, 6, 0, tzinfo=dt.UTC),
            summary_file=path,
        )

        self.assertEqual(result["expected_data_as_of"], "2026-07-02")
        self.assertEqual(result["should_update"], "false")


if __name__ == "__main__":
    unittest.main()
