import { db, getSettings } from './db.js';
import { fmtDate, fmtMonth, daysInMonth, addDays, startOfWeek, parseDate } from './time.js';

const PAID = "o.status = 'paid'";
const round = (n) => Math.round((n + Number.EPSILON) * 100) / 100;
const inr = (n) => '₹' + Math.round(n).toLocaleString('en-IN');

export function getTarget(month) {
  const row = db.prepare('SELECT amount FROM targets WHERE month = ?').get(month);
  if (row) return row.amount;
  return Number(getSettings().default_target || 0);
}

function revenueBetween(from, toExclusive) {
  return db.prepare(`SELECT COALESCE(SUM(total),0) AS revenue, COUNT(*) AS orders FROM orders o
    WHERE ${PAID} AND created_at >= ? AND created_at < ?`).get(from, toExclusive);
}

export function monthExpenses(month) {
  const [y, m] = month.split('-').map(Number);
  const start = `${month}-01`;
  const end = fmtDate(new Date(y, m, 1)); // first of next month
  const oneOff = db.prepare('SELECT * FROM expenses WHERE recurring = 0 AND date >= ? AND date < ? ORDER BY date DESC, id DESC').all(start, end);
  // Recurring expenses (rent, salaries) count in every month from the month they were added.
  const recurring = db.prepare('SELECT * FROM expenses WHERE recurring = 1 AND date < ? ORDER BY date DESC, id DESC').all(end);
  const all = [...recurring, ...oneOff];
  const byCat = {};
  for (const e of all) byCat[e.category] = (byCat[e.category] || 0) + e.amount;
  const sum = (arr) => arr.reduce((s, e) => s + e.amount, 0);
  return {
    total: round(sum(all)),
    recurringTotal: round(sum(recurring)),
    oneOffTotal: round(sum(oneOff)),
    byCategory: Object.entries(byCat).map(([category, amount]) => ({ category, amount: round(amount) })).sort((a, b) => b.amount - a.amount),
    recurring,
    oneOff,
  };
}

function periodRange(period, now) {
  const today = fmtDate(now);
  const tomorrow = fmtDate(addDays(now, 1));
  switch (period) {
    case 'today': return [today, tomorrow];
    case 'week': return [fmtDate(addDays(now, -6)), tomorrow];
    case 'month': return [`${fmtMonth(now)}-01`, tomorrow];
    case '30d': return [fmtDate(addDays(now, -29)), tomorrow];
    default: return ['0000-00-00', tomorrow];
  }
}

export function itemStats(period = 'month', now = new Date()) {
  const [from, to] = periodRange(period, now);
  const rows = db.prepare(`
    SELECT i.id, i.code, i.name, c.name AS category, i.price, i.cost, i.active,
      COALESCE(s.qty,0) AS qty, COALESCE(s.orders,0) AS orders, COALESCE(s.revenue,0) AS revenue
    FROM items i JOIN categories c ON c.id = i.category_id
    LEFT JOIN (
      SELECT oi.item_id, SUM(oi.qty) AS qty, COUNT(DISTINCT oi.order_id) AS orders, SUM(oi.qty * oi.price) AS revenue
      FROM order_items oi JOIN orders o ON o.id = oi.order_id
      WHERE ${PAID} AND o.created_at >= ? AND o.created_at < ?
      GROUP BY oi.item_id
    ) s ON s.item_id = i.id
    ORDER BY revenue DESC, qty DESC`).all(from, to);
  const totalRevenue = rows.reduce((s, r) => s + r.revenue, 0);
  const items = rows.map((r) => ({
    ...r,
    revenue: round(r.revenue),
    share: totalRevenue ? round((r.revenue / totalRevenue) * 100) : 0,
    margin: r.cost > 0 ? round(((r.price - r.cost) / r.price) * 100) : null,
  }));
  const sold = items.filter((r) => r.qty > 0);
  const by = (k) => [...sold].sort((a, b) => b[k] - a[k]);
  return {
    period, from, to,
    items,
    bestSeller: by('revenue')[0] || null,       // most money earned
    mostPopular: by('qty')[0] || null,          // most units sold
    customerFavourite: by('orders')[0] || null, // appears in the most separate orders
    topByRevenue: by('revenue').slice(0, 5),
    topByQty: by('qty').slice(0, 5),
    slowMovers: items.filter((r) => r.active).sort((a, b) => a.qty - b.qty || a.revenue - b.revenue).slice(0, 5),
  };
}

export function charts(now = new Date()) {
  const today = fmtDate(now);
  const month = fmtMonth(now);
  const y = now.getFullYear(), m0 = now.getMonth();
  const dim = daysInMonth(y, m0);
  const target = getTarget(month);

  // Hourly: today vs the average of the previous 28 days, per hour.
  const todayHours = db.prepare(`SELECT CAST(substr(created_at,12,2) AS INTEGER) AS h, SUM(total) AS revenue, COUNT(*) AS orders
    FROM orders o WHERE ${PAID} AND created_at >= ? AND created_at < ? GROUP BY h`).all(today, fmtDate(addDays(now, 1)));
  const histFrom = fmtDate(addDays(now, -28));
  const histDays = db.prepare(`SELECT COUNT(DISTINCT substr(created_at,1,10)) AS n FROM orders o WHERE ${PAID} AND created_at >= ? AND created_at < ?`).get(histFrom, today).n || 0;
  const avgHours = db.prepare(`SELECT CAST(substr(created_at,12,2) AS INTEGER) AS h, SUM(total) AS revenue, COUNT(*) AS orders
    FROM orders o WHERE ${PAID} AND created_at >= ? AND created_at < ? GROUP BY h`).all(histFrom, today);
  const s = getSettings();
  const open = Number(s.open_hour || 10), close = Number(s.close_hour || 23);
  const hourly = [];
  for (let h = Math.min(open, ...todayHours.map((r) => r.h)); h <= Math.max(close, ...todayHours.map((r) => r.h)); h++) {
    const t = todayHours.find((r) => r.h === h);
    const a = avgHours.find((r) => r.h === h);
    hourly.push({
      hour: h, label: `${((h + 11) % 12) + 1}${h < 12 ? 'am' : 'pm'}`,
      today: round(t?.revenue || 0), todayOrders: t?.orders || 0,
      average: histDays ? round((a?.revenue || 0) / histDays) : 0,
      avgOrders: histDays ? round((a?.orders || 0) / histDays) : 0,
    });
  }

  // Daily: this month, with the even-pace line and the running total vs target.
  const dayRows = db.prepare(`SELECT substr(created_at,1,10) AS d, SUM(total) AS revenue, COUNT(*) AS orders
    FROM orders o WHERE ${PAID} AND created_at >= ? AND created_at < ? GROUP BY d`).all(`${month}-01`, fmtDate(new Date(y, m0 + 1, 1)));
  const daily = [];
  let cum = 0;
  for (let d = 1; d <= dim; d++) {
    const key = `${month}-${String(d).padStart(2, '0')}`;
    const r = dayRows.find((x) => x.d === key);
    const future = key > today;
    if (!future) cum += r?.revenue || 0;
    daily.push({
      day: d, date: key,
      revenue: future ? null : round(r?.revenue || 0),
      orders: future ? null : r?.orders || 0,
      cumulative: future ? null : round(cum),
      pace: round((target / dim) * d),
      dailyTarget: round(target / dim),
    });
  }

  // Weekly: last 12 weeks (Mon–Sun).
  const weekly = [];
  const thisWeek = startOfWeek(now);
  for (let i = 11; i >= 0; i--) {
    const ws = addDays(thisWeek, -7 * i);
    const r = revenueBetween(fmtDate(ws), fmtDate(addDays(ws, 7)));
    weekly.push({ week: ws.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }), start: fmtDate(ws), revenue: round(r.revenue), orders: r.orders });
  }

  // Monthly: last 12 months with their targets.
  const monthly = [];
  for (let i = 11; i >= 0; i--) {
    const ms = new Date(y, m0 - i, 1);
    const key = fmtMonth(ms);
    const r = revenueBetween(`${key}-01`, fmtDate(new Date(ms.getFullYear(), ms.getMonth() + 1, 1)));
    monthly.push({ month: ms.toLocaleDateString('en-IN', { month: 'short', year: '2-digit' }), key, revenue: round(r.revenue), orders: r.orders, target: getTarget(key), expenses: monthExpenses(key).total });
  }

  // Category and payment split for this month.
  const categorySplit = db.prepare(`SELECT oi.category AS name, SUM(oi.qty*oi.price) AS value, SUM(oi.qty) AS qty
    FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE ${PAID} AND o.created_at >= ? GROUP BY oi.category ORDER BY value DESC`).all(`${month}-01`)
    .map((r) => ({ ...r, value: round(r.value) }));
  const paymentSplit = db.prepare(`SELECT payment_method AS name, SUM(total) AS value, COUNT(*) AS orders FROM orders o
    WHERE ${PAID} AND created_at >= ? GROUP BY payment_method ORDER BY value DESC`).all(`${month}-01`).map((r) => ({ ...r, value: round(r.value) }));

  // Average revenue by weekday over the last 8 weeks.
  const wdRows = db.prepare(`SELECT substr(created_at,1,10) AS d, SUM(total) AS revenue FROM orders o
    WHERE ${PAID} AND created_at >= ? AND created_at < ? GROUP BY d`).all(fmtDate(addDays(now, -56)), today);
  const names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const wd = names.map((n) => ({ day: n, total: 0, days: 0 }));
  for (const r of wdRows) { const w = parseDate(r.d).getDay(); wd[w].total += r.revenue; wd[w].days++; }
  const weekday = [1, 2, 3, 4, 5, 6, 0].map((i) => ({ day: names[i], average: wd[i].days ? round(wd[i].total / wd[i].days) : 0 }));

  return { hourly, daily, weekly, monthly, categorySplit, paymentSplit, weekday };
}

export function targetSummary(now = new Date()) {
  const month = fmtMonth(now);
  const today = fmtDate(now);
  const y = now.getFullYear(), m0 = now.getMonth();
  const dim = daysInMonth(y, m0);
  const dayOfMonth = now.getDate();
  const daysLeft = dim - dayOfMonth + 1; // including today
  const target = getTarget(month);

  const mtd = revenueBetween(`${month}-01`, fmtDate(addDays(now, 1)));
  const beforeToday = revenueBetween(`${month}-01`, today);
  const todayR = revenueBetween(today, fmtDate(addDays(now, 1)));

  const remaining = Math.max(0, target - mtd.revenue);
  const neededTodayFromStart = Math.max(0, (target - beforeToday.revenue) / daysLeft); // fixed for the whole day
  const requiredDailyAfterToday = daysLeft > 1 ? Math.max(0, (target - mtd.revenue) / (daysLeft - 1)) : remaining;
  // Count trading days from the first sale this month, so a mid-month opening isn't averaged over empty days.
  const first = db.prepare(`SELECT MIN(substr(created_at,1,10)) AS d FROM orders o WHERE ${PAID} AND created_at >= ?`).get(`${month}-01`).d;
  const completedDays = first && first < today ? Math.round((parseDate(today) - parseDate(first)) / 864e5) : 0;
  const avgDaily = completedDays > 0 ? beforeToday.revenue / completedDays : todayR.revenue;
  const projected = beforeToday.revenue + avgDaily * daysLeft;
  const aov = mtd.orders ? mtd.revenue / mtd.orders : 0;
  const expenses = monthExpenses(month);

  return {
    month, target, daysInMonth: dim, dayOfMonth, daysLeft,
    revenue: round(mtd.revenue), orders: mtd.orders,
    progressPct: target ? round((mtd.revenue / target) * 100) : 0,
    expectedPct: round((dayOfMonth / dim) * 100), // where an even pace would put you by end of today
    remaining: round(remaining),
    evenDailyTarget: round(target / dim),
    todayTarget: round(neededTodayFromStart),
    todayRevenue: round(todayR.revenue), todayOrders: todayR.orders,
    todayPct: neededTodayFromStart ? round((todayR.revenue / neededTodayFromStart) * 100) : 100,
    todayRemaining: round(Math.max(0, neededTodayFromStart - todayR.revenue)),
    requiredDailyFromTomorrow: round(requiredDailyAfterToday),
    avgDaily: round(avgDaily),
    projected: round(projected),
    aov: round(aov),
    ordersNeededToday: aov ? Math.ceil(Math.max(0, neededTodayFromStart - todayR.revenue) / aov) : null,
    expenses: { total: expenses.total, recurringTotal: expenses.recurringTotal, oneOffTotal: expenses.oneOffTotal, byCategory: expenses.byCategory },
    netProfit: round(mtd.revenue - expenses.total),
    breakEvenDaily: round(expenses.total / dim),
    // Revenue needed per day for the rest of the month to cover all logged expenses.
    breakEvenRemainingDaily: round(Math.max(0, expenses.total - mtd.revenue) / daysLeft),
  };
}

export function insights(now = new Date()) {
  const t = targetSummary(now);
  const c = charts(now);
  const it = itemStats('30d', now);
  const out = [];
  const add = (tone, title, text) => out.push({ tone, title, text });

  if (t.revenue === 0 && t.orders === 0) {
    add('info', 'No sales yet this month', `Your target is ${inr(t.target)}. That is ${inr(t.evenDailyTarget)} a day at an even pace. Bill your first order to start tracking.`);
    return out;
  }

  // 1. Target pace
  const gap = t.projected - t.target;
  if (gap >= 0) add('good', 'On track for the monthly target', `At your current average of ${inr(t.avgDaily)}/day you'll finish around ${inr(t.projected)}, ${inr(gap)} above the ${inr(t.target)} target.`);
  else add('warn', 'Behind the monthly target', `At ${inr(t.avgDaily)}/day you'll finish around ${inr(t.projected)}, ${inr(-gap)} short. You need ${inr(t.requiredDailyFromTomorrow)}/day from tomorrow (vs ${inr(t.evenDailyTarget)} at an even pace).`);

  // 2. Today
  if (t.remaining <= 0) {
    add('good', 'Monthly target reached', `${inr(t.revenue)} so far against ${inr(t.target)}. Consider raising next month's target to around ${inr(Math.round(t.projected / 5000) * 5000)}.`);
  } else if (t.todayRemaining > 0) {
    add('info', "Today's goal", `${inr(t.todayRevenue)} of ${inr(t.todayTarget)} done. ${inr(t.todayRemaining)} to go${t.ordersNeededToday ? `, about ${t.ordersNeededToday} more orders at your average bill of ${inr(t.aov)}` : ''}.`);
  } else {
    add('good', "Today's goal reached", `${inr(t.todayRevenue)} today against a goal of ${inr(t.todayTarget)}. Every extra rupee lowers tomorrow's target.`);
  }

  // 3. Average order value
  if (t.aov > 0) {
    const plus20 = t.orders * 20 * (t.daysInMonth / t.dayOfMonth);
    add('info', `Average bill ${inr(t.aov)}`, `Adding ₹20 to the average bill (an add-on topping, a drink in a combo) would bring in roughly ${inr(plus20)} more this month without any new customers.`);
  }

  // 4. Expenses and profit
  if (t.expenses.total > 0) {
    const pct = t.revenue ? (t.expenses.total / t.revenue) * 100 : 0;
    if (t.netProfit < 0) add('warn', 'Not covering expenses yet', `Expenses this month are ${inr(t.expenses.total)} against ${inr(t.revenue)} in sales. Break-even needs ${inr(t.breakEvenRemainingDaily)}/day for the rest of the month.`);
    else add(pct > 70 ? 'warn' : 'good', `Net so far ${inr(t.netProfit)}`, `Expenses are ${Math.round(pct)}% of sales (${inr(t.expenses.total)}). Your daily break-even is ${inr(t.breakEvenDaily)}.`);
    const top = t.expenses.byCategory[0];
    if (top) add('info', `Biggest cost: ${top.category[0].toUpperCase() + top.category.slice(1)}`, `${inr(top.amount)} this month, ${Math.round((top.amount / t.expenses.total) * 100)}% of all expenses.`);
  } else {
    add('info', 'Add your expenses', 'Enter rent, salaries, ingredients and bills on the Dashboard so profit and break-even can be worked out.');
  }

  // 5. Peak and quiet hours (from the 28-day average)
  const hrs = c.hourly.filter((h) => h.average > 0);
  if (hrs.length >= 3) {
    const peak = [...hrs].sort((a, b) => b.average - a.average)[0];
    const quiet = [...hrs].sort((a, b) => a.average - b.average)[0];
    add('info', `Busiest hour: ${peak.label}`, `Averages ${inr(peak.average)}. Keep batter and toppings prepped before then. Quietest is ${quiet.label} (${inr(quiet.average)}), a good slot for a happy-hour offer or mini-waffle deal.`);
  }

  // 6. Best weekday
  const wds = c.weekday.filter((w) => w.average > 0);
  if (wds.length >= 4) {
    const best = [...wds].sort((a, b) => b.average - a.average)[0];
    const worst = [...wds].sort((a, b) => a.average - b.average)[0];
    add('info', `${best.day} is your strongest day`, `Averages ${inr(best.average)} vs ${inr(worst.average)} on ${worst.day}. Try a ${worst.day}-only offer for the apartment residents.`);
  }

  // 7. Menu
  if (it.bestSeller) add('good', `Best seller: ${it.bestSeller.name}`, `${inr(it.bestSeller.revenue)} from ${it.bestSeller.qty} sold in the last 30 days (${it.bestSeller.share}% of item sales). Keep it front and centre on the menu board.`);
  const dead = it.slowMovers.filter((s) => s.qty <= Math.max(2, (it.mostPopular?.qty || 0) * 0.05));
  if (dead.length) add('warn', 'Slow movers', `${dead.map((d) => `${d.name} (${d.qty})`).join(', ')} sold the least in 30 days. Consider dropping them, folding them into a combo, or renaming them.`);
  const lowMargin = it.items.filter((i) => i.qty > 0 && i.margin != null && i.margin < 55).sort((a, b) => b.qty - a.qty)[0];
  if (lowMargin) add('warn', `Thin margin on ${lowMargin.name}`, `Only ${lowMargin.margin}% margin on a popular item. A ₹10–20 price change or smaller topping portion would help.`);

  return out;
}

export function dayEnd(dateStr, now = new Date()) {
  const date = dateStr || fmtDate(now);
  const next = fmtDate(addDays(parseDate(date), 1));
  const r = revenueBetween(date, next);
  const items = db.prepare(`SELECT oi.name, oi.category, SUM(oi.qty) AS qty, SUM(oi.qty*oi.price) AS revenue, COUNT(DISTINCT oi.order_id) AS orders
    FROM order_items oi JOIN orders o ON o.id = oi.order_id WHERE ${PAID} AND o.created_at >= ? AND o.created_at < ?
    GROUP BY oi.name, oi.category ORDER BY revenue DESC`).all(date, next);
  const notSold = db.prepare(`SELECT i.name, c.name AS category FROM items i JOIN categories c ON c.id = i.category_id
    WHERE i.active = 1 AND i.id NOT IN (SELECT oi.item_id FROM order_items oi JOIN orders o ON o.id = oi.order_id
      WHERE ${PAID} AND o.created_at >= ? AND o.created_at < ? AND oi.item_id IS NOT NULL)`).all(date, next);
  const payments = db.prepare(`SELECT payment_method AS method, SUM(total) AS amount, COUNT(*) AS orders FROM orders o
    WHERE ${PAID} AND created_at >= ? AND created_at < ? GROUP BY payment_method`).all(date, next);
  const cancelled = db.prepare(`SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS amount FROM orders WHERE status='cancelled' AND created_at >= ? AND created_at < ?`).get(date, next);
  return { date, revenue: round(r.revenue), orders: r.orders, aov: r.orders ? round(r.revenue / r.orders) : 0, items, notSold, payments, cancelled };
}
