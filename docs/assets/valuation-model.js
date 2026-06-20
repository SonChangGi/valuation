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
const IMPLIED_EXPLICIT_GROWTH_BOUNDS = [-0.10, 0.18];
const IMPLIED_TERMINAL_GROWTH_BOUNDS = [-0.02, 0.045];

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

function diagnosticFlag(level, title, detail) {
  return { level, title, detail };
}

function finiteNumbers(values) {
  return values
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map(Number)
    .filter(Number.isFinite);
}

function summarizeSensitivity(sensitivity, { baseValue, marketPrice } = {}) {
  const values = finiteNumbers(
    (sensitivity || []).flatMap((row) => (row.values || []).map((cell) => cell.perShareValue)),
  );
  if (!values.length) {
    return {
      low: null,
      mid: null,
      high: null,
      rangeWidth: null,
      rangeToBase: null,
      priceCoverage: 'unavailable',
      fragility: 'unavailable',
      flags: [diagnosticFlag('warning', '민감도 계산 불가', 'DCF 민감도 행렬을 만들 수 없어 단일 가치의 취약성을 판단할 수 없습니다.')],
      interpretation: '민감도는 할인율과 영구성장률의 작은 변화가 주당가치에 주는 영향을 보는 장치입니다.',
    };
  }
  const low = Math.min(...values);
  const high = Math.max(...values);
  const mid = median(values);
  const rangeWidth = high - low;
  const rangeToBase = baseValue ? safeDivide(rangeWidth, Math.abs(baseValue)) : null;
  const price = safeNumber(marketPrice);
  const valuesAbovePrice = price ? values.filter((value) => value >= price).length : null;
  const valuesBelowPrice = price ? values.filter((value) => value < price).length : null;
  let priceCoverage = 'unavailable';
  if (price) {
    if (valuesAbovePrice && valuesBelowPrice) priceCoverage = 'mixed';
    else if (valuesAbovePrice) priceCoverage = 'above_price';
    else if (valuesBelowPrice) priceCoverage = 'below_price';
  }
  let fragility = 'unavailable';
  if (rangeToBase !== null) {
    if (rangeToBase >= 0.75) fragility = 'fragile';
    else if (rangeToBase >= 0.35) fragility = 'sensitive';
    else fragility = 'stable';
  }
  const flags = [];
  if (fragility === 'fragile') {
    flags.push(diagnosticFlag('warning', '민감도 범위 매우 넓음', '할인율·영구성장률의 작은 변화가 기준 DCF 가치를 크게 흔듭니다. 단일 가치보다 범위를 우선하세요.'));
  } else if (fragility === 'sensitive') {
    flags.push(diagnosticFlag('watch', '민감도 확인 필요', 'DCF 범위가 기준값 대비 의미 있게 넓습니다. 낙관·비관 가정의 근거를 나눠 검토하세요.'));
  }
  if (priceCoverage === 'mixed') {
    flags.push(diagnosticFlag('watch', '현재가 판단이 가정에 따라 뒤집힘', '민감도 행렬 안에서 현재가보다 높은 칸과 낮은 칸이 모두 있습니다. 결론보다 가정 검증이 우선입니다.'));
  }
  return {
    low,
    mid,
    high,
    rangeWidth,
    rangeToBase,
    valuesAbovePrice,
    valuesBelowPrice,
    priceCoverage,
    fragility,
    flags,
    interpretation: '민감도 범위는 DCF가 정밀한 목표가인지, 아니면 가정 취약성 지도를 먼저 읽어야 하는지 알려줍니다.',
  };
}

function solveMonotonicRate({ targetValue, lower, upper, valueAtRate, iterations = 64 }) {
  const lowerValue = valueAtRate(lower);
  const upperValue = valueAtRate(upper);
  if (lowerValue === null || upperValue === null) {
    return {
      status: 'not_available',
      rate: null,
      lowerBound: lower,
      upperBound: upper,
      valueAtLowerBound: lowerValue,
      valueAtUpperBound: upperValue,
    };
  }
  if (targetValue < lowerValue) {
    return {
      status: 'below_range',
      rate: null,
      lowerBound: lower,
      upperBound: upper,
      valueAtLowerBound: lowerValue,
      valueAtUpperBound: upperValue,
    };
  }
  if (targetValue > upperValue) {
    return {
      status: 'above_range',
      rate: null,
      lowerBound: lower,
      upperBound: upper,
      valueAtLowerBound: lowerValue,
      valueAtUpperBound: upperValue,
    };
  }
  let lo = lower;
  let hi = upper;
  let mid = (lo + hi) / 2;
  let midValue = valueAtRate(mid);
  for (let index = 0; index < iterations; index += 1) {
    mid = (lo + hi) / 2;
    midValue = valueAtRate(mid);
    if (midValue === null) break;
    if (midValue < targetValue) lo = mid;
    else hi = mid;
  }
  return {
    status: 'solved',
    rate: mid,
    lowerBound: lower,
    upperBound: upper,
    valueAtLowerBound: lowerValue,
    valueAtUpperBound: upperValue,
    valueAtSolvedRate: midValue,
  };
}

function buildDcfDiagnostics({
  presentValueOfForecast,
  presentValueOfTerminal,
  enterpriseValue,
  equityValue,
  cash,
  debt,
  discountRate,
  terminalGrowthRate,
}) {
  const terminalValueWeight = safeDivide(presentValueOfTerminal, enterpriseValue);
  const forecastValueWeight = safeDivide(presentValueOfForecast, enterpriseValue);
  const terminalSpread = discountRate - terminalGrowthRate;
  const netDebt = Number(debt || 0) - Number(cash || 0);
  const flags = [];

  if (terminalValueWeight !== null && terminalValueWeight >= 0.75) {
    flags.push(diagnosticFlag(
      'warning',
      '터미널 가치 집중',
      '기업가치의 75% 이상이 명시 예측 이후에서 나옵니다. 영구성장률과 할인율 근거를 보수적으로 재점검하세요.',
    ));
  } else if (terminalValueWeight !== null && terminalValueWeight >= 0.6) {
    flags.push(diagnosticFlag(
      'watch',
      '터미널 가치 영향 큼',
      '기업가치의 상당 부분이 터미널 가치입니다. 단일 주당가치보다 민감도 범위를 함께 읽으세요.',
    ));
  }

  if (terminalSpread < 0.025) {
    flags.push(diagnosticFlag(
      'warning',
      '할인율-영구성장률 간격 좁음',
      '작은 가정 변화가 터미널 가치를 크게 바꿀 수 있습니다. 장기 성장률이 지속 가능한지 확인하세요.',
    ));
  }
  if (terminalGrowthRate > 0.035) {
    flags.push(diagnosticFlag(
      'watch',
      '영구성장률 상단 근접',
      '영구성장률은 장기 경제 성장과 재투자 여력을 넘기 어렵다는 전제를 명시하세요.',
    ));
  }
  if (equityValue <= 0) {
    flags.push(diagnosticFlag(
      'warning',
      '자기자본가치 비양수',
      '순부채 조정 이후 자기자본가치가 0 이하입니다. 부채·현금·주식수 데이터를 원문에서 확인하세요.',
    ));
  }

  return {
    terminalValueWeight,
    forecastValueWeight,
    terminalSpread,
    netDebt,
    flags,
    interpretation: 'DCF는 FCFF의 현재가치와 안정성장 터미널 가치를 분리해서 읽어야 하며, 터미널 비중이 높을수록 가정 검증이 더 중요합니다.',
  };
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
  const diagnostics = buildDcfDiagnostics({
    presentValueOfForecast,
    presentValueOfTerminal,
    enterpriseValue,
    equityValue,
    cash,
    debt,
    discountRate: discount,
    terminalGrowthRate: terminalGrowth,
  });
  return {
    baseFreeCashFlow: base,
    projectedFreeCashFlows,
    presentValueOfForecast,
    terminalValue,
    presentValueOfTerminal,
    enterpriseValue,
    equityValue,
    perShareValue,
    diagnostics,
  };
}

function buildReverseDcf({
  marketPrice,
  baseFreeCashFlow,
  sharesOutstanding,
  cash = 0,
  debt = 0,
  growthRate = DEFAULT_ASSUMPTIONS.growthRate,
  discountRate = DEFAULT_ASSUMPTIONS.discountRate,
  terminalGrowthRate = DEFAULT_ASSUMPTIONS.terminalGrowthRate,
  projectionYears = DEFAULT_ASSUMPTIONS.projectionYears,
}) {
  const price = safeNumber(marketPrice);
  const base = safeNumber(baseFreeCashFlow);
  const shares = safeNumber(sharesOutstanding);
  const discount = safeNumber(discountRate);
  const terminal = safeNumber(terminalGrowthRate);
  if (
    price === null
    || price <= 0
    || base === null
    || base <= 0
    || shares === null
    || shares <= 0
    || discount === null
    || terminal === null
    || discount <= terminal
  ) {
    return {
      status: 'not_available',
      marketPrice: price,
      targetEquityValue: null,
      explicitGrowth: null,
      terminalGrowth: null,
      flags: [diagnosticFlag('warning', 'Reverse DCF 제한', '시장가격, 양수 FCF, 주식수, 할인율 조건이 모두 있어야 내재 기대를 역산할 수 있습니다.')],
      interpretation: 'Reverse DCF는 현재가가 어떤 성장 가정을 요구하는지 보는 보조 분석입니다.',
    };
  }
  const valueWithGrowth = (rate) => {
    try {
      return calculateDcf({
        baseFreeCashFlow: base,
        sharesOutstanding: shares,
        cash,
        debt,
        growthRate: rate,
        discountRate: discount,
        terminalGrowthRate: terminal,
        projectionYears,
      }).perShareValue;
    } catch (_error) {
      return null;
    }
  };
  const terminalUpper = Math.min(IMPLIED_TERMINAL_GROWTH_BOUNDS[1], discount - 0.015);
  const valueWithTerminal = (rate) => {
    try {
      return calculateDcf({
        baseFreeCashFlow: base,
        sharesOutstanding: shares,
        cash,
        debt,
        growthRate,
        discountRate: discount,
        terminalGrowthRate: rate,
        projectionYears,
      }).perShareValue;
    } catch (_error) {
      return null;
    }
  };
  const explicitGrowth = solveMonotonicRate({
    targetValue: price,
    lower: IMPLIED_EXPLICIT_GROWTH_BOUNDS[0],
    upper: IMPLIED_EXPLICIT_GROWTH_BOUNDS[1],
    valueAtRate: valueWithGrowth,
  });
  const terminalGrowth = terminalUpper > IMPLIED_TERMINAL_GROWTH_BOUNDS[0]
    ? solveMonotonicRate({
      targetValue: price,
      lower: IMPLIED_TERMINAL_GROWTH_BOUNDS[0],
      upper: terminalUpper,
      valueAtRate: valueWithTerminal,
    })
    : {
      status: 'not_available',
      rate: null,
      lowerBound: IMPLIED_TERMINAL_GROWTH_BOUNDS[0],
      upperBound: terminalUpper,
    };
  const flags = [];
  if (explicitGrowth.status === 'above_range') {
    flags.push(diagnosticFlag('warning', '시장가가 높은 성장 기대 요구', '현재가를 설명하려면 보수적 상단을 넘는 명시 성장률이 필요합니다. 성장 옵션의 현실성을 직접 검토하세요.'));
  } else if (explicitGrowth.status === 'below_range') {
    flags.push(diagnosticFlag('watch', '시장가가 낮은 성장 기대 반영', '현재가가 보수적 성장 범위보다 낮은 DCF를 암시합니다. 구조적 악화나 데이터 오류 가능성을 확인하세요.'));
  }
  if (terminalGrowth.status === 'above_range') {
    flags.push(diagnosticFlag('warning', '영구성장률 상단 초과 요구', '현재가를 설명하려면 장기 안정성장 가정이 보수적 상단을 넘습니다. 터미널 가치 의존도를 특히 주의하세요.'));
  }
  return {
    status: 'available',
    marketPrice: price,
    targetEquityValue: price * shares,
    explicitGrowth,
    terminalGrowth,
    flags,
    interpretation: 'Reverse DCF는 목표가를 제시하지 않고, 현재 시장가격이 어떤 성장률/영구성장률을 요구하는지 보여줍니다.',
  };
}

function buildRelativeQualityGate({
  eps,
  bookValuePerShare,
  roe,
  netMargin,
  fcfMargin,
  headlineCount,
  benchmarkSource,
}) {
  const checks = [
    { key: 'positive_eps', label: 'EPS 양수', passed: eps !== null && eps > 0 },
    { key: 'positive_bps', label: 'BPS 양수', passed: bookValuePerShare !== null && bookValuePerShare > 0 },
    { key: 'headline_pair', label: 'PER/PBR 모두 산출', passed: headlineCount >= 2 },
    { key: 'user_confirmed', label: '사용자 비교배수 확인', passed: benchmarkSource !== 'illustrative-default' },
    { key: 'profit_quality', label: '수익성 신호 양호', passed: (netMargin === null || netMargin > 0) && (fcfMargin === null || fcfMargin >= 0) },
    { key: 'roe_context', label: 'ROE 맥락 확인', passed: roe === null || roe >= 0.08 },
  ];
  const blocking = checks.slice(0, 3).filter((check) => !check.passed);
  let status = 'usable';
  let label = '사용자 확인됨';
  let detail = '사용자가 비교배수를 확인했고 기본 수익성 신호가 통과했습니다. 모델 검증이 아니라 사용자 입력 기준이므로 DCF와 분리해서 보세요.';
  if (blocking.length) {
    status = 'limited';
    label = '사용 제한';
    detail = 'EPS/BPS 또는 PER/PBR 산출 조건이 부족해 상대가치를 핵심 결론으로 쓰기 어렵습니다.';
  } else if (benchmarkSource === 'illustrative-default') {
    status = 'needs_user_review';
    label = '검토 전';
    detail = '기본 배수는 예시값입니다. 비교기업의 산업·성장률·ROE 유사성을 확인해야 합니다.';
  } else if (!checks[4].passed || !checks[5].passed) {
    status = 'usable_with_caution';
    label = '사용자 확인·주의';
    detail = '사용자가 배수를 확인했지만 수익성/현금흐름 품질 신호가 약해 보수적으로 해석해야 합니다.';
  }
  return {
    status,
    label,
    checks,
    detail,
    interpretation: '상대가치는 싸다/비싸다 자동판정이 아니라 비교군 품질을 통과했는지 확인하는 절차입니다.',
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
  const roe = safeDivide(netIncome, equity);
  const netMargin = safeDivide(netIncome, revenue);
  const fcfMargin = safeDivide(freeCashFlow, revenue);
  const earningsYield = safeDivide(eps, price);
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
  const flags = [];
  if (eps === null || eps <= 0) {
    flags.push(diagnosticFlag('warning', 'PER 사용 제한', 'EPS가 양수가 아니면 PER 기반 암시 주가를 핵심 결론으로 쓰지 마세요.'));
  }
  if (bookValuePerShare === null || bookValuePerShare <= 0) {
    flags.push(diagnosticFlag('warning', 'PBR 사용 제한', 'BPS가 양수가 아니면 PBR 비교가 경제적으로 취약합니다.'));
  }
  if (roe !== null && roe < 0.08 && bookValuePerShare && bookValuePerShare > 0) {
    flags.push(diagnosticFlag('watch', 'ROE 확인 필요', 'PBR은 장부가치만이 아니라 지속 가능한 ROE와 함께 해석해야 합니다.'));
  }
  if (fcfMargin !== null && fcfMargin < 0) {
    flags.push(diagnosticFlag('watch', '현금흐름 괴리', '순이익과 달리 FCF가 약하면 운전자본·CAPEX·일회성 요인을 확인하세요.'));
  }
  const qualityGate = buildRelativeQualityGate({
    eps,
    bookValuePerShare,
    roe,
    netMargin,
    fcfMargin,
    headlineCount: headlineValues.length,
    benchmarkSource,
  });
  return {
    perShareMetrics: { eps, bookValuePerShare, salesPerShare, freeCashFlowPerShare },
    qualitySignals: { roe, netMargin, fcfMargin, earningsYield },
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
    diagnostics: {
      usableHeadlineMultiples: headlineValues.length,
      qualityGate,
      flags,
      interpretation: '시장 배수는 성장률·수익성·위험·회계 품질이 비슷한 비교군을 전제로 할 때만 의미가 커집니다.',
    },
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
  buildDcfDiagnostics,
  buildReverseDcf,
  buildRelativeQualityGate,
  buildSensitivity,
  calculateDcf,
  calculateRelativeValuation,
  formatMoney,
  formatMultiple,
  formatPercent,
  median,
  safeDivide,
  summarizeSensitivity,
};
