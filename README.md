# Stock Valuation Workspace

`https://sonchanggi.github.io/valuation/`에 배포하기 위한 새 정적 가치평가 웹페이지입니다. 사용자가 티커를 입력하면 캐시된 회사 JSON을 불러와 DCF 절대가치와 PER/PBR 상대가치를 함께 보여줍니다.

> 이 프로젝트는 기존 `quant-dashboard`와 다른 프로젝트의 UI/구조를 **참고만** 합니다. 다른 저장소나 기존 결과물은 수정하지 않습니다.

## 핵심 방향

- **가치평가의 주체는 사용자**입니다. 이 웹페이지는 계산 보조 도구이며 투자, 세무, 법률 또는 매매 조언이 아닙니다.
- **예측 변수는 적게 유지**합니다. DCF는 정규화 FCF, 성장률, 할인율, 영구성장률, 현금/부채, 주식수 중심입니다.
- **복잡성의 비용을 표시**합니다. 복잡한 모델은 설명력을 높일 수 있지만 오류 가능성도 키울 수 있습니다.
- **정적 GitHub Pages 우선**입니다. 브라우저는 외부 금융 API를 직접 호출하지 않고, 생성된 `docs/data/*.json`만 읽습니다.

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
python scripts/update_data.py --tickers AAPL MSFT NVDA --output docs/data --user-agent "your-app your-real-contact@example.com" --verbose
```

SEC 요청에는 식별 가능한 User-Agent가 필요합니다. 로컬/CI 모두 `SEC_USER_AGENT` 환경변수나 `--user-agent`로 실제 연락 가능한 값을 지정해야 합니다.

새 티커를 추가하려면:

```bash
python scripts/update_data.py --tickers AAPL MSFT NVDA GOOGL --output docs/data --user-agent "your-app your-real-contact@example.com" --verbose
```

`--tickers`는 공백/쉼표 구분을 모두 허용하지만 `A-Z`, 숫자, `.`, `-`만 통과시켜 워크플로 입력을 보수적으로 제한합니다.

## 로컬 실행

```bash
npm test
npm run build
npm run serve
```

그 다음 <http://localhost:8000>을 열면 됩니다.

## 검증

- `npm test` — Python 모델/데이터 계약 테스트 + Node 브라우저 모델 테스트
- `npm run build` — 오프라인 정적 데이터/HTML/JS 계약 검증
- `npm run generate-data` — 네트워크 가능한 환경에서 샘플 데이터 생성

## GitHub Pages 배포

`.github/workflows/pages.yml`는 `docs/` 디렉터리를 Pages artifact로 업로드합니다. 저장소 Pages URL은 `https://sonchanggi.github.io/valuation/` 형태가 됩니다.

데이터 갱신은 `.github/workflows/data-refresh.yml`에서 수동 실행하거나 예약 실행할 수 있습니다. 실행 전 저장소 변수 `SEC_USER_AGENT`를 설정해야 하며, 수동 실행 시 `tickers` 입력에 공백으로 구분한 티커 목록을 넣으면 해당 목록으로 `docs/data`를 다시 생성합니다.

## 방법론 요약

### DCF 절대가치

1. 최근 연간 SEC 현금흐름표에서 자유현금흐름(영업현금흐름 - CAPEX)을 계산합니다.
2. 최근 3년 양수 FCF 중앙값을 기준 FCF로 둡니다.
3. 명시 성장률, 할인율, 영구성장률을 사용자가 조정합니다.
4. 5년 예측 FCF와 터미널 가치를 현재가치로 할인합니다.
5. 현금/부채를 반영해 주당 자기자본가치를 산출합니다.

### PER/PBR 상대가치

- PER: EPS × 비교 PER
- PBR: BPS × 비교 PBR
- 웹페이지의 핵심 상대가치 범위는 PER/PBR만 사용합니다.
- P/S, P/FCF는 매출/현금흐름 관점의 보조 교차확인 지표이며 핵심 범위에 섞지 않습니다.
- 비교 배수는 기본값일 뿐이며 사용자가 산업/비교기업에 맞게 바꿔야 합니다.

## 한계

- SEC XBRL 태그는 회사마다 다를 수 있습니다.
- 시장가격 스냅샷은 best-effort이며 공식 가격 보증이 아닙니다.
- 비미국/비SEC 공시 기업은 기본 경로에서 지원되지 않을 수 있습니다.
- DCF는 입력값에 매우 민감합니다. 값이 정교해 보여도 정답을 의미하지 않습니다.
