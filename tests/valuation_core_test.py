import math
import unittest

from scripts.valuation_core import (
    ValuationError,
    calculate_dcf,
    calculate_relative_valuation,
    derive_growth_rate,
    normalize_fcf,
)


class ValuationCoreTest(unittest.TestCase):
    def test_dcf_per_share_base_case(self):
        result = calculate_dcf(
            base_fcf=100,
            shares_outstanding=10,
            cash=20,
            debt=5,
            growth_rate=0.05,
            discount_rate=0.10,
            terminal_growth_rate=0.02,
            projection_years=3,
        )
        self.assertGreater(result["enterpriseValue"], 0)
        self.assertAlmostEqual(result["perShareValue"], result["equityValue"] / 10)
        self.assertEqual(len(result["projectedFreeCashFlows"]), 3)

    def test_dcf_rejects_discount_rate_below_terminal_growth(self):
        with self.assertRaises(ValuationError):
            calculate_dcf(base_fcf=100, shares_outstanding=10, discount_rate=0.02, terminal_growth_rate=0.03)

    def test_relative_valuation_includes_per_and_pbr(self):
        result = calculate_relative_valuation(
            price=50,
            revenue=1000,
            net_income=100,
            equity=250,
            free_cash_flow=80,
            shares_outstanding=10,
            benchmark_pe=20,
            benchmark_pb=3,
            benchmark_ps=2,
            benchmark_pfcf=15,
        )
        rows = {row["label"]: row for row in result["rows"]}
        self.assertIn("PER", rows)
        self.assertIn("PBR", rows)
        self.assertEqual(rows["PER"]["impliedValue"], 200)
        self.assertEqual(rows["PBR"]["impliedValue"], 75)
        self.assertIsNotNone(result["range"]["mid"])
        self.assertEqual(result["range"]["low"], 75)
        self.assertEqual(result["range"]["mid"], 137.5)
        self.assertEqual(result["range"]["high"], 200)

    def test_relative_headline_range_excludes_auxiliary_multiples(self):
        result = calculate_relative_valuation(
            price=50,
            revenue=10_000,
            net_income=100,
            equity=250,
            free_cash_flow=10_000,
            shares_outstanding=10,
            benchmark_pe=20,
            benchmark_pb=3,
            benchmark_ps=100,
            benchmark_pfcf=100,
        )
        self.assertEqual(result["range"]["basis"], "PER/PBR headline only")
        self.assertEqual(result["range"]["low"], 75)
        self.assertEqual(result["range"]["high"], 200)
        self.assertGreater(result["auxiliaryRange"]["mid"], result["range"]["high"])

    def test_growth_derivation_is_capped(self):
        rows = [
            {"fy": 2021, "revenue": 100, "freeCashFlow": 10},
            {"fy": 2024, "revenue": 1000, "freeCashFlow": 90},
        ]
        self.assertLessEqual(derive_growth_rate(rows), 0.12)

    def test_normalize_fcf_uses_recent_positive_median(self):
        rows = [
            {"fy": 2022, "freeCashFlow": -10},
            {"fy": 2023, "freeCashFlow": 100},
            {"fy": 2024, "freeCashFlow": 200},
            {"fy": 2025, "freeCashFlow": 300},
        ]
        self.assertEqual(normalize_fcf(rows), 200)


if __name__ == "__main__":
    unittest.main()
