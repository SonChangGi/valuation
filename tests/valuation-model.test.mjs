import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  buildReverseDcf,
  buildSensitivity,
  calculateDcf,
  calculateRelativeValuation,
  summarizeSensitivity,
} from '../docs/assets/valuation-model.js';

const fixtures = JSON.parse(fs.readFileSync(new URL('./fixtures/valuation_cases.json', import.meta.url), 'utf8'));

function assertClose(actual, expected, tolerance = 1e-9) {
  assert.ok(Number.isFinite(actual), `expected finite actual value, got ${actual}`);
  assert.ok(Math.abs(actual - expected) <= tolerance * Math.max(1, Math.abs(expected)), `${actual} != ${expected}`);
}

test('calculateDcf returns a per-share equity value and projection rows', () => {
  const result = calculateDcf({
    baseFreeCashFlow: 100,
    sharesOutstanding: 10,
    cash: 20,
    debt: 5,
    growthRate: 0.05,
    discountRate: 0.1,
    terminalGrowthRate: 0.02,
    projectionYears: 3,
  });
  assert.equal(result.projectedFreeCashFlows.length, 3);
  assert.equal(result.perShareValue, result.equityValue / 10);
  assert.ok(result.perShareValue > 0);
  assert.ok(result.diagnostics.terminalValueWeight > 0.5);
  assert.equal(Math.round(result.diagnostics.terminalSpread * 100), 8);
});

test('calculateDcf rejects terminal growth above discount rate', () => {
  assert.throws(() => calculateDcf({
    baseFreeCashFlow: 100,
    sharesOutstanding: 10,
    discountRate: 0.02,
    terminalGrowthRate: 0.03,
  }), /할인율/);
});

test('calculateRelativeValuation exposes PER and PBR rows', () => {
  const result = calculateRelativeValuation({
    price: 50,
    revenue: 1000,
    netIncome: 100,
    equity: 250,
    freeCashFlow: 80,
    sharesOutstanding: 10,
    benchmarkPe: 20,
    benchmarkPb: 3,
    benchmarkPs: 2,
    benchmarkPfcf: 15,
  });
  const rows = Object.fromEntries(result.rows.map((row) => [row.label, row]));
  assert.equal(rows.PER.impliedValue, 200);
  assert.equal(rows.PBR.impliedValue, 75);
  assert.ok(result.range.mid > 0);
  assert.equal(result.range.low, 75);
  assert.equal(result.range.mid, 137.5);
  assert.equal(result.range.high, 200);
  assert.equal(result.range.basis, 'PER/PBR headline only');
  assert.equal(result.range.confirmed, false);
  assert.equal(result.benchmarkSource, 'illustrative-default');
  assert.equal(result.qualitySignals.roe, 0.4);
  assert.equal(result.diagnostics.usableHeadlineMultiples, 2);
  assert.equal(result.diagnostics.qualityGate.status, 'needs_user_review');
});

test('calculateRelativeValuation excludes auxiliary multiples from headline range', () => {
  const result = calculateRelativeValuation({
    price: 50,
    revenue: 10_000,
    netIncome: 100,
    equity: 250,
    freeCashFlow: 10_000,
    sharesOutstanding: 10,
    benchmarkPe: 20,
    benchmarkPb: 3,
    benchmarkPs: 100,
    benchmarkPfcf: 100,
  });
  assert.equal(result.range.low, 75);
  assert.equal(result.range.high, 200);
  assert.ok(result.auxiliaryRange.mid > result.range.high);
});

test('calculateRelativeValuation marks user-confirmed benchmark multiples', () => {
  const result = calculateRelativeValuation({
    price: 50,
    revenue: 1000,
    netIncome: 100,
    equity: 250,
    freeCashFlow: 80,
    sharesOutstanding: 10,
    benchmarkPe: 20,
    benchmarkPb: 3,
    benchmarkSource: 'user-confirmed',
  });
  assert.equal(result.range.confirmed, true);
  assert.equal(result.benchmarkSource, 'user-confirmed');
});

test('browser valuation formulas match shared fixture', () => {
  const dcf = calculateDcf(fixtures.dcf.inputs);
  assertClose(dcf.perShareValue, fixtures.dcf.expected.perShareValue);
  assertClose(dcf.enterpriseValue, fixtures.dcf.expected.enterpriseValue);
  assertClose(dcf.equityValue, fixtures.dcf.expected.equityValue);
  assertClose(dcf.diagnostics.terminalValueWeight, fixtures.dcf.expected.terminalValueWeight);

  const relative = calculateRelativeValuation(fixtures.relative.inputs);
  assertClose(relative.range.low, fixtures.relative.expected.range.low);
  assertClose(relative.range.mid, fixtures.relative.expected.range.mid);
  assertClose(relative.range.high, fixtures.relative.expected.range.high);
  assertClose(relative.auxiliaryRange.mid, fixtures.relative.expected.auxiliaryRange.mid);
  assert.equal(relative.range.confirmed, false);
  assertClose(relative.qualitySignals.roe, fixtures.relative.expected.qualitySignals.roe);
});

test('buildReverseDcf solves current price implied growth from existing assumptions', () => {
  const dcf = calculateDcf({
    baseFreeCashFlow: 100,
    sharesOutstanding: 10,
    cash: 20,
    debt: 5,
    growthRate: 0.05,
    discountRate: 0.1,
    terminalGrowthRate: 0.02,
    projectionYears: 3,
  });
  const reverse = buildReverseDcf({
    marketPrice: dcf.perShareValue,
    baseFreeCashFlow: 100,
    sharesOutstanding: 10,
    cash: 20,
    debt: 5,
    growthRate: 0.05,
    discountRate: 0.1,
    terminalGrowthRate: 0.02,
    projectionYears: 3,
  });
  assert.equal(reverse.status, 'available');
  assert.equal(reverse.explicitGrowth.status, 'solved');
  assertClose(reverse.explicitGrowth.rate, 0.05, 1e-6);
});

test('summarizeSensitivity turns the matrix into a fragility signal', () => {
  const assumptions = {
    baseFreeCashFlow: 100,
    sharesOutstanding: 10,
    cash: 0,
    debt: 0,
    growthRate: 0.04,
    discountRate: 0.09,
    terminalGrowthRate: 0.025,
    projectionYears: 5,
  };
  const dcf = calculateDcf(assumptions);
  const sensitivity = buildSensitivity(assumptions);
  const summary = summarizeSensitivity(sensitivity, { baseValue: dcf.perShareValue, marketPrice: dcf.perShareValue });
  assert.ok(['stable', 'sensitive', 'fragile'].includes(summary.fragility));
  assert.ok(summary.high > summary.low);
  assert.equal(summary.priceCoverage, 'mixed');
});
