// Fills a SEPARATE demo database (data-demo/) with ~6 weeks of made-up sales so
// you can see the dashboard working. Your real data in data/ is never touched.
//   npm run demo         -> create demo data
//   npm run start:demo   -> run the POS against the demo data
import path from 'node:path';
import { rmSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.env.WB_DATA_DIR ||= path.join(root, 'data-demo');
rmSync(process.env.WB_DATA_DIR, { recursive: true, force: true });
process.env.WB_NO_LISTEN = '1';

const { db } = await import('./db.js');
const { createOrder } = await import('./index.js');
const { fmtDate } = await import('./time.js');

let seed = 42;
const rand = () => ((seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296);
const pick = (weighted) => { let r = rand() * weighted.reduce((s, w) => s + w[1], 0); for (const [v, w] of weighted) { if ((r -= w) <= 0) return v; } return weighted[0][0]; };

const items = db.prepare('SELECT id, code FROM items').all();
const popularity = { W01: 6, W02: 9, W03: 7, W04: 8, W05: 12, W06: 7, W07: 4, W08: 6, W09: 1, S01: 3, S02: 5, S03: 2, C01: 6, C02: 4, C03: 2, M01: 6, M02: 5, M03: 0.6 };
const weightedItems = items.map((i) => [i.id, popularity[i.code] ?? 1]);
const hourWeights = [[10, 1], [11, 2], [12, 3], [13, 3], [14, 2], [15, 2], [16, 4], [17, 6], [18, 8], [19, 10], [20, 10], [21, 8], [22, 5]];

const now = new Date();
const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
let orders = 0;
for (let d = new Date(start); d <= now; d.setDate(d.getDate() + 1)) {
  const wd = d.getDay();
  const isToday = fmtDate(d) === fmtDate(now);
  let n = Math.round((wd === 0 || wd === 6 ? 13 : wd === 5 ? 10 : 7) * (0.8 + rand() * 0.4) * (1 + (d - start) / 864e5 / 120));
  for (let k = 0; k < n; k++) {
    const h = pick(hourWeights);
    const t = new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, Math.floor(rand() * 60), Math.floor(rand() * 60));
    if (isToday && t > now) continue;
    const lines = [];
    const count = pick([[1, 6], [2, 3], [3, 1]]);
    for (let j = 0; j < count; j++) lines.push({ item_id: pick(weightedItems), qty: pick([[1, 8], [2, 2]]) });
    createOrder({ items: lines, payment_method: pick([['upi', 7], ['cash', 3], ['card', 0.5]]), order_type: pick([['dine-in', 5], ['takeaway', 5]]), discount: rand() < 0.05 ? 20 : 0 }, t);
    orders++;
  }
}

const ins = db.prepare('INSERT INTO expenses (date, category, amount, note, recurring) VALUES (?,?,?,?,?)');
const first = fmtDate(start);
ins.run(first, 'rent', 25000, 'Shop rent', 1);
ins.run(first, 'salary', 24000, '2 staff', 1);
ins.run(first, 'electricity', 3500, 'Approx. monthly bill', 1);
for (let w = new Date(start); w <= now; w.setDate(w.getDate() + 7)) {
  ins.run(fmtDate(w), 'ingredients', Math.round(9000 + rand() * 3000), 'Weekly stock', 0);
  if (rand() < 0.5) ins.run(fmtDate(w), 'packaging', Math.round(1200 + rand() * 800), 'Boxes, forks, tissues', 0);
}
ins.run(fmtDate(new Date(now.getFullYear(), now.getMonth(), 2)), 'marketing', 3000, 'Flyers in the apartment complex', 0);

console.log(`Demo data ready: ${orders} orders since ${first} in ${process.env.WB_DATA_DIR}`);
console.log('Run "npm run start:demo" to open the POS with this data.');
