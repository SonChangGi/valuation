import unittest
from pathlib import Path


class StaticCopyTest(unittest.TestCase):
    def test_user_judgment_and_new_page_copy_present(self):
        html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertIn("https://sonchanggi.github.io/valuation/", html)
        self.assertIn("가치평가를 근거 있게", html)
        self.assertIn('id="ticker-filters"', html)
        self.assertIn("섹터·테마별 JSON", html)
        self.assertIn("기존 프로젝트 결과물은 참고만 하고 수정하지 않습니다", html)
        self.assertIn("판단은 사용자에게 있습니다", html)
        self.assertIn("투자, 세무, 법률 또는 매매 조언이 아닙니다", html)
        self.assertIn("DCF와 상대가치는 평균내지 않습니다", html)
        self.assertIn("Reverse DCF", html)
        self.assertIn("Fama-French", html)
        self.assertIn("터미널 가치 의존도", Path("docs/assets/app.js").read_text(encoding="utf-8"))
        self.assertIn("방법론 사용법과 해석 가이드", html)
        self.assertIn("민감도 표에서 주당가치가 크게 흔들리면", html)
        self.assertIn("PER 해석", Path("docs/assets/app.js").read_text(encoding="utf-8"))
        self.assertIn("PBR은 ROE와 함께 읽어야 합니다", html)
        self.assertIn("CFA Institute 자유현금흐름 가치평가 개요", html)
        self.assertIn("Investor.gov EDGAR 투자 리서치 안내", html)
        self.assertIn("리포트 복사", html)
        self.assertIn("인쇄/PDF", html)
        self.assertIn('id="decision-cockpit"', html)
        self.assertIn("Content-Security-Policy", html)

    def test_methodology_section_structure_is_locked(self):
        html = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="workflow-step"'), 6)
        self.assertGreaterEqual(html.count('class="methodology-card'), 8)
        for source in [
            "investor.gov/introduction-investing/getting-started/researching-investments/using-edgar-research-investments",
            "cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation",
            "cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples",
            "pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/termvalapproaches.htm",
            "doi.org/10.1111/j.1540-6261.1992.tb04398.x",
        ]:
            self.assertIn(source, html)
        self.assertGreaterEqual(html.count('target="_blank" rel="noopener noreferrer"'), 5)

    def test_browser_app_uses_same_origin_data_only(self):
        app = Path("docs/assets/app.js").read_text(encoding="utf-8")
        assumptions = Path("docs/assets/assumptions.js").read_text(encoding="utf-8")
        self.assertIn("fetch('data/index.json')", app)
        self.assertNotIn("data.sec.gov", app)
        self.assertNotIn("query1.finance.yahoo", app)
        self.assertNotIn("summarizeRange", app)
        self.assertIn("relativeConfirmed", app)
        self.assertIn("tickerMatchesFilter", app)
        self.assertIn("diagnostics", app)
        self.assertIn("user-confirmed", app)
        self.assertIn("Decision Cockpit", app)
        self.assertIn("Reverse DCF", app)
        self.assertIn("상대가치 품질 게이트", app)
        self.assertIn("DCF 현금흐름 시각화", app)
        self.assertIn("navigator.clipboard.writeText", app)
        self.assertIn("window.print()", app)
        self.assertIn("sensitivity-cell", app)
        self.assertIn('id="status-title"', app)
        self.assertIn("색 막대는 모델 가치", app)
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
