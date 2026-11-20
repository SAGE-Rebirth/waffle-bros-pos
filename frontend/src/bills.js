// Pure helpers for the Bills page (no React, no fetch) so they can be unit-tested with node --test.

// "Nutella Waffle ×2, Corn Sandwich ×1" for the first `max` lines, and how many lines are left over.
export function itemsSummary(items, max = 3) {
  const shown = items.slice(0, max).map((i) => `${i.name} ×${i.qty}`).join(', ');
  return { text: shown, more: Math.max(0, items.length - max), qty: items.reduce((n, i) => n + i.qty, 0) };
}

// Page buttons: always the first and last page, a few around the current one, '…' for gaps.
export function pageWindow(page, pages, around = 1) {
  const out = [];
  for (let p = 1; p <= pages; p += 1) {
    if (p === 1 || p === pages || Math.abs(p - page) <= around) out.push(p);
    else if (out[out.length - 1] !== '…') out.push('…');
  }
  return out;
}

const addDays = (iso, n) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

// Quick date ranges, from the shop's today (YYYY-MM-DD). '' means no limit.
export const RANGES = [
  ['today', 'Today'],
  ['yesterday', 'Yesterday'],
  ['7d', 'Last 7 days'],
  ['month', 'This month'],
  ['all', 'All time'],
];
export function rangeFor(key, today) {
  switch (key) {
    case 'today': return { from: today, to: today };
    case 'yesterday': { const y = addDays(today, -1); return { from: y, to: y }; }
    case '7d': return { from: addDays(today, -6), to: today };
    case 'month': return { from: `${today.slice(0, 8)}01`, to: today };
    default: return { from: '', to: '' };
  }
}
// Which quick range (if any) a from/to pair is, so its button can light up.
export function rangeKey(from, to, today) {
  return RANGES.map(([k]) => k).find((k) => { const r = rangeFor(k, today); return r.from === from && r.to === to; }) || 'custom';
}

// The page's filters <-> the query string after #bills? (also what GET /api/bills takes).
export const DEFAULT_FILTERS = { from: '', to: '', q: '', status: 'all', payment: '', page: 1, size: 25 };
const ISO = /^\d{4}-\d{2}-\d{2}$/;
export function parseFilters(query, today) {
  const p = new URLSearchParams(query);
  const day = (k) => (ISO.test(p.get(k) || '') ? p.get(k) : '');
  const f = { ...DEFAULT_FILTERS, ...rangeFor('today', today) };
  if (p.has('from') || p.has('to')) { f.from = day('from'); f.to = day('to'); }
  f.q = (p.get('q') || '').slice(0, 40);
  if (['paid', 'cancelled'].includes(p.get('status'))) f.status = p.get('status');
  if (['cash', 'upi', 'card'].includes(p.get('payment'))) f.payment = p.get('payment');
  const page = Number.parseInt(p.get('page') || '1', 10);
  f.page = Number.isFinite(page) && page > 0 ? page : 1;
  const size = Number.parseInt(p.get('size') || '25', 10);
  f.size = [25, 50, 100].includes(size) ? size : 25;
  return f;
}
// Hash query: from/to are always written (an empty value means "no limit", unlike a missing one).
export function filtersQuery(f) {
  const p = new URLSearchParams({ from: f.from, to: f.to });
  if (f.q.trim()) p.set('q', f.q.trim());
  if (f.status !== 'all') p.set('status', f.status);
  if (f.payment) p.set('payment', f.payment);
  if (f.page > 1) p.set('page', String(f.page));
  if (f.size !== 25) p.set('size', String(f.size));
  return p.toString();
}
// The API query: the same filters, with empty ones left out.
export function apiQuery(f) {
  const p = new URLSearchParams();
  if (f.from) p.set('from', f.from);
  if (f.to) p.set('to', f.to);
  if (f.q.trim()) p.set('q', f.q.trim());
  if (f.status !== 'all') p.set('status', f.status);
  if (f.payment) p.set('payment', f.payment);
  p.set('page', String(f.page));
  p.set('page_size', String(f.size));
  return p.toString();
}
