import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeDashboardAssumptions } from '../docs/assets/assumptions.js';
import { calculateDcf } from '../docs/assets/valuation-model.js';

test('normalizeDashboardAssumptions preserves explicit null base FCF fail-closed state', () => {
  const normalized = normalizeDashboardAssumptions(
    { baseFreeCashFlow: null, sharesOutstanding: 10, cash: 0, debt: 0 },
    { freeCashFlow: 80, sharesDiluted: 10 },
  );

  assert.equal(normalized.baseFreeCashFlow, null);
  assert.throws(() => calculateDcf(normalized), /FCF/);
});

test('normalizeDashboardAssumptions uses latest FCF only when generated assumption is absent', () => {
  const normalized = normalizeDashboardAssumptions(
    { sharesOutstanding: 10, cash: 0, debt: 0 },
    { freeCashFlow: 80, sharesDiluted: 10 },
  );

  assert.equal(normalized.baseFreeCashFlow, 80);
  assert.ok(calculateDcf(normalized).perShareValue > 0);
});

test('normalizeDashboardAssumptions keeps DCF closed when generated and latest FCF are absent', () => {
  const normalized = normalizeDashboardAssumptions(
    { sharesOutstanding: 10, cash: 0, debt: 0 },
    { sharesDiluted: 10 },
  );

  assert.equal(normalized.baseFreeCashFlow, null);
  assert.throws(() => calculateDcf(normalized), /FCF/);
});
