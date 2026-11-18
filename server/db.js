// SQLite storage using Node's built-in driver (no native build step needed).
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dataDir = process.env.WB_DATA_DIR || path.join(root, 'data');
mkdirSync(dataDir, { recursive: true });
export const DB_PATH = path.join(dataDir, 'waffle-bros.db');

export const db = new DatabaseSync(DB_PATH);
db.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;');

db.exec(`
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,            -- short id shown on the card, e.g. W01
  name TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  price REAL NOT NULL,
  cost REAL NOT NULL DEFAULT 0,         -- ingredient cost per unit, optional, for margin insights
  image TEXT,                           -- data URL or /images/... path
  veg INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  bill_no TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,             -- local time 'YYYY-MM-DD HH:MM:SS'
  subtotal REAL NOT NULL,
  discount REAL NOT NULL DEFAULT 0,
  tax REAL NOT NULL DEFAULT 0,
  total REAL NOT NULL,
  payment_method TEXT NOT NULL DEFAULT 'cash',   -- cash | upi | card
  order_type TEXT NOT NULL DEFAULT 'dine-in',    -- dine-in | takeaway | delivery
  source TEXT NOT NULL DEFAULT 'counter',        -- counter | whatsapp (phase 2)
  customer_name TEXT,
  customer_phone TEXT,
  delivery_address TEXT,                         -- phase 2: building / flat no.
  status TEXT NOT NULL DEFAULT 'paid',           -- paid | cancelled (later: pending, preparing for online orders)
  note TEXT,
  synced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES items(id),
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  price REAL NOT NULL,
  qty INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,                   -- 'YYYY-MM-DD'
  category TEXT NOT NULL,               -- rent, salary, ingredients, electricity, packaging, marketing, other
  amount REAL NOT NULL,
  note TEXT,
  recurring INTEGER NOT NULL DEFAULT 0, -- 1 = repeats every month (rent, salary)
  synced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS targets (
  month TEXT PRIMARY KEY,               -- 'YYYY-MM'
  amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);
`);

const DEFAULT_SETTINGS = {
  shop_name: 'Waffle Bros',
  shop_address: 'Bhopal',
  shop_phone: '',
  gstin: '',
  gst_rate: '0',             // percent; 5% is typical for restaurants once registered
  default_target: '100000',
  open_hour: '10',
  close_hour: '23',
  sheets_enabled: '0',
  sheets_spreadsheet_id: '',
  sheets_credentials_path: '',
  sheets_last_sync: '',
};
const insSetting = db.prepare('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)');
for (const [k, v] of Object.entries(DEFAULT_SETTINGS)) insSetting.run(k, v);

export function getSettings() {
  const rows = db.prepare('SELECT key, value FROM settings').all();
  return Object.fromEntries(rows.map((r) => [r.key, r.value]));
}
export function setSettings(obj) {
  const st = db.prepare('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value');
  for (const [k, v] of Object.entries(obj)) st.run(k, v == null ? '' : String(v));
}

export function tx(fn) {
  db.exec('BEGIN');
  try {
    const r = fn();
    db.exec('COMMIT');
    return r;
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
}

// Seed a starter menu the first time. Prices are placeholders; change them in Settings → Menu.
const count = db.prepare('SELECT COUNT(*) AS n FROM categories').get().n;
if (count === 0) {
  tx(() => {
    const cats = ['Waffle', 'Sandwich', 'Combo', 'Mini Waffle'];
    const insCat = db.prepare('INSERT INTO categories (name, sort) VALUES (?, ?)');
    const catId = {};
    cats.forEach((c, i) => { catId[c] = Number(insCat.run(c, i).lastInsertRowid); });
    const insItem = db.prepare('INSERT INTO items (code, name, category_id, price, cost, veg, sort) VALUES (?, ?, ?, ?, ?, 1, ?)');
    const menu = [
      ['W01', 'Classic Maple Butter', 'Waffle', 129, 40],
      ['W02', 'Dark Chocolate', 'Waffle', 149, 48],
      ['W03', 'Milk Chocolate', 'Waffle', 149, 46],
      ['W04', 'Triple Chocolate', 'Waffle', 189, 62],
      ['W05', 'Nutella', 'Waffle', 199, 70],
      ['W06', 'KitKat Crunch', 'Waffle', 189, 60],
      ['W07', 'Red Velvet Cream Cheese', 'Waffle', 199, 66],
      ['W08', 'Lotus Biscoff', 'Waffle', 219, 78],
      ['W09', 'Honey Banana', 'Waffle', 159, 45],
      ['S01', 'Veg Grilled Waffle Sandwich', 'Sandwich', 139, 42],
      ['S02', 'Paneer Tikka Waffle Sandwich', 'Sandwich', 169, 55],
      ['S03', 'Cheese Corn Waffle Sandwich', 'Sandwich', 149, 45],
      ['C01', 'Waffle + Cold Coffee', 'Combo', 229, 75],
      ['C02', 'Any 2 Waffles (Duo)', 'Combo', 299, 100],
      ['C03', 'Family Pack (4 Waffles)', 'Combo', 549, 190],
      ['M01', 'Mini Waffle Bites Chocolate (6 pc)', 'Mini Waffle', 99, 30],
      ['M02', 'Mini Waffle Bites Nutella (6 pc)', 'Mini Waffle', 129, 42],
      ['M03', 'Mini Pancake Bites (10 pc)', 'Mini Waffle', 109, 32],
    ];
    menu.forEach(([code, name, cat, price, cost], i) => insItem.run(code, name, catId[cat], price, cost, i));
  });
}
