import unittest
from pathlib import Path

from scripts.validate_data import validate_company, validate_index, validate_static_files


class DataContractTest(unittest.TestCase):
    def test_generated_data_contract(self):
        company_paths = validate_index(Path("docs/data"))
        self.assertGreaterEqual(len(company_paths), 12)
        for path in company_paths:
            validate_company(path)

    def test_static_assets_contract(self):
        validate_static_files(Path.cwd())


if __name__ == "__main__":
    unittest.main()
