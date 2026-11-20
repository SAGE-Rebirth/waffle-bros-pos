// pinApi: counter actions ask for the PIN every time and never keep the token on the tablet.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const store = new Map();
globalThis.sessionStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.window = new EventTarget();
const calls = [];
globalThis.fetch = async (url, opts) => {
  calls.push({ url, auth: opts.headers.Authorization });
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};

const { adminSession, pinApi, PIN_NEEDED_EVENT } = await import('./api.js');

let prompts = 0;
window.addEventListener(PIN_NEEDED_EVENT, (e) => {
  prompts += 1;
  e.detail.resolve({ token: `once-${prompts}`, expires_at: Date.now() / 1000 + 120 });
});

test('every counter action asks for the PIN and uses that one token', async () => {
  await pinApi.post('/api/orders/1/cancel', {}, 'cancel');
  await pinApi.del('/api/expenses/2', 'delete');
  assert.equal(prompts, 2);
  assert.deepEqual(calls.map((c) => c.auth), ['Bearer once-1', 'Bearer once-2']);
  assert.equal(adminSession.get(), null); // nothing saved on the tablet
});

test('an Admin page session on the same tablet is not reused at the counter', async () => {
  adminSession.set({ token: 'admin-session', expires_at: Date.now() / 1000 + 3600 });
  calls.length = 0;
  await pinApi.put('/api/targets/2026-11', { amount: 1 }, 'target');
  assert.equal(calls[0].auth, `Bearer once-${prompts}`);
  assert.equal(adminSession.get().token, 'admin-session');
  adminSession.clear();
});

test('closing the PIN prompt cancels the action', async () => {
  const listener = (e) => { e.stopImmediatePropagation(); e.detail.reject(Object.assign(new Error('PIN not entered'), { cancelled: true })); };
  const t = new EventTarget();
  // Re-route by swapping window for this test only.
  const real = globalThis.window;
  globalThis.window = t;
  t.addEventListener(PIN_NEEDED_EVENT, listener);
  calls.length = 0;
  await assert.rejects(pinApi.post('/api/expenses', {}, 'add'), /PIN not entered/);
  assert.equal(calls.length, 0);
  globalThis.window = real;
});
