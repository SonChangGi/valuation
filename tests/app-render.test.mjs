import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

class MockElement {
  constructor(selector) {
    this.selector = selector;
    this.children = [];
    this.value = '';
    this.label = '';
    this.type = '';
    this.name = '';
    this.className = '';
    this._textContent = '';
    this._innerHTML = '';
    this.classList = { toggle: () => undefined };
  }

  set textContent(value) {
    this._textContent = String(value);
  }

  get textContent() {
    return this._textContent;
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
  }

  get innerHTML() {
    return this._innerHTML;
  }

  replaceChildren(...children) {
    this.children = children;
  }

  addEventListener() {
    return undefined;
  }
}

function installBrowserMocks() {
  const nodes = new Map();
  Object.defineProperty(globalThis, 'document', {
    value: {
      querySelector(selector) {
        if (!nodes.has(selector)) nodes.set(selector, new MockElement(selector));
        return nodes.get(selector);
      },
      createElement(tag) {
        return new MockElement(tag);
      },
    },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'localStorage', {
    value: { getItem: () => '', setItem: () => undefined },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'navigator', {
    value: { clipboard: { writeText: async () => undefined } },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'window', {
    value: { print: () => undefined },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'fetch', {
    value: async (resource) => {
      const file = path.resolve('docs', String(resource));
      try {
        const text = await fs.readFile(file, 'utf8');
        return { ok: true, status: 200, json: async () => JSON.parse(text) };
      } catch (_error) {
        return { ok: false, status: 404, json: async () => ({}) };
      }
    },
    configurable: true,
  });
  return nodes;
}

test('browser app renders decision cockpit and valuation visuals from static data', async () => {
  const nodes = installBrowserMocks();
  await import(`../docs/assets/app.js?test=${Date.now()}`);
  await new Promise((resolve) => setTimeout(resolve, 50));

  assert.match(nodes.get('#decision-cockpit')?.innerHTML || '', /가치 레이더와 다음 행동/);
  assert.match(nodes.get('#dcf-table-wrap')?.innerHTML || '', /DCF 현금흐름 시각화/);
  assert.match(nodes.get('#relative-table-wrap')?.innerHTML || '', /상대가치 시각화/);
  assert.match(nodes.get('#valuation-band')?.innerHTML || '', /valuation-scale/);
});
