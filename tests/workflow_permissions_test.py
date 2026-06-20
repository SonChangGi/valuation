import unittest
from pathlib import Path


PINNED_NODE24_ACTIONS = {
    "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7",
    "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6",
    "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6",
    "actions/configure-pages@45bfe0192ca1faeb007ade9deae92b16b8254a0d # v6",
    "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9 # v5",
    "actions/deploy-pages@cd2ce8fcbc39b97be8ca5fce6e763baed58fa128 # v5",
}

MUTABLE_NODE20_ACTIONS = {
    "actions/checkout@v4",
    "actions/setup-python@v5",
    "actions/setup-node@v4",
    "actions/configure-pages@v5",
    "actions/upload-pages-artifact@v3",
    "actions/deploy-pages@v4",
}


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

    def test_workflows_use_pinned_node24_actions(self):
        workflows = "\n".join(path.read_text(encoding="utf-8") for path in Path(".github/workflows").glob("*.yml"))
        for action in PINNED_NODE24_ACTIONS:
            self.assertIn(action, workflows)
        for action in MUTABLE_NODE20_ACTIONS:
            self.assertNotIn(action, workflows)


if __name__ == "__main__":
    unittest.main()
