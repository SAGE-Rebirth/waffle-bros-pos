import { test } from 'node:test';
import assert from 'node:assert/strict';
import { itemsSummary, pageWindow, rangeFor, rangeKey, parseFilters, filtersQuery, apiQuery } from './bills.js';

const T = '2026-11-20';

test('item summary shows the first lines and counts the rest', () => {
  const items = [{ name: 'A', qty: 2 }, { name: 'B', qty: 1 }, { name: 'C', qty: 1 }, { name: 'D', qty: 3 }];
  assert.deepEqual(itemsSummary(items), { text: 'A ×2, B ×1, C ×1', more: 1, qty: 7 });
  assert.deepEqual(itemsSummary(items.slice(0, 1)), { text: 'A ×2', more: 0, qty: 2 });
});

test('page buttons keep first, last and neighbours', () => {
  assert.deepEqual(pageWindow(1, 1), [1]);
  assert.deepEqual(pageWindow(1, 3), [1, 2, 3]);
  assert.deepEqual(pageWindow(5, 10), [1, '…', 4, 5, 6, '…', 10]);
  assert.deepEqual(pageWindow(10, 10), [1, '…', 9, 10]);
});

test('quick ranges use the shop day', () => {
  assert.deepEqual(rangeFor('yesterday', '2026-12-01'), { from: '2026-11-30', to: '2026-11-30' });
  assert.deepEqual(rangeFor('7d', T), { from: '2026-11-14', to: T });
  assert.deepEqual(rangeFor('month', T), { from: '2026-11-01', to: T });
  assert.deepEqual(rangeFor('all', T), { from: '', to: '' });
  assert.equal(rangeKey('2026-11-01', T, T), 'month');
  assert.equal(rangeKey('2026-11-02', T, T), 'custom');
});

test('filters survive a round trip through the hash and default to today', () => {
  assert.deepEqual(parseFilters('', T), { from: T, to: T, q: '', status: 'all', payment: '', page: 1, size: 25 });
  const f = { from: '', to: '', q: ' 014 ', status: 'cancelled', payment: 'upi', page: 3, size: 50 };
  assert.deepEqual(parseFilters(filtersQuery(f), T), { ...f, q: '014' });
  assert.equal(apiQuery(f), 'q=014&status=cancelled&payment=upi&page=3&page_size=50');
  const bad = parseFilters('from=nope&to=2026-11-20&status=x&payment=gold&page=-2&size=7', T);
  assert.deepEqual(bad, { from: '', to: T, q: '', status: 'all', payment: '', page: 1, size: 25 });
});
