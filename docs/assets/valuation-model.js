const DEFAULT_ASSUMPTIONS = Object.freeze({
  projectionYears: 5,
  growthRate: 0.04,
  discountRate: 0.09,
  terminalGrowthRate: 0.025,
  benchmarkPe: 22,
  benchmarkPb: 4,
  benchmarkPs: 5,
  benchmarkPfcf: 20,
});

const SENSITIVITY_DISCOUNT_RATES = [0.08, 0.09, 0.10];
const SENSITIVITY_TERMINAL_RATES = [0.015, 0.025, 0.035];

function safeNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function safeDivide(numerator, denominator) {
  const top = safeNumber(numerator);
  const bottom = safeNumber(denominator);
  if (top === null || bottom === null || bottom === 0) return null;
  return top / bottom;
}

function median(values) {
  const usable = values.filter((value) => value !== null && value !== undefined).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!usable.length) return null;
  const middle = Math.floor(usable.length / 2);
  return usable.length % 2 ? usable[middle] : (usable[middle - 1] + usable[middle]) / 2;
}

function calculateDcf({
  baseFreeCashFlow,
  sharesOutstanding,
  cash = 0,
  debt = 0,
  growthRate = DEFAULT_ASSUMPTIONS.growthRate,
  discountRate = DEFAULT_ASSUMPTIONS.discountRate,
  terminalGrowthRate = DEFAULT_ASSUMPTIONS.terminalGrowthRate,
  projectionYears = DEFAULT_ASSUMPTIONS.projectionYears,
}) {
  const base = safeNumber(baseFreeCashFlow);
  const shares = safeNumber(sharesOutstanding);
  const growth = safeNumber(growthRate);
  const discount = safeNumber(discountRate);
  const terminalGrowth = safeNumber(terminalGrowthRate);
  const years = Number.parseInt(projectionYears, 10);
  if (base === null || shares === null || shares <= 0) {
    throw new Error('FCF와 주식수가 있어야 DCF를 계산할 수 있습니다.');
  }
  if (discount === null || terminalGrowth === null || discount <= terminalGrowth) {
    throw new Error('할인율은 영구성장률보다 높아야 합니다.');
  }
  if (!Number.isInteger(years) || years < 1) {
    throw new Error('예측 기간은 1년 이상이어야 합니다.');
  }

  let fcf = base;
  let presentValueOfForecast = 0;
  const projectedFreeCashFlows = [];
  for (let year = 1; year <= years; year += 1) {
    fcf *= 1 + growth;
    const presentValue = fcf / ((1 + discount) ** year);
    presentValueOfForecast += presentValue;
    projectedFreeCashFlows.push({ year, freeCashFlow: fcf, presentValue });
  }
  const terminalFreeCashFlow = fcf * (1 + terminalGrowth);
  const terminalValue = terminalFreeCashFlow / (discount - terminalGrowth);
  const presentValueOfTerminal = terminalValue / ((1 + discount) ** years);
  const enterpriseValue = presentValueOfForecast + presentValueOfTerminal;
  const equityValue = enterpriseValue + Number(cash || 0) - Number(debt || 0);
  const perShareValue = equityValue / shares;
  return {
    baseFreeCashFlow: base,
    projectedFreeCashFlows,
    presentValueOfForecast,
    terminalValue,
    presentValueOfTerminal,
    enterpriseValue,
    equityValue,
    perShareValue,
  };
}

function calculateRelativeValuation({
  price,
  revenue,
  netIncome,
  equity,
  freeCashFlow,
  sharesOutstanding,
  benchmarkPe = DEFAULT_ASSUMPTIONS.benchmarkPe,
  benchmarkPb = DEFAULT_ASSUMPTIONS.benchmarkPb,
  benchmarkPs = DEFAULT_ASSUMPTIONS.benchmarkPs,
  benchmarkPfcf = DEFAULT_ASSUMPTIONS.benchmarkPfcf,
  benchmarkSource = 'illustrative-default',
}) {
  const shares = safeNumber(sharesOutstanding);
  if (shares === null || shares <= 0) {
    throw new Error('주식수가 있어야 상대가치를 계산할 수 있습니다.');
  }
  const eps = safeDivide(netIncome, shares);
  const bookValuePerShare = safeDivide(equity, shares);
  const salesPerShare = safeDivide(revenue, shares);
  const freeCashFlowPerShare = safeDivide(freeCashFlow, shares);
  const rows = [
    {
      key: 'pe',
      label: 'PER',
      baseMetric: eps,
      currentMultiple: eps && eps > 0 ? safeDivide(price, eps) : null,
      benchmarkMultiple: Number(benchmarkPe),
      impliedValue: eps && eps > 0 ? eps * Number(benchmarkPe) : null,
      description: '순이익 1주당 이익(EPS)에 비교 PER을 곱한 값',
    },
    {
      key: 'pb',
      label: 'PBR',
      baseMetric: bookValuePerShare,
      currentMultiple: bookValuePerShare && bookValuePerShare > 0 ? safeDivide(price, bookValuePerShare) : null,
      benchmarkMultiple: Number(benchmarkPb),
      impliedValue: bookValuePerShare && bookValuePerShare > 0 ? bookValuePerShare * Number(benchmarkPb) : null,
      description: '1주당 순자산(BPS)에 비교 PBR을 곱한 값',
    },
    {
      key: 'ps',
      label: 'P/S',
      baseMetric: salesPerShare,
      currentMultiple: salesPerShare && salesPerShare > 0 ? safeDivide(price, salesPerShare) : null,
      benchmarkMultiple: Number(benchmarkPs),
      impliedValue: salesPerShare && salesPerShare > 0 ? salesPerShare * Number(benchmarkPs) : null,
      description: '1주당 매출에 비교 P/S를 곱한 보조 값',
    },
    {
      key: 'pfcf',
      label: 'P/FCF',
      baseMetric: freeCashFlowPerShare,
      currentMultiple: freeCashFlowPerShare && freeCashFlowPerShare > 0 ? safeDivide(price, freeCashFlowPerShare) : null,
      benchmarkMultiple: Number(benchmarkPfcf),
      impliedValue: freeCashFlowPerShare && freeCashFlowPerShare > 0 ? freeCashFlowPerShare * Number(benchmarkPfcf) : null,
      description: '1주당 자유현금흐름에 비교 P/FCF를 곱한 보조 값',
    },
  ];
  const headlineValues = rows
    .filter((row) => row.key === 'pe' || row.key === 'pb')
    .map((row) => row.impliedValue)
    .filter(Number.isFinite);
  const auxiliaryValues = rows
    .filter((row) => row.key !== 'pe' && row.key !== 'pb')
    .map((row) => row.impliedValue)
    .filter(Number.isFinite);
  return {
    perShareMetrics: { eps, bookValuePerShare, salesPerShare, freeCashFlowPerShare },
    rows,
    range: {
      low: headlineValues.length ? Math.min(...headlineValues) : null,
      mid: median(headlineValues),
      high: headlineValues.length ? Math.max(...headlineValues) : null,
      basis: 'PER/PBR headline only',
      confirmed: benchmarkSource !== 'illustrative-default',
    },
    auxiliaryRange: {
      low: auxiliaryValues.length ? Math.min(...auxiliaryValues) : null,
      mid: median(auxiliaryValues),
      high: auxiliaryValues.length ? Math.max(...auxiliaryValues) : null,
      basis: 'P/S and P/FCF auxiliary cross-check only',
    },
    benchmarkSource,
    benchmarkNote: '기본 배수는 예시값이며 사용자가 산업/비교기업 기준으로 확인해야 합니다.',
  };
}

function buildSensitivity({ baseFreeCashFlow, sharesOutstanding, cash, debt, growthRate, projectionYears }) {
  return SENSITIVITY_DISCOUNT_RATES.map((discountRate) => ({
    discountRate,
    values: SENSITIVITY_TERMINAL_RATES.map((terminalGrowthRate) => {
      try {
        return {
          terminalGrowthRate,
          perShareValue: calculateDcf({
            baseFreeCashFlow,
            sharesOutstanding,
            cash,
            debt,
            growthRate,
            discountRate,
            terminalGrowthRate,
            projectionYears,
          }).perShareValue,
        };
      } catch (_error) {
        return { terminalGrowthRate, perShareValue: null };
      }
    }),
  }));
}

function formatMoney(value, currency = 'USD', options = {}) {
  const number = safeNumber(value);
  if (number === null) return 'N/A';
  const compact = options.compact ?? Math.abs(number) >= 1_000_000;
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency,
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 2 : 2,
  }).format(number);
}

function formatPercent(value, digits = 1) {
  const number = safeNumber(value);
  if (number === null) return 'N/A';
  return new Intl.NumberFormat('ko-KR', { style: 'percent', maximumFractionDigits: digits }).format(number);
}

function formatMultiple(value) {
  const number = safeNumber(value);
  if (number === null) return 'N/A';
  return `${number.toFixed(1)}배`;
}

export {
  DEFAULT_ASSUMPTIONS,
  SENSITIVITY_DISCOUNT_RATES,
  SENSITIVITY_TERMINAL_RATES,
  buildSensitivity,
  calculateDcf,
  calculateRelativeValuation,
  formatMoney,
  formatMultiple,
  formatPercent,
  median,
  safeDivide,
};
