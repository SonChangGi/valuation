import { DEFAULT_ASSUMPTIONS } from './valuation-model.js';

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function numberOr(value, replacement) {
  const number = finiteNumber(value);
  return number === null ? replacement : number;
}

function nullableAssumption(source, key, replacement) {
  if (!Object.prototype.hasOwnProperty.call(source, key)) {
    return replacement;
  }
  if (source[key] === null) {
    return null;
  }
  return numberOr(source[key], replacement);
}

function assumptionOrDefault(source, key, replacement) {
  if (!Object.prototype.hasOwnProperty.call(source, key)) {
    return replacement;
  }
  return numberOr(source[key], replacement);
}

function normalizeDashboardAssumptions(assumptions = {}, latest = {}) {
  return {
    projectionYears: assumptionOrDefault(assumptions, 'projectionYears', DEFAULT_ASSUMPTIONS.projectionYears),
    growthRate: assumptionOrDefault(assumptions, 'growthRate', DEFAULT_ASSUMPTIONS.growthRate),
    discountRate: assumptionOrDefault(assumptions, 'discountRate', DEFAULT_ASSUMPTIONS.discountRate),
    terminalGrowthRate: assumptionOrDefault(assumptions, 'terminalGrowthRate', DEFAULT_ASSUMPTIONS.terminalGrowthRate),
    benchmarkPe: assumptionOrDefault(assumptions, 'benchmarkPe', DEFAULT_ASSUMPTIONS.benchmarkPe),
    benchmarkPb: assumptionOrDefault(assumptions, 'benchmarkPb', DEFAULT_ASSUMPTIONS.benchmarkPb),
    benchmarkPs: assumptionOrDefault(assumptions, 'benchmarkPs', DEFAULT_ASSUMPTIONS.benchmarkPs),
    benchmarkPfcf: assumptionOrDefault(assumptions, 'benchmarkPfcf', DEFAULT_ASSUMPTIONS.benchmarkPfcf),
    baseFreeCashFlow: nullableAssumption(assumptions, 'baseFreeCashFlow', finiteNumber(latest.freeCashFlow)),
    cash: assumptionOrDefault(assumptions, 'cash', numberOr(latest.cash, 0)),
    debt: assumptionOrDefault(assumptions, 'debt', 0),
    sharesOutstanding: nullableAssumption(assumptions, 'sharesOutstanding', numberOr(latest.sharesDiluted, 0)),
  };
}

export { normalizeDashboardAssumptions };
