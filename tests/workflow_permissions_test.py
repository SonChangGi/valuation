import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


NODE24_ACTIONS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v6",
    "actions/setup-node": "v6",
}

NODE20_ACTION_TAGS = {
    "actions/checkout@v4",
    "actions/setup-python@v5",
    "actions/setup-node@v4",
    "actions/configure-pages@v5",
    "actions/upload-pages-artifact@v3",
    "actions/deploy-pages@v4",
}


class WorkflowPermissionsTest(unittest.TestCase):
    def read(self, workflow: str) -> str:
        return (WORKFLOW_DIR / workflow).read_text(encoding="utf-8")

    def workflows(self):
        return sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(
            WORKFLOW_DIR.glob("*.yaml")
        )

    def test_ci_is_read_only(self):
        ci = self.read("ci.yml")
        self.assertIn("permissions:\n  contents: read", ci)
        self.assertNotIn("contents: write", ci)
        self.assertNotIn("pull-requests: write", ci)

    def test_only_ci_and_sec_smoke_workflows_exist(self):
        self.assertFalse((WORKFLOW_DIR / "data-refresh.yml").exists())
        self.assertFalse((WORKFLOW_DIR / "pages.yml").exists())
        self.assertTrue((WORKFLOW_DIR / "sec-egress-smoke.yml").exists())
        self.assertEqual(
            {"ci.yml", "sec-egress-smoke.yml"},
            {path.name for path in self.workflows()},
        )

    def test_sec_smoke_is_manual_only_and_read_only(self):
        smoke = self.read("sec-egress-smoke.yml")
        self.assertRegex(
            smoke,
            r"(?m)^on:\n  workflow_dispatch:\n\npermissions:",
        )
        for forbidden_trigger in (
            "inputs:",
            "schedule:",
            "cron:",
            "push:",
            "pull_request:",
        ):
            self.assertNotIn(forbidden_trigger, smoke)
        self.assertIn("permissions:\n  contents: read", smoke)
        self.assertIn(
            "jobs:\n  sec-egress-smoke:\n    permissions:\n      contents: read",
            smoke,
        )
        self.assertEqual(2, smoke.count("contents: read"))
        self.assertNotIn("contents: write", smoke)

    def test_workflows_contain_no_legacy_production_refresh_path(self):
        workflows = "\n".join(
            path.read_text(encoding="utf-8") for path in self.workflows()
        )
        for forbidden in (
            "schedule:",
            "cron:",
            "contents: write",
            "pages: write",
            "id-token: write",
            "scripts/update_data.py",
            "query1.finance.yahoo.com",
            "git push",
            "actions/configure-pages",
            "actions/upload-pages-artifact",
            "actions/deploy-pages",
            'cron: "15 5 * * 2-6"',
            'cron: "15 7 * * 2-6"',
        ):
            self.assertNotIn(forbidden, workflows)

    def test_workflows_use_node24_action_majors(self):
        workflows = "\n".join(
            path.read_text(encoding="utf-8") for path in self.workflows()
        )
        for action, tag in NODE24_ACTIONS.items():
            self.assertRegex(workflows, rf"{re.escape(action)}@[0-9a-f]{{40}} # {tag}")
            self.assertNotIn(f"{action}@{tag}\n", workflows)
        for action in NODE20_ACTION_TAGS:
            self.assertNotIn(action, workflows)


if __name__ == "__main__":
    unittest.main()
