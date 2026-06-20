import unittest
from pathlib import Path

from scripts.validate_data import validate_company, validate_index, validate_public_summary, validate_static_files


class DataContractTest(unittest.TestCase):
    def test_generated_data_contract(self):
        company_paths = validate_index(Path("docs/data"))
        self.assertGreaterEqual(len(company_paths), 12)
        for path in company_paths:
            validate_company(path)
        validate_public_summary(Path("docs/data"))


    def test_public_summary_exposes_dcf_coverage_degradation(self):
        import json

        summary = json.loads(Path("docs/data/summary.json").read_text(encoding="utf-8"))
        coverage = summary["coverage"]
        self.assertEqual(summary["status"]["state"], "degraded")
        self.assertEqual(coverage["dcfAvailableCount"], 17)
        self.assertEqual(coverage["missingDcfCount"], 4)
        self.assertEqual(coverage["missingDcfTickers"], ["JPM", "LLY", "NEE", "PLD"])
        self.assertEqual(coverage["dcfMethodReviewTickers"], ["JPM", "NEE", "PLD"])
        self.assertEqual(coverage["dcfInsufficientCashFlowTickers"], ["LLY"])
        self.assertAlmostEqual(coverage["dcfCoverageRatio"], 17 / 21)
        entity_by_symbol = {entity["symbol"]: entity for entity in summary["primaryEntities"]}
        self.assertEqual(entity_by_symbol["JPM"]["metrics"]["dcfStatus"], "method_review")
        self.assertEqual(entity_by_symbol["LLY"]["metrics"]["dcfStatus"], "insufficient_cash_flow")

    def test_static_assets_contract(self):
        validate_static_files(Path.cwd())


if __name__ == "__main__":
    unittest.main()
