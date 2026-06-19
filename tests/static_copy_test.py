import unittest
from pathlib import Path


class StaticCopyTest(unittest.TestCase):
    def test_user_judgment_and_new_page_copy_present(self):
        html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertIn("https://sonchanggi.github.io/valuation/", html)
        self.assertIn("기존 프로젝트 결과물은 참고만 하고 수정하지 않습니다", html)
        self.assertIn("판단은 사용자에게 있습니다", html)
        self.assertIn("투자, 세무, 법률 또는 매매 조언이 아닙니다", html)
        self.assertIn("DCF와 상대가치는 평균내지 않습니다", html)
        self.assertIn("Content-Security-Policy", html)

    def test_browser_app_uses_same_origin_data_only(self):
        app = Path("docs/assets/app.js").read_text(encoding="utf-8")
        assumptions = Path("docs/assets/assumptions.js").read_text(encoding="utf-8")
        self.assertIn("fetch('data/index.json')", app)
        self.assertNotIn("data.sec.gov", app)
        self.assertNotIn("query1.finance.yahoo", app)
        self.assertNotIn("summarizeRange", app)
        self.assertIn("relativeConfirmed", app)
        self.assertIn("user-confirmed", app)
        self.assertIn("source[key] === null", assumptions)
        self.assertNotIn("baseFreeCashFlow ??", app)

    def test_static_site_does_not_publish_blended_value_copy(self):
        for path in [
            Path("docs/index.html"),
            Path("docs/assets/app.js"),
            Path("docs/assets/assumptions.js"),
            Path("docs/assets/valuation-model.js"),
            Path("docs/assets/styles.css"),
        ]:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("blendedRange", text)
            self.assertNotIn("참고 범위 중앙값", text)
            self.assertNotIn("band-track", text)


if __name__ == "__main__":
    unittest.main()
