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
    valuationMetrics: $('#valuation-metrics'),
    assumptionForm: $('#assumption-form'),
    resetAssumptions: $('#reset-assumptions'),
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

function classForQuality(status) {
  if (status === '충분') return 'secondary';
  if (status === '일부 누락') return 'warning';
  return 'danger';
}

function setStatus(title, copy, tone = '') {
  elements.lookupStatus.className = `lookup-status ${tone}`.trim();
  elements.lookupStatus.innerHTML = `<h2>${escapeHtml(title)}</h2><p>${escapeHtml(copy)}</p>`;
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
  hydrateAssumptionInputs();
  renderCompany();
  recalculateAndRender();
  showDashboard(true);
  setStatus(`${normalized} 가치평가를 표시 중`, '가정을 조정하면 DCF와 상대가치가 즉시 다시 계산됩니다.');
  restoreMemo(normalized);
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

function recalculateAndRender() {
  if (!state.company || !state.assumptions) return;
  readAssumptionsFromInputs();
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
  renderValuationSummary(dcf, relative, dcfError);
  renderDcf(dcf, dcfError);
  renderRelative(relative, relativeError);
  updateRelativeReviewStatus();
}

function renderValuationSummary(dcf, relative, dcfError) {
  const currency = state.company.company.currency || 'USD';
  const price = state.company.market.price;
  elements.valuationBand.innerHTML = renderMethodComparison(dcf, relative, price, currency);
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

function renderMethodComparison(dcf, relative, price, currency) {
  const relativeValue = state.relativeConfirmed ? relative?.range?.mid : null;
  return `
    <div class="method-compare" aria-label="DCF와 상대가치 독립 비교">
      <article class="method-card">
        <span>DCF 독립 결과</span>
        <strong>${escapeHtml(dcf ? formatMoney(dcf.perShareValue, currency, { compact: false }) : 'N/A')}</strong>
        <small>정규화 FCF와 사용자가 조정한 성장률·할인율 기준입니다.</small>
      </article>
      <article class="method-card">
        <span>PER/PBR 상대가치</span>
        <strong>${escapeHtml(relativeValue ? formatMoney(relativeValue, currency, { compact: false }) : '사용자 검토 전')}</strong>
        <small>기본 배수는 예시값입니다. 비교기업/산업 현실성을 확인해야 요약값으로 사용합니다.</small>
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
    ? `<strong>DCF 계산 제한:</strong> ${escapeHtml(error)}`
    : `최근 정규화 FCF ${escapeHtml(formatMoney(state.assumptions.baseFreeCashFlow, currency))}에 성장률 ${escapeHtml(formatPercent(state.assumptions.growthRate, 2))}, 할인율 ${escapeHtml(formatPercent(state.assumptions.discountRate, 2))}, 영구성장률 ${escapeHtml(formatPercent(state.assumptions.terminalGrowthRate, 2))}을 적용했습니다. 입력값이 조금만 바뀌어도 결과가 크게 달라질 수 있습니다.`;
  if (!dcf) {
    elements.dcfTableWrap.innerHTML = '';
    elements.sensitivityWrap.innerHTML = '';
    return;
  }
  elements.dcfTableWrap.innerHTML = `
    <table>
      <caption>DCF 자유현금흐름 예측</caption>
      <thead><tr><th>연도</th><th>예상 FCF</th><th>현재가치</th></tr></thead>
      <tbody>${dcf.projectedFreeCashFlows.map((row) => `<tr><td>${row.year}</td><td>${formatMoney(row.freeCashFlow, currency)}</td><td>${formatMoney(row.presentValue, currency)}</td></tr>`).join('')}</tbody>
    </table>`;
  const sensitivity = buildSensitivity(state.assumptions);
  elements.sensitivityWrap.innerHTML = `
    <h3>할인율 × 영구성장률 민감도</h3>
    <div class="table-wrap">
      <table>
        <caption>DCF 민감도 매트릭스</caption>
        <thead><tr><th>할인율</th>${sensitivity[0].values.map((cell) => `<th>${formatPercent(cell.terminalGrowthRate, 1)}</th>`).join('')}</tr></thead>
        <tbody>${sensitivity.map((row) => `<tr><th scope="row">${formatPercent(row.discountRate, 1)}</th>${row.values.map((cell) => `<td>${formatMoney(cell.perShareValue, currency, { compact: false })}</td>`).join('')}</tr>`).join('')}</tbody>
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
  const rowHtml = (row) => `
    <tr>
      <th scope="row">${escapeHtml(row.label)}</th>
      <td>${formatMoney(row.baseMetric, currency, { compact: false })}</td>
      <td>${formatMultiple(row.currentMultiple)}</td>
      <td>${formatMultiple(row.benchmarkMultiple)}</td>
      <td>${formatMoney(row.impliedValue, currency, { compact: false })}</td>
      <td>${escapeHtml(row.description)}</td>
    </tr>`;
  elements.relativeTableWrap.innerHTML = `
    <div class="explain-box">
      ${state.relativeConfirmed
        ? 'PER/PBR 배수가 사용자 확인 상태입니다. 그래도 비교기업·산업·ROE 차이는 직접 검토해야 합니다.'
        : '아래 PER/PBR 값은 기본 예시 배수로 계산한 출발점입니다. 사용자 확인 전에는 요약 가치로 취급하지 않습니다.'}
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
  elements.memo.addEventListener('input', () => {
    if (!state.currentTicker) return;
    localStorage.setItem(`valuation:memo:${state.currentTicker}`, elements.memo.value);
  });
}

bindElements();
bindEvents();
loadIndex().catch((error) => {
  showDashboard(false);
  setStatus('데이터 인덱스를 불러오지 못했습니다', error.message, 'error');
});
