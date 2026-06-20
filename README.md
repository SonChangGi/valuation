# Stock Valuation Workspace

`https://sonchanggi.github.io/valuation/`에 배포하기 위한 새 정적 가치평가 웹페이지입니다. 사용자가 티커를 입력하면 캐시된 회사 JSON을 불러와 DCF 절대가치와 PER/PBR 상대가치를 근거, 진단, 한계와 함께 보여줍니다.

> 이 프로젝트는 기존 `quant-dashboard`와 다른 프로젝트의 UI/구조를 **참고만** 합니다. 다른 저장소나 기존 결과물은 수정하지 않습니다.

## 핵심 방향

- **가치평가의 주체는 사용자**입니다. 이 웹페이지는 계산 보조 도구이며 투자, 세무, 법률 또는 매매 조언이 아닙니다.
- **예측 변수는 적게 유지**합니다. DCF는 정규화 FCF, 성장률, 할인율, 영구성장률, 현금/부채, 주식수 중심입니다.
- **복잡성의 비용을 표시**합니다. 복잡한 모델은 설명력을 높일 수 있지만 오류 가능성도 키울 수 있습니다.
- **정적 GitHub Pages 우선**입니다. 브라우저는 외부 금융 API를 직접 호출하지 않고, 생성된 `docs/data/*.json`만 읽습니다.
- **DCF와 상대가치는 평균내지 않습니다.** 두 방법은 서로 다른 질문에 답하므로 독립적으로 비교하고, 최종 판단은 사용자의 메모/가정 점검으로 남깁니다.
- **실제 분석 흐름을 보조**합니다. 가치 레이더, 민감도 히트맵, 현금흐름 막대 시각화, 리포트 복사, 인쇄/PDF 버튼으로 판단 기록을 남기기 쉽게 합니다.
- **문헌 기반 진단을 추가**합니다. CFA Institute, Damodaran, Fama-French, Investor.gov/SEC 참고 자료를 수식 복잡화가 아니라 터미널 가치 의존도, PER/PBR 사용 제한, ROE/마진 점검, 공시 원천 확인 기준으로 반영합니다.
- **섹터·테마 탐색을 지원**합니다. 기본 생성 목록은 기술, 커뮤니케이션, 소비재, 금융, 헬스케어, 에너지, 산업재, 유틸리티, 부동산, 소재 예시를 포함합니다.

## 페이지 구조

- `docs/index.html` — 새 GitHub Pages 웹페이지
- `docs/assets/styles.css` — 한국어 리서치 대시보드 UI
- `docs/assets/app.js` — 티커 검색, 렌더링, 가정 편집
- `docs/assets/valuation-model.js` — 브라우저/테스트 공용 가치평가 수식
- `docs/data/index.json` — 지원 티커 목록
- `docs/data/companies/*.json` — 회사별 정적 가치평가 데이터

## 데이터 생성

SEC EDGAR 공개 API를 이용해 회사 재무제표를 가져오고, 시장가격은 Yahoo chart endpoint를 best-effort 스냅샷으로만 사용합니다. 가격 계층은 SEC 재무 데이터와 신뢰도를 분리해서 표시합니다.

공식 참고:

- SEC EDGAR APIs: <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- SEC developer/fair access guidance: <https://www.sec.gov/developer>

로컬 생성:

```bash
SEC_USER_AGENT="your-app your-real-contact@example.com" npm run generate-data
# 또는
python scripts/update_data.py --output docs/data --user-agent "your-app your-real-contact@example.com" --verbose
```

SEC 요청에는 식별 가능한 User-Agent가 필요합니다. 로컬/CI 모두 `SEC_USER_AGENT` 환경변수나 `--user-agent`로 실제 연락 가능한 값을 지정해야 합니다.

새 티커를 추가하려면:

```bash
python scripts/update_data.py --tickers AAPL MSFT NVDA GOOGL JPM XOM --output docs/data --user-agent "your-app your-real-contact@example.com" --verbose
```

`--tickers`는 공백/쉼표 구분을 모두 허용하지만 `A-Z`, 숫자, `.`, `-`만 통과시켜 워크플로 입력을 보수적으로 제한합니다.

## 로컬 실행

```bash
npm test
npm run build
npm run serve
```

그 다음 <http://localhost:8000>을 열면 됩니다.

## UX / 활용 기능

- **Decision Cockpit** — 데이터 신뢰도, DCF 안전마진, 상대가치 확인 상태, 다음 행동을 한눈에 보여줍니다.
- **섹터/테마 필터** — 생성된 티커를 섹터와 테마 태그로 빠르게 좁혀 다양한 기업군을 탐색합니다.
- **가치 레이더** — 현재가와 DCF, PER/PBR 확인 가치, 민감도 상·하단을 막대 기준으로 비교합니다.
- **Reverse DCF** — 현재가가 설명되려면 필요한 명시 성장률·영구성장률을 역산해 시장가격의 전제를 읽습니다.
- **모델 진단** — DCF 터미널 가치 비중, 할인율-영구성장률 스프레드, ROE·순이익률·FCF 마진을 표시해 숫자의 취약점을 읽게 합니다.
- **DCF 현금흐름 시각화** — 예상 FCF와 현재가치를 연도별 막대로 함께 보여줘 터미널 가치 이전의 현금흐름 구조를 읽기 쉽게 합니다.
- **민감도 히트맵/취약성 요약** — 할인율×영구성장률 결과가 현재가보다 높은지, 낮은지, 근접한지 색으로 표시하고 범위가 기준값 대비 얼마나 넓은지 요약합니다.
- **상대가치 시각화** — PER/PBR 암시 주가를 현재가와 바로 비교하고, P/S·P/FCF는 보조 표로 분리합니다.
- **상대가치 품질 게이트** — EPS/BPS 산출 가능성, PER/PBR 쌍, 사용자 확인, ROE·마진 신호를 통과해야 상대가치를 핵심 판단에 씁니다.
- **리포트 복사 / 인쇄** — 현재 티커, 가정, DCF, 상대가치 상태, 데이터 경고, 사용자 메모를 복사하거나 PDF로 저장할 수 있습니다.

## 검증

- `npm test` — Python 모델/데이터 계약 테스트 + Node 브라우저 모델 테스트
- `npm run build` — 오프라인 정적 데이터/HTML/JS 계약 검증
- `npm run generate-data` — 네트워크 가능한 환경에서 샘플 데이터 생성

## GitHub Pages 배포

`.github/workflows/pages.yml`는 `docs/` 디렉터리를 Pages artifact로 업로드합니다. 저장소 Pages URL은 `https://sonchanggi.github.io/valuation/` 형태가 됩니다.

데이터 갱신은 `.github/workflows/data-refresh.yml`에서 수동 실행하거나 예약 실행할 수 있습니다. 실행 전 저장소 변수 `SEC_USER_AGENT`를 설정해야 하며, 수동 실행 시 `tickers` 입력에 공백으로 구분한 티커 목록을 넣으면 해당 목록으로 `docs/data`를 다시 생성합니다.

## 방법론 사용법과 해석

### 전체 사용 순서

1. **데이터 품질 확인** — 재무 데이터 상태, 가격 기준일, 누락 경고, 원천 태그를 먼저 확인합니다. 데이터가 약하면 모델 결과보다 공시 원문 검토가 우선입니다.
2. **DCF 가정 조정** — 기준 FCF, 성장률, 할인율, 영구성장률을 현실적인 범위로 맞춥니다. 변수 수는 적게 두되 각 변수의 경제적 근거는 명확해야 합니다.
3. **민감도 분석** — 할인율과 영구성장률 변화에 주당가치가 얼마나 흔들리는지 확인합니다. 흔들림이 크면 결과는 목표가가 아니라 가정 취약성의 지도입니다.
4. **PER/PBR 비교 배수 확인** — 기본 배수는 예시입니다. 비교기업의 산업, 성장률, 마진, ROE, 부채, 회계 품질을 확인한 뒤에만 요약 판단에 반영합니다.
5. **불일치 분석** — DCF와 상대가치가 다르면 평균내지 말고 원인을 찾습니다. 시장의 단기 이익 평가, 장기 현금흐름 가정, 장부가치의 의미를 분리해서 봅니다.
6. **사용자 판단 기록** — 모델은 계산 보조 도구입니다. 최종 결론, 반론, 추가 확인할 자료, 안전마진 요구 수준은 사용자가 메모로 남깁니다.

### DCF 절대가치

DCF는 “미래 현금흐름을 오늘 가치로 할인하면 얼마인가?”라는 질문에 답합니다.

1. 최근 연간 SEC 현금흐름표에서 자유현금흐름(영업현금흐름 - CAPEX)을 계산합니다.
2. 최근 3년 양수 FCF 중앙값을 기준 FCF로 둡니다.
3. 최근 3년 중 CAPEX가 확인된 FCF가 2개 미만이면 영업현금흐름을 대용치로 쓰지 않고 DCF를 수동 확인 대상으로 격하합니다.
4. 명시 성장률, 할인율, 영구성장률을 사용자가 조정합니다.
5. 5년 예측 FCF와 터미널 가치를 현재가치로 할인합니다.
6. 현금/부채를 반영해 주당 자기자본가치를 산출합니다.
7. 터미널 가치 비중과 할인율-영구성장률 스프레드를 진단해 단일 값의 취약성을 표시합니다.
8. 현재가를 설명하는 명시 성장률·영구성장률을 역산해 시장가격의 전제를 별도로 보여줍니다.

**어떻게 써야 하는가**

- FCF가 양수이고 반복 가능하다고 볼 수 있는 회사에 우선 적용합니다.
- 성장률은 매출 성장, 가격 결정력, 마진, 재투자 여력으로 설명할 수 있어야 합니다.
- 할인율은 사업 위험, 부채, 금리 환경, 현금흐름 안정성을 반영해야 합니다.
- 영구성장률은 장기 경제 성장률과 기업의 지속 가능한 재투자 능력을 넘지 않도록 보수적으로 둡니다.

**어떻게 해석하는가**

- DCF 주당가치는 목표가가 아니라 “내 가정이 맞다면”의 조건부 결과입니다.
- 현재가보다 DCF 가치가 높아도 가정 근거가 약하면 안전마진이 없는 결론입니다.
- 가치 대부분이 터미널 가치에 집중되면 장기 성장률과 할인율이 결론을 지배한다는 뜻입니다.
- 터미널 가치 비중이 75% 이상이면 “값이 틀렸다”가 아니라 “장기 안정성장 가정이 결론의 핵심”이라는 경고로 읽습니다.
- 민감도 표에서 주변 칸이 크게 바뀌면 단일 숫자보다 가치 범위와 취약한 가정을 읽어야 합니다.
- Reverse DCF의 내재 성장률이 보수 범위 상단을 넘으면 “가격이 틀렸다”가 아니라 “시장가격을 믿으려면 매우 강한 성장/터미널 가정에 동의해야 한다”는 뜻입니다.

### PER 상대가치

PER은 `EPS × 비교 PER`로 암시 주가를 계산합니다. “순이익 1달러를 시장이 몇 배로 평가하는가?”를 보는 방식입니다.

**어떻게 써야 하는가**

- 흑자이고 이익의 질이 안정적인 기업에 우선 사용합니다.
- 비교 PER은 같은 산업만으로 정하지 말고 성장률, 마진, 부채, 회계 품질이 비슷한 기업군에서 가져옵니다.
- PER은 EPS가 양수이고 반복 가능한 경우에만 핵심 지표로 씁니다. EPS가 음수이거나 일회성 이익이 크면 보조 신호로 낮춥니다.
- 일회성 이익, 경기순환 고점 이익, 적자 기업에는 핵심 결론으로 쓰지 않습니다.

**어떻게 해석하는가**

- 낮은 PER은 저평가 신호일 수도 있지만 이익 감소, 낮은 성장, 높은 위험의 반영일 수도 있습니다.
- 높은 PER은 과열일 수도 있지만 높은 ROIC, 긴 성장 기간, 높은 이익 가시성을 반영할 수도 있습니다.
- DCF보다 PER 가치가 높으면 시장이 단기 이익 또는 성장 옵션을 더 높게 평가하는지 확인합니다.
- 상대가치 품질 게이트가 “검토 전”이면 기본 배수 예시를 핵심 결론으로 쓰지 않습니다.

### PBR 상대가치

PBR은 `BPS × 비교 PBR`로 암시 주가를 계산합니다. “장부상 순자산 1달러를 시장이 몇 배로 평가하는가?”를 보는 방식입니다.

**어떻게 써야 하는가**

- 은행, 보험, 금융, 자본집약 업종처럼 장부가치와 수익 창출 능력의 연결이 강한 기업에 특히 유용합니다.
- 비교 PBR은 ROE와 함께 판단합니다. 같은 PBR이라도 지속 가능한 ROE가 높으면 더 비싸게 평가될 수 있습니다.
- 무형자산, 자사주, 상각, 회계 기준 차이가 큰 기업은 장부가치의 경제적 의미를 별도로 검토합니다.

**어떻게 해석하는가**

- 낮은 PBR은 청산가치 기회가 아니라 낮은 자본수익률 또는 자산 부실 위험일 수 있습니다.
- 높은 PBR은 과대평가가 아니라 높은 ROE와 자본효율성을 반영할 수 있습니다.
- PER과 PBR이 다른 방향을 가리키면 이익률과 자본효율성 중 어느 쪽이 핵심인지 분리해서 봅니다.

### P/S와 P/FCF 보조 배수

이 프로젝트의 핵심 상대가치 범위는 PER/PBR만 사용합니다. P/S와 P/FCF는 매출·현금흐름 관점의 보조 교차확인 지표이며 핵심 범위에 섞지 않습니다.

- **P/S**는 이익이 낮거나 변동성이 클 때 매출 규모를 기준으로 비교합니다. 단, 장기 마진이 낮으면 높은 P/S를 정당화하기 어렵습니다.
- **P/FCF**는 현금 창출력을 확인합니다. 단, 운전자본 변동, 경기순환, 일시적 CAPEX 축소 때문에 왜곡될 수 있습니다.
- 보조 배수가 PER/PBR과 반대 방향이면 회계 이익과 현금흐름 사이의 괴리를 분석해야 합니다.

### 방법론 참고 자료

- CFA Institute Free Cash Flow Valuation: <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation>
- CFA Institute Equity Valuation: Concepts and Basic Tools: <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/equity-valuation-concepts-basic-tools>
- CFA Institute Market-Based Valuation: <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples>
- Investor.gov EDGAR 리서치 안내: <https://www.investor.gov/introduction-investing/getting-started/researching-investments/using-edgar-research-investments>
- Damodaran terminal value 접근법: <https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/termvalapproaches.htm>
- Damodaran relative valuation chapter: <https://pages.stern.nyu.edu/~adamodar/pdfiles/valn2ed/ch17.pdf>
- Fama & French (1992), The Cross-Section of Expected Stock Returns: <https://doi.org/10.1111/j.1540-6261.1992.tb04398.x>

### 데이터 품질 안전장치

- SEC XBRL 금액 태그는 `USD`, 주식수 태그는 `shares` 단위만 사용합니다. `USD/shares` 같은 단위는 금액 원천으로 대체 사용하지 않습니다.
- 생성 JSON에는 원천 태그, 단위, 제출일, 양식, 기간 종료일을 `sourceTags`로 남겨 추적성을 확보합니다.
- 생성 단계의 상대가치 배수는 `illustrative-default`/`confirmed=false`로 기록합니다.
- 생성 JSON에는 `sector`, `sectorLabel`, `themeTags`, `methodologyReferences`, `modelPolicy`, DCF/상대가치 `diagnostics`를 포함합니다.
- 생성 JSON에는 `dcfSensitivitySummary`, `reverseDcf`, 상대가치 `qualityGate`를 포함해 단일 값보다 가정 취약성과 사용 가능성을 먼저 확인하게 합니다.
- 이 변경은 `schemaVersion: 1`의 하위 호환 additive capability이며, JSON에는 `schemaRevision: "1.1"`과 `schemaCapabilities`/`capabilities`로 새 기능을 명시합니다.
- 정적 페이지에는 Content Security Policy를 선언하고, 브라우저는 같은 출처의 캐시 JSON만 읽도록 테스트합니다.

## 한계

- SEC XBRL 태그는 회사마다 다를 수 있습니다.
- 시장가격 스냅샷은 best-effort이며 공식 가격 보증이 아닙니다.
- 비미국/비SEC 공시 기업은 기본 경로에서 지원되지 않을 수 있습니다.
- DCF는 입력값에 매우 민감합니다. 값이 정교해 보여도 정답을 의미하지 않습니다.
