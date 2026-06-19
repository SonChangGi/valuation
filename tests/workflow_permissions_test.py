import unittest
from pathlib import Path


class WorkflowPermissionsTest(unittest.TestCase):
    def read(self, workflow: str) -> str:
        return Path(".github/workflows", workflow).read_text(encoding="utf-8")

    def test_ci_is_read_only(self):
        ci = self.read("ci.yml")
        self.assertIn("permissions:\n  contents: read", ci)
        self.assertNotIn("contents: write", ci)
        self.assertNotIn("pull-requests: write", ci)

    def test_pages_deploy_has_only_required_write_permissions(self):
        pages = self.read("pages.yml")
        self.assertIn("contents: read", pages)
        self.assertIn("pages: write", pages)
        self.assertIn("id-token: write", pages)
        self.assertNotIn("contents: write", pages)

    def test_data_refresh_write_scope_is_explicit(self):
        refresh = self.read("data-refresh.yml")
        self.assertIn("permissions:\n  contents: write", refresh)
        self.assertIn("SEC_USER_AGENT", refresh)
        self.assertIn("npm run build", refresh)


if __name__ == "__main__":
    unittest.main()
