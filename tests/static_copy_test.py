import unittest
from pathlib import Path


class StaticCopyTest(unittest.TestCase):
    def test_user_judgment_and_new_page_copy_present(self):
        html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertIn("https://sonchanggi.github.io/valuation/", html)
        self.assertIn("기존 프로젝트 결과물은 참고만 하고 수정하지 않습니다", html)
        self.assertIn("판단은 사용자에게 있습니다", html)
        self.assertIn("투자, 세무, 법률 또는 매매 조언이 아닙니다", html)

    def test_browser_app_uses_same_origin_data_only(self):
        app = Path("docs/assets/app.js").read_text(encoding="utf-8")
        self.assertIn("fetch('data/index.json')", app)
        self.assertNotIn("data.sec.gov", app)
        self.assertNotIn("query1.finance.yahoo", app)


if __name__ == "__main__":
    unittest.main()
