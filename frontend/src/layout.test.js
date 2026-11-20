// Run with `npm test` (Node's built-in test runner, no extra packages).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CARDS, LAYOUT_KEY, MAX_HEIGHT, MIN_HEIGHT, defaultLayout, sanitize, moveCard, dropCard, resizeCard, setHidden,
  isDefault, loadLayout, saveLayout, widthLabel, heightLabel, setSize, snapWidth, snapHeight,
} from './layout.js';

const ids = CARDS.map((c) => c.id);

function memoryStorage(init = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    has: (k) => m.has(k),
  };
}

test('default layout lists every card once with its default width', () => {
  const l = defaultLayout();
  assert.deepEqual(l.order, ids);
  assert.equal(new Set(l.order).size, CARDS.length);
  assert.equal(l.width.target, 12);
  assert.equal(l.width.items, 7);
  assert.deepEqual(l.hidden, []);
  assert.deepEqual(l.height, {});
});

test('sanitize falls back to the default for junk', () => {
  for (const junk of [null, undefined, 42, 'x', [], {}, { order: 'nope' }, { order: [] }, { order: ['ghost'] }]) {
    assert.deepEqual(sanitize(junk), defaultLayout());
  }
});

test('sanitize drops unknown and duplicate cards and keeps the saved order', () => {
  const l = sanitize({ order: ['payments', 'ghost', 'target', 'payments', ...ids], width: {}, hidden: [] });
  assert.deepEqual(l.order.slice(0, 2), ['payments', 'target']);
  assert.equal(l.order.length, CARDS.length);
  assert.equal(new Set(l.order).size, CARDS.length);
});

test('sanitize slots a card missing from an old save in after its default neighbour', () => {
  const old = ids.filter((id) => id !== 'calendar').reverse();
  const l = sanitize({ order: old });
  assert.equal(l.order.length, CARDS.length);
  assert.equal(l.order[l.order.indexOf('insights') + 1], 'calendar');
  const first = sanitize({ order: ids.filter((id) => id !== 'target') });
  assert.equal(first.order[0], 'target');
});

test('sanitize rejects widths that are not allowed', () => {
  const l = sanitize({ order: ids, width: { target: 5, sales: 13, items: '6', expenses: 6.5 } });
  assert.equal(l.width.target, 5);
  assert.equal(l.width.sales, 8);
  assert.equal(l.width.items, 7);
  assert.equal(l.width.expenses, 5);
});

test('sanitize never hides every card', () => {
  assert.deepEqual(sanitize({ order: ids, hidden: ids }).hidden, []);
  assert.deepEqual(sanitize({ order: ids, hidden: ['insights', 'ghost', 'insights'] }).hidden, ['insights']);
});

test('moveCard and dropCard reorder without losing cards', () => {
  const l = defaultLayout();
  assert.deepEqual(moveCard(l, 'payments', 0).order.slice(0, 2), ['payments', 'target']);
  assert.equal(moveCard(l, 'target', 99).order.at(-1), 'target');
  assert.equal(moveCard(l, 'ghost', 0), l);
  assert.equal(moveCard(l, 'target', 0), l);
  const d = dropCard(l, 'target', 'insights');
  assert.deepEqual(d.order.slice(0, 3), ['sales', 'insights', 'target']);
  const back = dropCard(d, 'target', 'sales');
  assert.deepEqual(back.order, ids);
  assert.equal(dropCard(l, 'target', null), l);
  assert.equal(dropCard(l, 'target', 'target'), l);
});

test('resizeCard steps through the allowed widths and stops at the ends', () => {
  let l = defaultLayout();
  l = resizeCard(l, 'items', +1);
  assert.equal(l.width.items, 8);
  for (let i = 0; i < 3; i++) l = resizeCard(l, 'items', +1);
  assert.equal(l.width.items, 11);
  l = resizeCard(l, 'items', +1);
  assert.equal(l.width.items, 12);
  assert.equal(resizeCard(l, 'items', +1), l);
  let s = defaultLayout();
  for (let i = 0; i < 10; i++) s = resizeCard(s, 'payments', -1);
  assert.equal(s.width.payments, 3);
});

test('setHidden hides and shows cards but always leaves one', () => {
  let l = setHidden(defaultLayout(), 'insights', true);
  assert.deepEqual(l.hidden, ['insights']);
  assert.deepEqual(setHidden(l, 'insights', false).hidden, []);
  for (const id of ids) l = setHidden(l, id, true);
  assert.equal(l.hidden.length, CARDS.length - 1);
});

test('isDefault and widthLabel', () => {
  assert.ok(isDefault(defaultLayout()));
  assert.ok(!isDefault(moveCard(defaultLayout(), 'payments', 0)));
  assert.equal(widthLabel(12), 'Full');
  assert.equal(widthLabel(6), '50%');
  assert.equal(widthLabel(4), '33%');
});

test('save and load round-trip; the default layout clears the saved one', () => {
  const store = memoryStorage();
  const l = resizeCard(moveCard(defaultLayout(), 'payments', 0), 'sales', +1);
  assert.ok(saveLayout(l, store));
  assert.deepEqual(loadLayout(store), l);
  assert.ok(saveLayout(defaultLayout(), store));
  assert.ok(!store.has(LAYOUT_KEY));
  assert.deepEqual(loadLayout(store), defaultLayout());
});

test('load survives broken JSON and blocked storage', () => {
  assert.deepEqual(loadLayout(memoryStorage({ [LAYOUT_KEY]: '{oops' })), defaultLayout());
  const blocked = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); }, removeItem() { throw new Error('denied'); } };
  assert.deepEqual(loadLayout(blocked), defaultLayout());
  assert.equal(saveLayout(moveCard(defaultLayout(), 'payments', 0), blocked), false);
  assert.deepEqual(loadLayout(undefined), defaultLayout());
});

test('snapWidth picks the nearest allowed width', () => {
  assert.equal(snapWidth(6.4), 6);
  assert.equal(snapWidth(6.6), 7);
  assert.equal(snapWidth(0), 3);
  assert.equal(snapWidth(-5), 3);
  assert.equal(snapWidth(40), 12);
  assert.equal(snapWidth(NaN), 12);
});

test('snapHeight rounds to 10 px within limits; null means automatic', () => {
  assert.equal(snapHeight(423), 420);
  assert.equal(snapHeight(5), MIN_HEIGHT);
  assert.equal(snapHeight(99999), MAX_HEIGHT);
  assert.equal(snapHeight(null), null);
  assert.equal(snapHeight(Infinity), null);
});

test('setSize changes width and height, and null height goes back to automatic', () => {
  let l = setSize(defaultLayout(), 'sales', { width: 9.7, height: 512 });
  assert.equal(l.width.sales, 10);
  assert.equal(l.height.sales, 510);
  assert.ok(!isDefault(l));
  l = setSize(l, 'sales', { width: 8 });
  assert.equal(l.height.sales, 510); // height kept when only the width changes
  l = setSize(l, 'sales', { height: null });
  assert.equal('sales' in l.height, false);
  assert.ok(isDefault(l));
  const same = defaultLayout();
  assert.equal(setSize(same, 'sales', { width: 8 }), same);
  assert.equal(setSize(same, 'ghost', { width: 4 }), same);
});

test('sanitize keeps only sensible heights', () => {
  const l = sanitize({ order: ids, height: { sales: 400, items: 20, expenses: 'tall', calendar: 99999, ghost: 300, target: 412.5 } });
  assert.deepEqual(l.height, { sales: 400 });
  assert.deepEqual(sanitize({ order: ids, height: 'x' }).height, {});
});

test('a saved layout with heights round-trips', () => {
  const store = new Map();
  const s = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
  const l = setSize(defaultLayout(), 'calendar', { width: 6, height: 700 });
  saveLayout(l, s);
  assert.deepEqual(loadLayout(s), l);
  assert.equal(heightLabel(null), 'Auto height');
  assert.equal(heightLabel(700), '700px tall');
});
