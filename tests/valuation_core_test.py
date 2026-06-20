import json
import math
import unittest
from pathlib import Path

from scripts.valuation_core import (
    ValuationError,
    build_reverse_dcf,
    build_sensitivity,
    calculate_dcf,
    calculate_relative_valuation,
    derive_growth_rate,
    normalize_fcf,
    summarize_sensitivity,
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
        self.assertIn("diagnostics", result)
        self.assertGreater(result["diagnostics"]["terminalValueWeight"], 0.5)
        self.assertAlmostEqual(result["diagnostics"]["terminalSpread"], 0.08)

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
        self.assertFalse(result["range"]["confirmed"])
        self.assertEqual(result["benchmarkSource"], "illustrative-default")
        self.assertAlmostEqual(result["qualitySignals"]["roe"], 0.4)
        self.assertIn("diagnostics", result)
        self.assertEqual(result["diagnostics"]["qualityGate"]["status"], "needs_user_review")

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

    def test_relative_valuation_marks_user_confirmed_benchmarks(self):
        result = calculate_relative_valuation(
            price=50,
            revenue=1000,
            net_income=100,
            equity=250,
            free_cash_flow=80,
            shares_outstanding=10,
            benchmark_pe=20,
            benchmark_pb=3,
            benchmark_source="user-confirmed",
        )
        self.assertTrue(result["range"]["confirmed"])
        self.assertEqual(result["benchmarkSource"], "user-confirmed")

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

    def test_python_valuation_formulas_match_shared_fixture(self):
        fixtures = json.loads(Path("tests/fixtures/valuation_cases.json").read_text(encoding="utf-8"))
        dcf_inputs = fixtures["dcf"]["inputs"]
        dcf = calculate_dcf(
            base_fcf=dcf_inputs["baseFreeCashFlow"],
            shares_outstanding=dcf_inputs["sharesOutstanding"],
            cash=dcf_inputs["cash"],
            debt=dcf_inputs["debt"],
            growth_rate=dcf_inputs["growthRate"],
            discount_rate=dcf_inputs["discountRate"],
            terminal_growth_rate=dcf_inputs["terminalGrowthRate"],
            projection_years=dcf_inputs["projectionYears"],
        )
        self.assertAlmostEqual(dcf["perShareValue"], fixtures["dcf"]["expected"]["perShareValue"])
        self.assertAlmostEqual(dcf["enterpriseValue"], fixtures["dcf"]["expected"]["enterpriseValue"])
        self.assertAlmostEqual(dcf["equityValue"], fixtures["dcf"]["expected"]["equityValue"])

        relative_inputs = fixtures["relative"]["inputs"]
        relative = calculate_relative_valuation(
            price=relative_inputs["price"],
            revenue=relative_inputs["revenue"],
            net_income=relative_inputs["netIncome"],
            equity=relative_inputs["equity"],
            free_cash_flow=relative_inputs["freeCashFlow"],
            shares_outstanding=relative_inputs["sharesOutstanding"],
            benchmark_pe=relative_inputs["benchmarkPe"],
            benchmark_pb=relative_inputs["benchmarkPb"],
            benchmark_ps=relative_inputs["benchmarkPs"],
            benchmark_pfcf=relative_inputs["benchmarkPfcf"],
        )
        self.assertAlmostEqual(relative["range"]["low"], fixtures["relative"]["expected"]["range"]["low"])
        self.assertAlmostEqual(relative["range"]["mid"], fixtures["relative"]["expected"]["range"]["mid"])
        self.assertAlmostEqual(relative["range"]["high"], fixtures["relative"]["expected"]["range"]["high"])
        self.assertAlmostEqual(relative["auxiliaryRange"]["mid"], fixtures["relative"]["expected"]["auxiliaryRange"]["mid"])
        self.assertAlmostEqual(dcf["diagnostics"]["terminalValueWeight"], fixtures["dcf"]["expected"]["terminalValueWeight"])
        self.assertAlmostEqual(relative["qualitySignals"]["roe"], fixtures["relative"]["expected"]["qualitySignals"]["roe"])

    def test_reverse_dcf_solves_market_implied_growth(self):
        baseline = calculate_dcf(
            base_fcf=100,
            shares_outstanding=10,
            cash=20,
            debt=5,
            growth_rate=0.05,
            discount_rate=0.10,
            terminal_growth_rate=0.02,
            projection_years=3,
        )
        reverse = build_reverse_dcf(
            market_price=baseline["perShareValue"],
            base_fcf=100,
            shares_outstanding=10,
            cash=20,
            debt=5,
            growth_rate=0.05,
            discount_rate=0.10,
            terminal_growth_rate=0.02,
            projection_years=3,
        )
        self.assertEqual(reverse["status"], "available")
        self.assertEqual(reverse["explicitGrowth"]["status"], "solved")
        self.assertAlmostEqual(reverse["explicitGrowth"]["rate"], 0.05, places=5)
        self.assertIn("Reverse DCF", reverse["interpretation"])

    def test_sensitivity_summary_marks_fragility_and_price_coverage(self):
        baseline = calculate_dcf(
            base_fcf=100,
            shares_outstanding=10,
            cash=0,
            debt=0,
            growth_rate=0.04,
            discount_rate=0.09,
            terminal_growth_rate=0.025,
            projection_years=5,
        )
        sensitivity = build_sensitivity(100, 10, 0, 0, 0.04, 5)
        summary = summarize_sensitivity(sensitivity, base_value=baseline["perShareValue"], market_price=baseline["perShareValue"])
        self.assertIn(summary["fragility"], {"stable", "sensitive", "fragile"})
        self.assertGreater(summary["high"], summary["low"])
        self.assertEqual(summary["priceCoverage"], "mixed")
        self.assertIn("interpretation", summary)


if __name__ == "__main__":
    unittest.main()
