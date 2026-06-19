import {
  buildSensitivity,
  calculateDcf,
  calculateRelativeValuation,
  formatMoney,
  formatMultiple,
  formatPercent,
} from './valuation-model.js';
import { normalizeDashboardAssumptions } from './assumptions.js';

const state = {
  index: null,
  company: null,
  assumptions: null,
  currentTicker: null,
  relativeConfirmed: false,
};

const $ = (selector) => document.querySelector(selector);
const elements = {};

function bindElements() {
  Object.assign(elements, {
    tickerForm: $('#ticker-form'),
    tickerInput: $('#ticker-input'),
    tickerList: $('#ticker-list'),
    sampleTickers: $('#sample-tickers'),
    dataGenerated: $('#data-generated'),
    lookupStatus: $('#lookup-status'),
    companySection: $('#company-section'),
    dashboardGrid: $('#dashboard-grid'),
    detailGrid: $('#detail-grid'),
    judgmentSection: $('#judgment-section'),
    companyTitle: $('#company-title'),
    companyEyebrow: $('#company-eyebrow'),
    companyMeta: $('#company-meta'),
    qualityPill: $('#quality-pill'),
    marketConfidence: $('#market-confidence'),
    snapshotMetrics: $('#snapshot-metrics'),
    qualityWarnings: $('#quality-warnings'),
    valuationBand: $('#valuation-band'),
    decisionCockpit: $('#decision-cockpit'),
    valuationMetrics: $('#valuation-metrics'),
    assumptionForm: $('#assumption-form'),
    resetAssumptions: $('#reset-assumptions'),
    copyReport: $('#copy-report'),
    printReport: $('#print-report'),
    confirmRelative: $('#confirm-relative'),
    relativeReviewStatus: $('#relative-review-status'),
    dcfExplanation: $('#dcf-explanation'),
    dcfTableWrap: $('#dcf-table-wrap'),
    sensitivityWrap: $('#sensitivity-wrap'),
    relativeTableWrap: $('#relative-table-wrap'),
    memo: $('#judgment-memo'),
  });
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function calculateUpside(value, price) {
  const modelValue = finiteNumber(value);
  const marketPrice = finiteNumber(price);
  if (modelValue === null || marketPrice === null || marketPrice <= 0) return null;
  return (modelValue / marketPrice) - 1;
}

function toneForUpside(upside) {
  if (upside === null) return 'muted';
  if (upside >= 0.15) return 'positive';
  if (upside <= -0.15) return 'negative';
  return 'neutral';
}

function comparisonLabel(value, price) {
  const upside = calculateUpside(value, price);
  if (upside === null) return '비교 불가';
  if (upside >= 0.15) return `현재가 대비 ${formatPercent(upside, 1)} 높음`;
  if (upside <= -0.15) return `현재가 대비 ${formatPercent(Math.abs(upside), 1)} 낮음`;
  return `현재가와 근접 (${formatPercent(upside, 1)})`;
}

function scaledPercent(value, maxValue) {
  const number = finiteNumber(value);
  const max = finiteNumber(maxValue);
  if (number === null || max === null || max <= 0) return 0;
  return Math.max(4, Math.min(100, (Math.abs(number) / max) * 100));
}

function classForQuality(status) {
  if (status === '충분') return 'secondary';
  if (status === '일부 누락') return 'warning';
  return 'danger';
}

function setStatus(title, copy, tone = '') {
  elements.lookupStatus.className = `lookup-status ${tone}`.trim();
  elements.lookupStatus.innerHTML = `<h2 id="status-title">${escapeHtml(title)}</h2><p>${escapeHtml(copy)}</p>`;
}

function showDashboard(show) {
  [elements.companySection, elements.dashboardGrid, elements.detailGrid, elements.judgmentSection].forEach((node) => {
    node.classList.toggle('hidden', !show);
  });
}

async function loadIndex() {
  const response = await fetch('data/index.json');
  if (!response.ok) throw new Error(`index.json 로드 실패: ${response.status}`);
  state.index = await response.json();
  renderIndexControls();
  const first = state.index.tickers?.[0]?.ticker;
  if (first) {
    await loadTicker(first);
  } else {
    setStatus('생성된 티커가 없습니다', 'scripts/update_data.py를 실행해 docs/data JSON을 먼저 생성하세요.', 'error');
  }
}

function renderIndexControls() {
  const tickers = state.index?.tickers || [];
  elements.dataGenerated.textContent = `생성 시각 ${state.index.generatedAt || 'N/A'} · ${tickers.length}개 티커`;
  elements.tickerList.replaceChildren(...tickers.map((item) => {
    const option = document.createElement('option');
    option.value = item.ticker;
    option.label = item.name || item.ticker;
    return option;
  }));
  elements.sampleTickers.replaceChildren(...tickers.slice(0, 8).map((item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = item.ticker;
    button.addEventListener('click', () => loadTicker(item.ticker));
    return button;
  }));
}

function findIndexItem(ticker) {
  const normalized = ticker.trim().toUpperCase();
  return (state.index?.tickers || []).find((item) => item.ticker === normalized);
}

async function loadTicker(ticker) {
  const normalized = ticker.trim().toUpperCase();
  if (!normalized) return;
  const item = findIndexItem(normalized);
  if (!item) {
    showDashboard(false);
    setStatus(
      `${normalized}는 현재 캐시되지 않았습니다`,
      '이 페이지는 새 웹페이지 /valuation/의 정적 JSON만 읽습니다. 새 티커는 scripts/update_data.py --tickers ' + normalized + ' --output docs/data 또는 GitHub Actions 수동 실행으로 생성하세요.',
      'error',
    );
    elements.tickerInput.value = normalized;
    return;
  }
  setStatus(`${normalized} 데이터를 여는 중`, '같은 출처의 캐시 JSON을 불러오고 있습니다.');
  const response = await fetch(`data/${item.companyFile}`);
  if (!response.ok) throw new Error(`${item.companyFile} 로드 실패: ${response.status}`);
  state.company = await response.json();
  state.currentTicker = normalized;
  state.assumptions = normalizeAssumptions(state.company.assumptions || {});
  state.relativeConfirmed = false;
  elements.tickerInput.value = normalized;
  restoreMemo(normalized);
  hydrateAssumptionInputs();
  renderCompany();
  recalculateAndRender();
  showDashboard(true);
  setStatus(`${normalized} 가치평가를 표시 중`, '가정을 조정하면 DCF와 상대가치가 즉시 다시 계산됩니다.');
}

function normalizeAssumptions(assumptions) {
  return normalizeDashboardAssumptions(assumptions, state.company?.financials?.latest || {});
}

function hydrateAssumptionInputs() {
  const a = state.assumptions;
  $('#growth-rate').value = String(a.growthRate * 100);
  $('#discount-rate').value = String(a.discountRate * 100);
  $('#terminal-growth-rate').value = String(a.terminalGrowthRate * 100);
  $('#benchmark-pe').value = String(a.benchmarkPe);
  $('#benchmark-pb').value = String(a.benchmarkPb);
  $('#benchmark-ps').value = String(a.benchmarkPs);
  $('#benchmark-pfcf').value = String(a.benchmarkPfcf);
  updateAssumptionOutputs();
  updateRelativeReviewStatus();
}

function readAssumptionsFromInputs() {
  state.assumptions = {
    ...state.assumptions,
    growthRate: Number($('#growth-rate').value) / 100,
    discountRate: Number($('#discount-rate').value) / 100,
    terminalGrowthRate: Number($('#terminal-growth-rate').value) / 100,
    benchmarkPe: Number($('#benchmark-pe').value),
    benchmarkPb: Number($('#benchmark-pb').value),
    benchmarkPs: Number($('#benchmark-ps').value),
    benchmarkPfcf: Number($('#benchmark-pfcf').value),
  };
  updateAssumptionOutputs();
}

function updateAssumptionOutputs() {
  $('#growth-output').textContent = formatPercent(Number($('#growth-rate').value) / 100, 2);
  $('#discount-output').textContent = formatPercent(Number($('#discount-rate').value) / 100, 2);
  $('#terminal-output').textContent = formatPercent(Number($('#terminal-growth-rate').value) / 100, 2);
}

function updateRelativeReviewStatus() {
  elements.relativeReviewStatus.textContent = state.relativeConfirmed
    ? '사용자가 PER/PBR 비교 배수를 검토했습니다. 상대가치 참고값을 요약에 표시합니다.'
    : '기본 PER/PBR 배수는 예시값입니다. 산업·비교기업 현실성을 확인한 뒤 적용하세요.';
  elements.relativeReviewStatus.classList.toggle('confirmed', state.relativeConfirmed);
}

function renderCompany() {
  const { company, market, quality, financials } = state.company;
  const latest = financials.latest || {};
  elements.companyEyebrow.textContent = `${company.ticker} · ${company.exchange || 'Exchange N/A'}`;
  elements.companyTitle.textContent = company.name || company.ticker;
  elements.companyMeta.textContent = [company.sicDescription, company.entityType, `CIK ${company.cik}`].filter(Boolean).join(' · ');
  elements.qualityPill.textContent = `재무 데이터: ${quality.status}`;
  elements.qualityPill.className = `status-pill ${classForQuality(quality.status)}`;
  elements.marketConfidence.textContent = `가격: ${market.confidence || 'unknown'}`;
  elements.marketConfidence.className = `status-pill ${market.confidence === 'missing' ? 'warning' : 'secondary'}`;
  elements.snapshotMetrics.innerHTML = [
    metricCard('현재가', formatMoney(market.price, company.currency, { compact: false }), market.asOf ? `가격 기준일 ${market.asOf}` : '가격 기준일 N/A'),
    metricCard('최근 매출', formatMoney(latest.revenue, financials.currency), `FY ${latest.fy || 'N/A'}`),
    metricCard('최근 순이익', formatMoney(latest.netIncome, financials.currency), 'SEC annual fact'),
    metricCard('정규화 FCF', formatMoney(state.assumptions.baseFreeCashFlow, financials.currency), '최근 3년 양수 FCF 중앙값'),
    metricCard('현금 - 부채', formatMoney((state.assumptions.cash || 0) - (state.assumptions.debt || 0), financials.currency), 'DCF 자기자본 조정'),
  ].join('');
  const warnings = quality.warnings || [];
  elements.qualityWarnings.innerHTML = warnings.length
    ? warnings.map((warning) => `<p>${escapeHtml(warning)}</p>`).join('')
    : '<p>핵심 재무제표 태그가 현재 모델 산출에 충분합니다. 그래도 원문 공시와 일회성 요인은 직접 확인하세요.</p>';
}

function metricCard(label, value, detail = '') {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ''}</article>`;
}

function calculateCurrentValuations() {
  const latest = state.company.financials.latest || {};
  const market = state.company.market || {};
  let dcf = null;
  let dcfError = null;
  try {
    dcf = calculateDcf(state.assumptions);
  } catch (error) {
    dcfError = error.message;
  }
  let relative = null;
  let relativeError = null;
  try {
    relative = calculateRelativeValuation({
      price: market.price,
      revenue: latest.revenue,
      netIncome: latest.netIncome,
      equity: latest.equity,
      freeCashFlow: latest.freeCashFlow,
      sharesOutstanding: state.assumptions.sharesOutstanding,
      benchmarkPe: state.assumptions.benchmarkPe,
      benchmarkPb: state.assumptions.benchmarkPb,
      benchmarkPs: state.assumptions.benchmarkPs,
      benchmarkPfcf: state.assumptions.benchmarkPfcf,
      benchmarkSource: state.relativeConfirmed ? 'user-confirmed' : 'illustrative-default',
    });
  } catch (error) {
    relativeError = error.message;
    relative = null;
  }
  return { dcf, dcfError, relative, relativeError };
}

function recalculateAndRender() {
  if (!state.company || !state.assumptions) return;
  readAssumptionsFromInputs();
  const { dcf, dcfError, relative, relativeError } = calculateCurrentValuations();
  renderValuationSummary(dcf, relative, dcfError);
  renderDcf(dcf, dcfError);
  renderRelative(relative, relativeError);
  updateRelativeReviewStatus();
}

function renderValuationSummary(dcf, relative, dcfError) {
  const currency = state.company.company.currency || 'USD';
  const price = state.company.market.price;
  elements.valuationBand.innerHTML = renderMethodComparison(dcf, relative, price, currency);
  elements.decisionCockpit.innerHTML = renderDecisionCockpit(dcf, dcfError, price, currency);
  const dcfUpside = price && dcf?.perShareValue ? (dcf.perShareValue / price) - 1 : null;
  const relativeUpside = price && state.relativeConfirmed && relative?.range?.mid ? (relative.range.mid / price) - 1 : null;
  elements.valuationMetrics.innerHTML = [
    metricCard('현재가', formatMoney(price, currency, { compact: false }), '시장가격은 best-effort 스냅샷'),
    metricCard('DCF 주당가치', dcf ? formatMoney(dcf.perShareValue, currency, { compact: false }) : 'N/A', dcfError || 'FCF 기반 절대가치'),
    metricCard('DCF 현재가 대비', dcfUpside === null ? 'N/A' : formatPercent(dcfUpside, 1), '매수/매도 신호가 아닌 DCF 가정 차이'),
    metricCard('상대가치 상태', state.relativeConfirmed && relative?.range?.mid ? formatMoney(relative.range.mid, currency, { compact: false }) : '검토 전', 'PER/PBR은 사용자 확인 뒤 요약 반영'),
    metricCard('상대가치 현재가 대비', relativeUpside === null ? 'N/A' : formatPercent(relativeUpside, 1), '확인된 비교 배수일 때만 표시'),
  ].join('');
}

function renderValuationScale(label, value, price, currency, note = '') {
  const valueNumber = finiteNumber(value);
  const priceNumber = finiteNumber(price);
  const upside = calculateUpside(valueNumber, priceNumber);
  const tone = toneForUpside(upside);
  if (valueNumber === null || priceNumber === null || priceNumber <= 0) {
    return `
      <div class="valuation-scale muted">
        <div class="scale-labels"><span>${escapeHtml(label)}</span><strong>비교 불가</strong></div>
        <small>${escapeHtml(note || '가격 또는 가치 데이터가 부족합니다.')}</small>
      </div>`;
  }
  const maxValue = Math.max(valueNumber, priceNumber);
  const valueWidth = scaledPercent(valueNumber, maxValue);
  const currentLeft = scaledPercent(priceNumber, maxValue);
  return `
    <div class="valuation-scale ${tone}">
      <div class="scale-labels">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(formatMoney(valueNumber, currency, { compact: false }))}</strong>
      </div>
      <div class="scale-track" aria-hidden="true">
        <span class="scale-fill" style="width: ${valueWidth}%"></span>
        <span class="scale-marker" style="left: ${currentLeft}%"></span>
      </div>
      <div class="scale-foot">
        <span>현재가 ${escapeHtml(formatMoney(priceNumber, currency, { compact: false }))}</span>
        <span>${escapeHtml(comparisonLabel(valueNumber, priceNumber))}</span>
      </div>
      ${note ? `<small>${escapeHtml(note)}</small>` : ''}
    </div>`;
}

function renderDecisionCockpit(dcf, dcfError, price, currency) {
  const quality = state.company.quality || {};
  const warnings = quality.warnings || [];
  const dcfUpside = calculateUpside(dcf?.perShareValue, price);
  const relativeValue = state.relativeConfirmed ? relative?.range?.mid : null;
  const relativeUpside = calculateUpside(relativeValue, price);
  const sensitivityValues = buildSensitivity(state.assumptions)
    .flatMap((row) => row.values.map((cell) => finiteNumber(cell.perShareValue)))
    .filter((value) => value !== null);
  const sensitivityLow = sensitivityValues.length ? Math.min(...sensitivityValues) : null;
  const sensitivityHigh = sensitivityValues.length ? Math.max(...sensitivityValues) : null;
  const memoReady = Boolean(elements.memo?.value?.trim());
  const nextAction = nextActionText({ dcf, dcfError, warnings, memoReady, dcfUpside, relativeUpside });
  return `
    <div class="cockpit-header">
      <div>
        <p class="eyebrow">Decision Cockpit</p>
        <h3>가치 레이더와 다음 행동</h3>
      </div>
      <span class="status-pill ${warnings.length ? 'warning' : 'secondary'}">${warnings.length ? '공시 확인 필요' : '기본 데이터 통과'}</span>
    </div>
    <p class="scale-legend">색 막대는 모델 가치, 검은 선은 현재가입니다. 색상은 현재가 대비 차이를 빠르게 읽기 위한 보조 신호입니다.</p>
    <div class="cockpit-grid">
      <article class="cockpit-card ${warnings.length ? 'warning' : 'positive'}">
        <span>데이터 신뢰도</span>
        <strong>${escapeHtml(quality.status || 'N/A')}</strong>
        <small>${warnings.length ? `${warnings.length}개 경고를 먼저 확인` : '핵심 태그 기준 통과'}</small>
      </article>
      <article class="cockpit-card ${toneForUpside(dcfUpside)}">
        <span>DCF 안전마진 렌즈</span>
        <strong>${dcfUpside === null ? 'N/A' : escapeHtml(formatPercent(dcfUpside, 1))}</strong>
        <small>${escapeHtml(dcfError || comparisonLabel(dcf?.perShareValue, price))}</small>
      </article>
      <article class="cockpit-card ${state.relativeConfirmed ? toneForUpside(relativeUpside) : 'warning'}">
        <span>상대가치 활용 상태</span>
        <strong>${state.relativeConfirmed ? escapeHtml(formatPercent(relativeUpside, 1)) : '검토 전'}</strong>
        <small>${state.relativeConfirmed ? escapeHtml(comparisonLabel(relativeValue, price)) : 'PER/PBR 비교군 검토 후 반영'}</small>
      </article>
      <article class="cockpit-card action">
        <span>다음 행동</span>
        <strong>${escapeHtml(nextAction.title)}</strong>
        <small>${escapeHtml(nextAction.detail)}</small>
      </article>
    </div>
    <div class="radar-grid">
      ${renderValuationScale('DCF 기준 가치', dcf?.perShareValue, price, currency, '현금흐름 가정 기반')}
      ${renderValuationScale('PER/PBR 확인 가치', relativeValue, price, currency, state.relativeConfirmed ? '사용자 확인 배수 기반' : '검토 완료 전에는 참고값 숨김')}
      ${renderValuationScale('민감도 하단', sensitivityLow, price, currency, '할인율×영구성장률 보수 구간')}
      ${renderValuationScale('민감도 상단', sensitivityHigh, price, currency, '낙관 구간도 가정 근거 필요')}
    </div>`;
}

function nextActionText({ dcf, dcfError, warnings, memoReady, dcfUpside, relativeUpside }) {
  if (warnings.length) {
    return { title: '데이터 원문 확인', detail: 'SEC 태그·회계기간·가격 기준일을 먼저 점검하세요.' };
  }
  if (!dcf || dcfError) {
    return { title: 'DCF 조건 보강', detail: 'FCF, 주식수, 할인율/영구성장률 조건을 확인하세요.' };
  }
  if (!state.relativeConfirmed) {
    return { title: '비교 배수 검토', detail: '산업·성장률·ROE가 비슷한 PER/PBR 기준을 확인하세요.' };
  }
  if (dcfUpside !== null && relativeUpside !== null && Math.abs(dcfUpside - relativeUpside) > 0.35) {
    return { title: '불일치 원인 분석', detail: '현금흐름 가정과 시장 배수가 왜 다른 방향인지 분해하세요.' };
  }
  if (!memoReady) {
    return { title: '판단 메모 작성', detail: '가정, 반론, 안전마진 요구 수준을 기록하세요.' };
  }
  return { title: '안전마진 재점검', detail: '낙관·기준·비관 가정에서도 결론이 유지되는지 확인하세요.' };
}

function renderMethodComparison(dcf, relative, price, currency) {
  const relativeValue = state.relativeConfirmed ? relative?.range?.mid : null;
  const dcfTone = toneForUpside(calculateUpside(dcf?.perShareValue, price));
  const relativeTone = state.relativeConfirmed ? toneForUpside(calculateUpside(relativeValue, price)) : 'warning';
  return `
    <div class="method-compare" aria-label="DCF와 상대가치 독립 비교">
      <article class="method-card ${dcfTone}">
        <span>DCF 독립 결과</span>
        <strong>${escapeHtml(dcf ? formatMoney(dcf.perShareValue, currency, { compact: false }) : 'N/A')}</strong>
        <small>정규화 FCF와 사용자가 조정한 성장률·할인율 기준입니다.</small>
        ${renderValuationScale('DCF vs 현재가', dcf?.perShareValue, price, currency)}
      </article>
      <article class="method-card ${relativeTone}">
        <span>PER/PBR 상대가치</span>
        <strong>${escapeHtml(relativeValue ? formatMoney(relativeValue, currency, { compact: false }) : '사용자 검토 전')}</strong>
        <small>기본 배수는 예시값입니다. 비교기업/산업 현실성을 확인해야 요약값으로 사용합니다.</small>
        ${renderValuationScale('상대가치 vs 현재가', relativeValue, price, currency)}
      </article>
      <article class="method-card">
        <span>현재가</span>
        <strong>${escapeHtml(formatMoney(price, currency, { compact: false }))}</strong>
        <small>두 방법은 평균내지 않고 독립적으로 비교합니다.</small>
      </article>
    </div>`;
}

function renderDcf(dcf, error) {
  const currency = state.company.company.currency || 'USD';
  elements.dcfExplanation.innerHTML = error
    ? `<strong>DCF 계산 제한:</strong> ${escapeHtml(error)} <br />FCF·주식수·할인율 조건이 충족되지 않으면 절대가치는 계산하지 않고 원문 공시 확인 대상으로 남깁니다.`
    : `<strong>사용법:</strong> 최근 정규화 FCF ${escapeHtml(formatMoney(state.assumptions.baseFreeCashFlow, currency))}를 출발점으로 성장률 ${escapeHtml(formatPercent(state.assumptions.growthRate, 2))}, 할인율 ${escapeHtml(formatPercent(state.assumptions.discountRate, 2))}, 영구성장률 ${escapeHtml(formatPercent(state.assumptions.terminalGrowthRate, 2))}을 적용했습니다.
      <ul>
        <li><strong>분석:</strong> 성장률은 매출 성장·마진·재투자 여력으로 설명하고, 할인율은 사업 위험과 금리 환경을 반영하는지 점검하세요.</li>
        <li><strong>해석:</strong> 주당가치는 목표가가 아니라 “내 현금흐름 가정이 맞다면”의 결과입니다. 현재가와 차이가 클수록 가정 근거와 안전마진을 더 엄격하게 봅니다.</li>
        <li><strong>주의:</strong> 민감도 표에서 주변 칸이 크게 흔들리면 결론은 숫자 하나가 아니라 가능한 가치 범위와 취약한 가정입니다.</li>
      </ul>`;
  if (!dcf) {
    elements.dcfTableWrap.innerHTML = '';
    elements.sensitivityWrap.innerHTML = '';
    return;
  }
  const forecastMax = Math.max(
    ...dcf.projectedFreeCashFlows.flatMap((row) => [Math.abs(row.freeCashFlow), Math.abs(row.presentValue)]),
    1,
  );
  elements.dcfTableWrap.innerHTML = `
    <div class="forecast-chart" aria-label="DCF 현금흐름 시각화">
      <h3>DCF 현금흐름 시각화</h3>
      ${dcf.projectedFreeCashFlows.map((row) => `
        <div class="forecast-row">
          <span>Y${row.year}</span>
          <div class="forecast-bars">
            <div class="forecast-bar fcf" style="width: ${scaledPercent(row.freeCashFlow, forecastMax)}%"><strong>${formatMoney(row.freeCashFlow, currency)}</strong></div>
            <div class="forecast-bar pv" style="width: ${scaledPercent(row.presentValue, forecastMax)}%"><strong>${formatMoney(row.presentValue, currency)}</strong></div>
          </div>
        </div>`).join('')}
      <div class="chart-legend"><span class="fcf-dot">예상 FCF</span><span class="pv-dot">현재가치</span></div>
    </div>
    <table>
      <caption>DCF 자유현금흐름 예측</caption>
      <thead><tr><th>연도</th><th>예상 FCF</th><th>현재가치</th></tr></thead>
      <tbody>${dcf.projectedFreeCashFlows.map((row) => `<tr><td>${row.year}</td><td>${formatMoney(row.freeCashFlow, currency)}</td><td>${formatMoney(row.presentValue, currency)}</td></tr>`).join('')}</tbody>
    </table>`;
  const sensitivity = buildSensitivity(state.assumptions);
  const price = state.company.market.price;
  elements.sensitivityWrap.innerHTML = `
    <h3>할인율 × 영구성장률 민감도</h3>
    <div class="table-wrap">
      <table>
        <caption>DCF 민감도 매트릭스</caption>
        <thead><tr><th>할인율</th>${sensitivity[0].values.map((cell) => `<th>${formatPercent(cell.terminalGrowthRate, 1)}</th>`).join('')}</tr></thead>
        <tbody>${sensitivity.map((row) => `<tr><th scope="row">${formatPercent(row.discountRate, 1)}</th>${row.values.map((cell) => {
    const upside = calculateUpside(cell.perShareValue, price);
    return `<td class="sensitivity-cell ${toneForUpside(upside)}"><strong>${formatMoney(cell.perShareValue, currency, { compact: false })}</strong><small>${comparisonLabel(cell.perShareValue, price)}</small></td>`;
  }).join('')}</tr>`).join('')}</tbody>
      </table>
    </div>`;
}

function renderRelative(relative, error) {
  const currency = state.company.company.currency || 'USD';
  if (!relative) {
    elements.relativeTableWrap.innerHTML = `<div class="explain-box">상대가치 계산 제한: ${escapeHtml(error || '상대가치를 산출할 데이터가 부족합니다.')}</div>`;
    return;
  }
  const coreRows = relative.rows.filter((row) => row.key === 'pe' || row.key === 'pb');
  const auxiliaryRows = relative.rows.filter((row) => row.key !== 'pe' && row.key !== 'pb');
  const price = state.company.market.price;
  const rowHtml = (row) => `
    <tr>
      <th scope="row">${escapeHtml(row.label)}</th>
      <td>${formatMoney(row.baseMetric, currency, { compact: false })}</td>
      <td>${formatMultiple(row.currentMultiple)}</td>
      <td>${formatMultiple(row.benchmarkMultiple)}</td>
      <td class="value-cell ${toneForUpside(calculateUpside(row.impliedValue, price))}"><strong>${formatMoney(row.impliedValue, currency, { compact: false })}</strong><small>${comparisonLabel(row.impliedValue, price)}</small></td>
      <td>${escapeHtml(row.description)}</td>
    </tr>`;
  elements.relativeTableWrap.innerHTML = `
    <div class="explain-box">
      ${state.relativeConfirmed
        ? 'PER/PBR 배수가 사용자 확인 상태입니다. 그래도 비교기업·산업·ROE 차이는 직접 검토해야 합니다.'
        : '아래 PER/PBR 값은 기본 예시 배수로 계산한 출발점입니다. 사용자 확인 전에는 요약 가치로 취급하지 않습니다.'}
      <ul>
        <li><strong>PER 해석:</strong> 이익의 질과 성장 지속성이 비슷한 기업끼리 비교할 때 의미가 커집니다. 낮은 PER은 저평가뿐 아니라 이익 감소 위험일 수 있습니다.</li>
        <li><strong>PBR 해석:</strong> 장부가치가 경제적 자산가치를 잘 반영하고 ROE가 지속 가능한지 함께 봐야 합니다. 낮은 PBR은 낮은 자본수익률 신호일 수 있습니다.</li>
        <li><strong>보조 배수:</strong> P/S와 P/FCF가 PER/PBR과 반대로 움직이면 매출 마진, 운전자본, CAPEX, 일회성 이익의 괴리를 분석하세요.</li>
      </ul>
    </div>
    <div class="relative-visual-grid" aria-label="상대가치 시각화">
      ${coreRows.map((row) => renderValuationScale(`${row.label} 암시 주가`, row.impliedValue, price, currency, row.description)).join('')}
    </div>
    <table>
      <caption>PER/PBR 핵심 상대가치 산출표</caption>
      <thead><tr><th>지표</th><th>1주당 기준값</th><th>현재 배수</th><th>비교 배수</th><th>암시 주가</th><th>해석</th></tr></thead>
      <tbody>${coreRows.map(rowHtml).join('')}</tbody>
    </table>
    <div class="auxiliary-relative">
      <h3>보조 교차확인: P/S · P/FCF</h3>
      <p>P/S와 P/FCF는 핵심 상대가치 범위에 섞지 않고, 매출/현금흐름 관점의 보조 신호로만 확인합니다.</p>
      <table>
        <caption>보조 상대가치 산출표</caption>
        <thead><tr><th>지표</th><th>1주당 기준값</th><th>현재 배수</th><th>비교 배수</th><th>암시 주가</th><th>해석</th></tr></thead>
        <tbody>${auxiliaryRows.map(rowHtml).join('')}</tbody>
      </table>
    </div>`;
}

function restoreMemo(ticker) {
  const key = `valuation:memo:${ticker}`;
  elements.memo.value = localStorage.getItem(key) || '';
}

function buildReportSummary() {
  readAssumptionsFromInputs();
  const { dcf, dcfError, relative, relativeError } = calculateCurrentValuations();
  const { company, market, quality } = state.company;
  const currency = company.currency || 'USD';
  const relativeValue = state.relativeConfirmed ? relative?.range?.mid : null;
  const warnings = quality.warnings?.length ? quality.warnings.join(' / ') : '핵심 경고 없음';
  return [
    `Stock Valuation Workspace - ${company.ticker} ${company.name || ''}`.trim(),
    `생성 시각: ${new Date().toISOString()}`,
    `현재가: ${formatMoney(market.price, currency, { compact: false })} (${market.asOf || '가격일 N/A'})`,
    `DCF 주당가치: ${dcf ? formatMoney(dcf.perShareValue, currency, { compact: false }) : `N/A - ${dcfError}`}`,
    `DCF 현재가 대비: ${dcf ? comparisonLabel(dcf.perShareValue, market.price) : '비교 불가'}`,
    `PER/PBR 상대가치: ${relativeValue ? formatMoney(relativeValue, currency, { compact: false }) : `검토 전${relativeError ? ` - ${relativeError}` : ''}`}`,
    `상대가치 상태: ${state.relativeConfirmed ? '사용자 검토 완료' : '기본 배수 예시값 - 검토 필요'}`,
    `가정: 성장률 ${formatPercent(state.assumptions.growthRate, 2)}, 할인율 ${formatPercent(state.assumptions.discountRate, 2)}, 영구성장률 ${formatPercent(state.assumptions.terminalGrowthRate, 2)}, PER ${formatMultiple(state.assumptions.benchmarkPe)}, PBR ${formatMultiple(state.assumptions.benchmarkPb)}`,
    `데이터 품질: ${quality.status || 'N/A'} / ${warnings}`,
    `사용자 메모: ${elements.memo?.value?.trim() || '없음'}`,
    '주의: 이 요약은 투자, 세무, 법률 또는 매매 조언이 아니라 사용자의 판단을 돕는 계산 기록입니다.',
  ].join('\n');
}

async function copyReportSummary() {
  const summary = buildReportSummary();
  await navigator.clipboard.writeText(summary);
  setStatus(`${state.currentTicker} 리포트를 복사했습니다`, '가정, DCF, 상대가치 상태, 데이터 경고, 메모가 클립보드에 저장되었습니다.', 'success');
}

function bindEvents() {
  elements.tickerForm.addEventListener('submit', (event) => {
    event.preventDefault();
    loadTicker(elements.tickerInput.value).catch((error) => setStatus('티커 로드 실패', error.message, 'error'));
  });
  elements.assumptionForm.addEventListener('input', (event) => {
    if (event.target?.id?.startsWith('benchmark-')) {
      state.relativeConfirmed = false;
    }
    try {
      recalculateAndRender();
    } catch (error) {
      setStatus('가정 확인 필요', error.message, 'error');
    }
  });
  elements.resetAssumptions.addEventListener('click', () => {
    state.assumptions = normalizeAssumptions(state.company.assumptions || {});
    state.relativeConfirmed = false;
    hydrateAssumptionInputs();
    recalculateAndRender();
  });
  elements.confirmRelative.addEventListener('click', () => {
    state.relativeConfirmed = true;
    recalculateAndRender();
  });
  elements.copyReport.addEventListener('click', () => {
    copyReportSummary().catch((error) => setStatus('리포트 복사 실패', `브라우저 클립보드 권한을 확인하세요: ${error.message}`, 'error'));
  });
  elements.printReport.addEventListener('click', () => {
    window.print();
  });
  elements.memo.addEventListener('input', () => {
    if (!state.currentTicker) return;
    localStorage.setItem(`valuation:memo:${state.currentTicker}`, elements.memo.value);
    recalculateAndRender();
  });
}

bindElements();
bindEvents();
loadIndex().catch((error) => {
  showDashboard(false);
  setStatus('데이터 인덱스를 불러오지 못했습니다', error.message, 'error');
});
