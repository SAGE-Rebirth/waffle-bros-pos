// Google Sheets sync. Pushes new orders, order items and expenses as rows, and
// rewrites a "Daily" summary tab, so the data can be reviewed outside the shop.
//
// Setup (once): create a Google Cloud service account, download its JSON key,
// share the spreadsheet with the service account's email as Editor, then fill in
// Settings → Google Sheet in the POS. No extra npm packages are needed.
import { readFileSync } from 'node:fs';
import { createSign } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { db, getSettings, setSettings } from './db.js';
import { fmtDateTime, fmtDate, addDays } from './time.js';

const SCOPE = 'https://www.googleapis.com/auth/spreadsheets';
let cachedToken = null;

const b64url = (buf) => Buffer.from(buf).toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');

async function accessToken(credPath) {
  if (cachedToken && cachedToken.exp > Date.now() + 60_000) return cachedToken.token;
  const key = JSON.parse(readFileSync(credPath, 'utf8'));
  const now = Math.floor(Date.now() / 1000);
  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claim = b64url(JSON.stringify({ iss: key.client_email, scope: SCOPE, aud: key.token_uri || 'https://oauth2.googleapis.com/token', iat: now, exp: now + 3600 }));
  const signer = createSign('RSA-SHA256');
  signer.update(`${header}.${claim}`);
  const jwt = `${header}.${claim}.${b64url(signer.sign(key.private_key))}`;
  const res = await fetch(key.token_uri || 'https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion: jwt }),
  });
  if (!res.ok) throw new Error(`Google auth failed: ${res.status} ${await res.text()}`);
  const j = await res.json();
  cachedToken = { token: j.access_token, exp: Date.now() + j.expires_in * 1000 };
  return cachedToken.token;
}

async function api(token, sheetId, path, method = 'GET', body) {
  const res = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${sheetId}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`Sheets API ${method} ${path}: ${res.status} ${await res.text()}`);
  return res.json();
}

const TABS = {
  Orders: ['Bill No', 'Date', 'Time', 'Items', 'Subtotal', 'Discount', 'Tax', 'Total', 'Payment', 'Order Type', 'Source', 'Status', 'Customer', 'Phone'],
  OrderItems: ['Bill No', 'Date', 'Time', 'Item', 'Category', 'Price', 'Qty', 'Line Total'],
  Expenses: ['Date', 'Category', 'Amount', 'Recurring', 'Note'],
  Daily: ['Date', 'Revenue', 'Orders', 'Avg Bill', 'Top Item'],
};

async function ensureTabs(token, sheetId) {
  const meta = await api(token, sheetId, '?fields=sheets.properties.title');
  const have = new Set(meta.sheets.map((s) => s.properties.title));
  const missing = Object.keys(TABS).filter((t) => !have.has(t));
  if (missing.length) {
    await api(token, sheetId, ':batchUpdate', 'POST', { requests: missing.map((title) => ({ addSheet: { properties: { title } } })) });
    for (const t of missing) {
      await api(token, sheetId, `/values/${t}!A1?valueInputOption=RAW`, 'PUT', { values: [TABS[t]] });
    }
  }
}

const append = (token, sheetId, tab, rows) => rows.length
  ? api(token, sheetId, `/values/${tab}!A1:append?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS`, 'POST', { values: rows })
  : null;

export async function syncNow() {
  const s = getSettings();
  if (s.sheets_enabled !== '1') return { ok: false, skipped: true, message: 'Google Sheet sync is turned off in Settings.' };
  if (!s.sheets_spreadsheet_id || !s.sheets_credentials_path) return { ok: false, message: 'Add the spreadsheet ID and credentials file path in Settings.' };

  const token = await accessToken(s.sheets_credentials_path);
  const id = s.sheets_spreadsheet_id;
  await ensureTabs(token, id);

  const orders = db.prepare('SELECT * FROM orders WHERE synced = 0 ORDER BY id LIMIT 500').all();
  const itemsFor = db.prepare('SELECT * FROM order_items WHERE order_id = ?');
  const orderRows = [], itemRows = [];
  for (const o of orders) {
    const items = itemsFor.all(o.id);
    const [d, t] = o.created_at.split(' ');
    orderRows.push([o.bill_no, d, t, items.map((i) => `${i.name} x${i.qty}`).join(', '), o.subtotal, o.discount, o.tax, o.total, o.payment_method, o.order_type, o.source, o.status, o.customer_name || '', o.customer_phone || '']);
    for (const i of items) itemRows.push([o.bill_no, d, t, i.name, i.category, i.price, i.qty, i.price * i.qty]);
  }
  await append(token, id, 'Orders', orderRows);
  await append(token, id, 'OrderItems', itemRows);
  if (orders.length) {
    const mark = db.prepare('UPDATE orders SET synced = 1 WHERE id = ?');
    for (const o of orders) mark.run(o.id);
  }

  const expenses = db.prepare('SELECT * FROM expenses WHERE synced = 0 ORDER BY id').all();
  await append(token, id, 'Expenses', expenses.map((e) => [e.date, e.category, e.amount, e.recurring ? 'Monthly' : 'One-off', e.note || '']));
  const markE = db.prepare('UPDATE expenses SET synced = 1 WHERE id = ?');
  for (const e of expenses) markE.run(e.id);

  // Daily summary for the last 90 days, rewritten each time.
  const from = fmtDate(addDays(new Date(), -89));
  const days = db.prepare(`SELECT substr(created_at,1,10) AS d, SUM(total) AS revenue, COUNT(*) AS orders FROM orders
    WHERE status='paid' AND created_at >= ? GROUP BY d ORDER BY d`).all(from);
  const topItem = db.prepare(`SELECT oi.name FROM order_items oi JOIN orders o ON o.id = oi.order_id
    WHERE o.status='paid' AND substr(o.created_at,1,10) = ? GROUP BY oi.name ORDER BY SUM(oi.qty) DESC LIMIT 1`);
  const daily = days.map((r) => [r.d, Math.round(r.revenue), r.orders, Math.round(r.revenue / r.orders), topItem.get(r.d)?.name || '']);
  await api(token, id, '/values/Daily!A2:E1000:clear', 'POST', {});
  if (daily.length) await api(token, id, `/values/Daily!A2?valueInputOption=USER_ENTERED`, 'PUT', { values: daily });

  const at = fmtDateTime(new Date());
  setSettings({ sheets_last_sync: at });
  return { ok: true, message: `Synced ${orders.length} orders and ${expenses.length} expenses.`, at };
}

export function startSyncLoop(intervalMs = 5 * 60_000) {
  const run = () => syncNow().catch((e) => console.warn('[sheets] sync failed:', e.message));
  setTimeout(run, 10_000);
  return setInterval(run, intervalMs);
}

if (process.argv[1] === fileURLToPath(import.meta.url) && process.argv.includes('--once')) {
  syncNow().then((r) => console.log(r.message)).catch((e) => { console.error(e.message); process.exit(1); });
}
