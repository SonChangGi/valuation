import test from 'node:test';
import assert from 'node:assert/strict';
import { calculateDcf, calculateRelativeValuation, summarizeRange } from '../docs/assets/valuation-model.js';

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

test('summarizeRange ignores null values', () => {
  assert.deepEqual(summarizeRange(null, 10, 20), { low: 10, mid: 15, high: 20 });
});
