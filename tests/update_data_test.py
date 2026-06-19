import unittest
from unittest.mock import patch

from scripts.update_data import build_annual_rows, build_company_payload, normalize_tickers


def annual_fact(value, unit="USD", fy=2025):
    return {"units": {unit: [{"fy": fy, "fp": "FY", "form": "10-K", "filed": "2026-01-01", "end": f"{fy}-12-31", "val": value}]}}


class UpdateDataTest(unittest.TestCase):
    def test_manual_price_override_feeds_relative_multiples(self):
        annual_rows = [
            {
                "fy": 2025,
                "revenue": 1000,
                "netIncome": 100,
                "equity": 200,
                "operatingCashFlow": 90,
                "capitalExpenditures": 10,
                "freeCashFlow": 80,
                "cash": 5,
                "debtCurrent": 0,
                "debtNoncurrent": 0,
                "sharesDiluted": 10,
            }
        ]
        with (
            patch("scripts.update_data.request_json") as request_json,
            patch("scripts.update_data.fetch_market_snapshot") as fetch_market_snapshot,
            patch("scripts.update_data.build_annual_rows", return_value=(annual_rows, [])),
        ):
            request_json.side_effect = [
                {"name": "Example Inc", "exchanges": ["NASDAQ"]},
                {"entityName": "Example Inc"},
            ]
            fetch_market_snapshot.return_value = (
                {"price": 999, "currency": "USD", "asOf": "2026-01-01", "source": "test", "sourceUrl": "test", "confidence": "best-effort"},
                [],
            )

            payload = build_company_payload(
                "TEST",
                {"cik": "0000000001", "name": "Example Inc", "exchange": "NASDAQ"},
                "valuation-pages-test",
                manual_price=50,
            )

        self.assertEqual(payload["market"]["price"], 50)
        self.assertEqual(payload["market"]["confidence"], "manual")
        pe_row = next(row for row in payload["valuations"]["relative"]["rows"] if row["key"] == "pe")
        self.assertEqual(pe_row["currentMultiple"], 5)
        self.assertFalse(payload["valuations"]["relative"]["range"]["confirmed"])
        self.assertNotIn("blendedRange", payload["valuations"])

    def test_missing_capex_does_not_fallback_to_operating_cash_flow(self):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": annual_fact(1000),
                    "NetIncomeLoss": annual_fact(100),
                    "NetCashProvidedByUsedInOperatingActivities": annual_fact(90),
                    "WeightedAverageNumberOfDilutedSharesOutstanding": annual_fact(10, unit="shares"),
                }
            }
        }

        rows, warnings = build_annual_rows(companyfacts)

        self.assertEqual(rows[0]["freeCashFlowStatus"], "missing_capex_excluded")
        self.assertNotIn("freeCashFlow", rows[0])
        self.assertTrue(any("CAPEX" in warning for warning in warnings))

    def test_monetary_facts_require_usd_unit_not_usd_per_share(self):
        companyfacts = {
            "facts": {
                "us-gaap": {
                    "Revenues": annual_fact(100, unit="USD/shares"),
                    "NetIncomeLoss": annual_fact(100),
                    "NetCashProvidedByUsedInOperatingActivities": annual_fact(90),
                    "PaymentsToAcquirePropertyPlantAndEquipment": annual_fact(10),
                    "WeightedAverageNumberOfDilutedSharesOutstanding": annual_fact(10, unit="shares"),
                }
            }
        }

        rows, _warnings = build_annual_rows(companyfacts)

        self.assertNotIn("revenue", rows[0])
        self.assertNotIn("revenue", rows[0]["sourceTags"])

    def test_dcf_requires_two_recent_capex_confirmed_fcf_years(self):
        annual_rows = [
            {
                "fy": 2023,
                "revenue": 1000,
                "netIncome": 100,
                "equity": 200,
                "operatingCashFlow": 90,
                "sharesDiluted": 10,
                "freeCashFlowStatus": "missing_capex_excluded",
                "sourceTags": {},
            },
            {
                "fy": 2024,
                "revenue": 1100,
                "netIncome": 110,
                "equity": 220,
                "operatingCashFlow": 95,
                "sharesDiluted": 10,
                "freeCashFlowStatus": "missing_capex_excluded",
                "sourceTags": {},
            },
            {
                "fy": 2025,
                "revenue": 1200,
                "netIncome": 120,
                "equity": 240,
                "operatingCashFlow": 100,
                "capitalExpenditures": 20,
                "freeCashFlow": 80,
                "freeCashFlowStatus": "reported_capex",
                "sharesDiluted": 10,
                "sourceTags": {},
            },
        ]
        with (
            patch("scripts.update_data.request_json") as request_json,
            patch("scripts.update_data.fetch_market_snapshot") as fetch_market_snapshot,
            patch("scripts.update_data.build_annual_rows", return_value=(annual_rows, [])),
        ):
            request_json.side_effect = [
                {"name": "Example Inc", "exchanges": ["NASDAQ"]},
                {"entityName": "Example Inc"},
            ]
            fetch_market_snapshot.return_value = (
                {"price": 50, "currency": "USD", "asOf": "2026-01-01", "source": "test", "sourceUrl": "test", "confidence": "best-effort"},
                [],
            )

            payload = build_company_payload("TEST", {"cik": "0000000001", "name": "Example Inc", "exchange": "NASDAQ"}, "valuation-pages-test")

        self.assertIsNone(payload["assumptions"]["baseFreeCashFlow"])
        self.assertIsNone(payload["valuations"]["dcf"])
        self.assertEqual(payload["quality"]["status"], "수동 확인 필요")
        self.assertTrue(any("CAPEX가 확인된 FCF가 2개 미만" in warning for warning in payload["quality"]["warnings"]))

    def test_normalize_tickers_accepts_spaces_commas_and_deduplicates(self):
        self.assertEqual(normalize_tickers(["aapl, MSFT", "aapl BRK.B"]), ["AAPL", "MSFT", "BRK.B"])

    def test_normalize_tickers_rejects_shell_like_input(self):
        with self.assertRaises(SystemExit):
            normalize_tickers(["AAPL; rm -rf /"])


if __name__ == "__main__":
    unittest.main()
