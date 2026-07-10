import datetime as dt
import unittest

from scripts.verify_publication_freshness import assess_publication


def summary(*, generated_at="2026-07-10T05:30:00Z", dates=None):
    dates = dates or ["2026-07-09"] * 10
    return {
        "generatedAt": generated_at,
        "dataAsOf": max(dates),
        "primaryEntities": [
            {"symbol": f"T{index}", "metrics": {"priceAsOf": value}}
            for index, value in enumerate(dates)
        ],
    }


class PublicationFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 7, 10, 6, 0, tzinfo=dt.UTC)

    def test_current_market_coverage_passes_even_with_cached_fundamentals(self):
        report = assess_publication(summary(), now_utc=self.now)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["freshMarketEntityCount"], 10)

    def test_metadata_only_rebuild_with_stale_prices_fails(self):
        report = assess_publication(
            summary(dates=["2026-06-18"] * 10),
            now_utc=self.now,
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("dataAsOf" in problem for problem in report["problems"]))

    def test_single_fresh_ticker_cannot_mask_stale_universe(self):
        report = assess_publication(
            summary(dates=["2026-07-09"] + ["2026-06-18"] * 9),
            now_utc=self.now,
        )
        self.assertEqual(report["status"], "fail")
        self.assertAlmostEqual(report["freshMarketCoverageRatio"], 0.1)

    def test_stale_generation_timestamp_fails(self):
        report = assess_publication(
            summary(generated_at="2026-07-07T00:00:00Z"),
            now_utc=self.now,
        )
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("generatedAt lag" in problem for problem in report["problems"]))


if __name__ == "__main__":
    unittest.main()
