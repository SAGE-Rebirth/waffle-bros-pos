import express from 'express';
import path from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import { networkInterfaces } from 'node:os';
import { fileURLToPath } from 'node:url';
import { db, tx, getSettings, setSettings, DB_PATH } from './db.js';
import { fmtDateTime, fmtDate, fmtMonth, addDays, parseDate } from './time.js';
import { targetSummary, charts, insights, itemStats, dayEnd, monthExpenses } from './analytics.js';
import { syncNow, startSyncLoop } from './sheets.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const app = express();
app.use(express.json({ limit: '5mb' })); // item images are stored as small data URLs

const bad = (res, msg, code = 400) => res.status(code).json({ error: msg });

// ---------- Menu ----------
app.get('/api/menu', (req, res) => {
  const categories = db.prepare('SELECT * FROM categories ORDER BY sort, id').all();
  const items = db.prepare(`SELECT i.*, c.name AS category FROM items i JOIN categories c ON c.id = i.category_id ORDER BY c.sort, i.sort, i.code`).all();
  res.json({ categories, items });
});

app.post('/api/categories', (req, res) => {
  const name = String(req.body.name || '').trim();
  if (!name) return bad(res, 'Category name is required');
  const sort = db.prepare('SELECT COALESCE(MAX(sort),0)+1 AS s FROM categories').get().s;
  try {
    const r = db.prepare('INSERT INTO categories (name, sort) VALUES (?, ?)').run(name, sort);
    res.json({ id: Number(r.lastInsertRowid) });
  } catch { bad(res, 'That category already exists'); }
});

function itemFields(b) {
  const f = {
    code: String(b.code || '').trim().toUpperCase(),
    name: String(b.name || '').trim(),
    category_id: Number(b.category_id),
    price: Number(b.price),
    cost: Number(b.cost || 0),
    image: b.image || null,
    veg: b.veg === false || b.veg === 0 ? 0 : 1,
    active: b.active === false || b.active === 0 ? 0 : 1,
  };
  if (!f.code || !f.name || !f.category_id || !(f.price >= 0)) throw new Error('Code, name, category and price are required');
  return f;
}

app.post('/api/items', (req, res) => {
  try {
    const f = itemFields(req.body);
    const r = db.prepare('INSERT INTO items (code, name, category_id, price, cost, image, veg, active) VALUES (?,?,?,?,?,?,?,?)')
      .run(f.code, f.name, f.category_id, f.price, f.cost, f.image, f.veg, f.active);
    res.json({ id: Number(r.lastInsertRowid) });
  } catch (e) { bad(res, e.message.includes('UNIQUE') ? 'That item ID is already used' : e.message); }
});

app.put('/api/items/:id', (req, res) => {
  try {
    const f = itemFields(req.body);
    db.prepare('UPDATE items SET code=?, name=?, category_id=?, price=?, cost=?, image=?, veg=?, active=? WHERE id=?')
      .run(f.code, f.name, f.category_id, f.price, f.cost, f.image, f.veg, f.active, Number(req.params.id));
    res.json({ ok: true });
  } catch (e) { bad(res, e.message.includes('UNIQUE') ? 'That item ID is already used' : e.message); }
});

app.delete('/api/items/:id', (req, res) => {
  // Items that were sold are hidden instead of deleted, so past bills stay intact.
  const id = Number(req.params.id);
  const used = db.prepare('SELECT 1 FROM order_items WHERE item_id = ? LIMIT 1').get(id);
  if (used) db.prepare('UPDATE items SET active = 0 WHERE id = ?').run(id);
  else db.prepare('DELETE FROM items WHERE id = ?').run(id);
  res.json({ ok: true, hidden: !!used });
});

// ---------- Orders ----------
function nextBillNo(now) {
  const d = fmtDate(now);
  const n = db.prepare('SELECT COUNT(*) AS n FROM orders WHERE substr(created_at,1,10) = ?').get(d).n + 1;
  return `WB${d.slice(2).replace(/-/g, '')}-${String(n).padStart(3, '0')}`;
}

export function createOrder(body, now = new Date()) {
  const lines = Array.isArray(body.items) ? body.items : [];
  if (!lines.length) throw new Error('The order is empty');
  const getItem = db.prepare('SELECT i.*, c.name AS category FROM items i JOIN categories c ON c.id = i.category_id WHERE i.id = ?');
  const resolved = lines.map((l) => {
    const it = getItem.get(Number(l.item_id));
    const qty = Math.max(1, Math.floor(Number(l.qty) || 1));
    if (!it) throw new Error(`Unknown item ${l.item_id}`);
    return { ...it, qty };
  });
  const subtotal = resolved.reduce((s, i) => s + i.price * i.qty, 0);
  const discount = Math.min(subtotal, Math.max(0, Number(body.discount) || 0));
  const gst = Number(getSettings().gst_rate || 0);
  const tax = Math.round((subtotal - discount) * gst) / 100;
  const total = Math.round((subtotal - discount + tax) * 100) / 100;
  return tx(() => {
    const bill = nextBillNo(now);
    const r = db.prepare(`INSERT INTO orders (bill_no, created_at, subtotal, discount, tax, total, payment_method, order_type, source,
      customer_name, customer_phone, delivery_address, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`).run(
      bill, fmtDateTime(now), subtotal, discount, tax, total,
      ['cash', 'upi', 'card'].includes(body.payment_method) ? body.payment_method : 'cash',
      ['dine-in', 'takeaway', 'delivery'].includes(body.order_type) ? body.order_type : 'dine-in',
      body.source === 'whatsapp' ? 'whatsapp' : 'counter',
      body.customer_name || null, body.customer_phone || null, body.delivery_address || null, body.note || null);
    const orderId = Number(r.lastInsertRowid);
    const ins = db.prepare('INSERT INTO order_items (order_id, item_id, name, category, price, qty) VALUES (?,?,?,?,?,?)');
    for (const i of resolved) ins.run(orderId, i.id, i.name, i.category, i.price, i.qty);
    return getOrder(orderId);
  });
}

function getOrder(id) {
  const o = db.prepare('SELECT * FROM orders WHERE id = ?').get(id);
  if (!o) return null;
  o.items = db.prepare('SELECT * FROM order_items WHERE order_id = ?').all(id);
  return o;
}

app.post('/api/orders', (req, res) => {
  try { res.json(createOrder(req.body)); } catch (e) { bad(res, e.message); }
});

app.get('/api/orders', (req, res) => {
  const date = req.query.date || fmtDate(new Date());
  const next = fmtDate(addDays(parseDate(date), 1));
  const orders = db.prepare('SELECT * FROM orders WHERE created_at >= ? AND created_at < ? ORDER BY id DESC').all(date, next);
  const itemsFor = db.prepare('SELECT name, qty, price FROM order_items WHERE order_id = ?');
  res.json(orders.map((o) => ({ ...o, items: itemsFor.all(o.id) })));
});

app.get('/api/orders/:id', (req, res) => {
  const o = getOrder(Number(req.params.id));
  return o ? res.json(o) : bad(res, 'Not found', 404);
});

app.post('/api/orders/:id/cancel', (req, res) => {
  db.prepare("UPDATE orders SET status = 'cancelled', synced = 0 WHERE id = ?").run(Number(req.params.id));
  res.json(getOrder(Number(req.params.id)));
});

// ---------- Dashboard ----------
app.get('/api/dashboard', (req, res) => {
  const now = new Date();
  res.json({
    target: targetSummary(now),
    charts: charts(now),
    insights: insights(now),
    items: itemStats(req.query.period || 'month', now),
  });
});
app.get('/api/items/stats', (req, res) => res.json(itemStats(req.query.period || 'month')));
app.get('/api/day-end', (req, res) => res.json(dayEnd(req.query.date)));

// ---------- Targets & expenses ----------
app.put('/api/targets/:month', (req, res) => {
  const amount = Number(req.body.amount);
  if (!/^\d{4}-\d{2}$/.test(req.params.month) || !(amount > 0)) return bad(res, 'Enter a valid target');
  db.prepare('INSERT INTO targets (month, amount) VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET amount = excluded.amount').run(req.params.month, amount);
  if (req.body.makeDefault) setSettings({ default_target: amount });
  res.json({ ok: true });
});

app.get('/api/expenses', (req, res) => res.json(monthExpenses(req.query.month || fmtMonth(new Date()))));
app.post('/api/expenses', (req, res) => {
  const amount = Number(req.body.amount);
  const category = String(req.body.category || '').trim().toLowerCase();
  const date = req.body.date || fmtDate(new Date());
  if (!(amount > 0) || !category) return bad(res, 'Amount and category are required');
  const r = db.prepare('INSERT INTO expenses (date, category, amount, note, recurring) VALUES (?,?,?,?,?)')
    .run(date, category, amount, req.body.note || null, req.body.recurring ? 1 : 0);
  res.json({ id: Number(r.lastInsertRowid) });
});
app.delete('/api/expenses/:id', (req, res) => {
  db.prepare('DELETE FROM expenses WHERE id = ?').run(Number(req.params.id));
  res.json({ ok: true });
});

// ---------- Settings, sync, backup ----------
app.get('/api/settings', (req, res) => res.json(getSettings()));
app.put('/api/settings', (req, res) => {
  const allowed = ['shop_name', 'shop_address', 'shop_phone', 'gstin', 'gst_rate', 'default_target', 'open_hour', 'close_hour',
    'sheets_enabled', 'sheets_spreadsheet_id', 'sheets_credentials_path'];
  setSettings(Object.fromEntries(Object.entries(req.body).filter(([k]) => allowed.includes(k))));
  res.json(getSettings());
});
app.post('/api/sync', async (req, res) => {
  try { res.json(await syncNow()); } catch (e) { res.status(500).json({ ok: false, message: e.message }); }
});
app.get('/api/backup', (req, res) => {
  db.exec('PRAGMA wal_checkpoint(FULL)');
  res.setHeader('Content-Disposition', `attachment; filename="waffle-bros-backup-${fmtDate(new Date())}.db"`);
  res.type('application/octet-stream').send(readFileSync(DB_PATH));
});

// ---------- Phase 2 placeholder: WhatsApp orders ----------
// A WhatsApp Business webhook will POST here; orders are created with source = 'whatsapp'.
app.post('/api/integrations/whatsapp', (req, res) => bad(res, 'WhatsApp ordering is planned for phase 2', 501));

// ---------- Front end ----------
const dist = path.join(root, 'client', 'dist');
if (existsSync(dist)) {
  app.use(express.static(dist));
  app.get(/^\/(?!api\/).*/, (req, res) => res.sendFile(path.join(dist, 'index.html')));
} else {
  app.get('/', (req, res) => res.send('Front end not built yet. Run <code>npm run build</code>, or use <code>npm run dev</code> while developing.'));
}

app.use((err, req, res, next) => { console.error(err); bad(res, err.message || 'Server error', 500); });

const PORT = Number(process.env.PORT || 4000);
if (process.env.WB_NO_LISTEN !== '1') {
  app.listen(PORT, '0.0.0.0', () => {
    const lan = Object.values(networkInterfaces()).flat().find((i) => i && i.family === 'IPv4' && !i.internal)?.address;
    console.log(`\n  🧇 Waffle Bros POS is running\n  On this computer:   http://localhost:${PORT}`);
    if (lan) console.log(`  On the shop Wi-Fi:  http://${lan}:${PORT}  (tablet / phone)`);
    console.log(`  Data file:          ${DB_PATH}\n`);
  });
  startSyncLoop();
}

export default app;
