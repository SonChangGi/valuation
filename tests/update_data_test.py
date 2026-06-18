import unittest
from unittest.mock import patch

from scripts.update_data import build_company_payload, normalize_tickers


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

    def test_normalize_tickers_accepts_spaces_commas_and_deduplicates(self):
        self.assertEqual(normalize_tickers(["aapl, MSFT", "aapl BRK.B"]), ["AAPL", "MSFT", "BRK.B"])

    def test_normalize_tickers_rejects_shell_like_input(self):
        with self.assertRaises(SystemExit):
            normalize_tickers(["AAPL; rm -rf /"])


if __name__ == "__main__":
    unittest.main()
