// Dashboard card layout: which cards show, in what order, and how wide.
// Pure functions (no React, no DOM) so they can be tested with `node --test`.
// The layout is saved in this browser only (localStorage), so each device keeps its own.

export const LAYOUT_KEY = 'wb-dashboard-layout-v1';

// Widths are columns of the 12-column dashboard grid. Below 1100px wide every card is full width.
export const WIDTHS = [3, 4, 5, 6, 7, 8, 9, 12];

// The cards on the dashboard, in their default order and width.
export const CARDS = [
  { id: 'target', title: 'Monthly target', width: 12 },
  { id: 'sales', title: 'Sales charts', width: 8 },
  { id: 'insights', title: 'Insights', width: 4 },
  { id: 'calendar', title: 'Sales calendar', width: 12 },
  { id: 'items', title: "What's selling", width: 7 },
  { id: 'expenses', title: 'Expenses', width: 5 },
  { id: 'categories', title: 'Sales by category', width: 4 },
  { id: 'weekdays', title: 'Average sales by weekday', width: 4 },
  { id: 'payments', title: 'Payment methods', width: 4 },
];

const BY_ID = new Map(CARDS.map((c) => [c.id, c]));

/** The layout everyone starts with (and gets back from "Reset layout"). */
export function defaultLayout() {
  return {
    order: CARDS.map((c) => c.id),
    width: Object.fromEntries(CARDS.map((c) => [c.id, c.width])),
    hidden: [],
  };
}

/**
 * Turn whatever was stored into a valid layout. Unknown cards are dropped, cards added in a
 * later version are slotted in after the card they follow by default, widths that are not
 * allowed fall back to the default, and anything unreadable gives the default layout.
 */
export function sanitize(raw) {
  const base = defaultLayout();
  if (!raw || typeof raw !== 'object') return base;
  const seen = new Set();
  const order = (Array.isArray(raw.order) ? raw.order : []).filter((id) => {
    if (typeof id !== 'string' || !BY_ID.has(id) || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  if (!order.length) return base;
  // New cards go right after their default predecessor (or first, if that is missing too).
  base.order.forEach((id, i) => {
    if (seen.has(id)) return;
    const prev = base.order.slice(0, i).reverse().find((p) => order.includes(p));
    order.splice(prev ? order.indexOf(prev) + 1 : 0, 0, id);
    seen.add(id);
  });
  const width = { ...base.width };
  if (raw.width && typeof raw.width === 'object') {
    for (const id of order) if (WIDTHS.includes(raw.width[id])) width[id] = raw.width[id];
  }
  const hidden = Array.isArray(raw.hidden) ? [...new Set(raw.hidden.filter((id) => BY_ID.has(id)))] : [];
  // Never hide every card: an empty dashboard looks broken.
  return { order, width, hidden: hidden.length >= order.length ? [] : hidden };
}

/** Move a card from one place in the order to another. */
export function moveCard(layout, id, toIndex) {
  const from = layout.order.indexOf(id);
  if (from < 0) return layout;
  const to = Math.max(0, Math.min(layout.order.length - 1, toIndex));
  if (from === to) return layout;
  const order = [...layout.order];
  order.splice(from, 1);
  order.splice(to, 0, id);
  return { ...layout, order };
}

/** Put card `id` where card `overId` is (what a drag and drop does). */
export function dropCard(layout, id, overId) {
  if (!overId || id === overId) return layout;
  const to = layout.order.indexOf(overId);
  return to < 0 ? layout : moveCard(layout, id, to);
}

/** Make a card one step narrower (step -1) or wider (step +1). */
export function resizeCard(layout, id, step) {
  const cur = WIDTHS.indexOf(layout.width[id]);
  const next = WIDTHS[Math.max(0, Math.min(WIDTHS.length - 1, (cur < 0 ? WIDTHS.indexOf(12) : cur) + step))];
  return next === layout.width[id] ? layout : { ...layout, width: { ...layout.width, [id]: next } };
}

export function setHidden(layout, id, hide) {
  const hidden = layout.hidden.filter((h) => h !== id);
  if (hide) {
    if (hidden.length + 1 >= layout.order.length) return layout; // keep at least one card
    hidden.push(id);
  }
  return { ...layout, hidden };
}

export function isDefault(layout) {
  return JSON.stringify(sanitize(layout)) === JSON.stringify(defaultLayout());
}

/** "58%" style label for a width. */
export const widthLabel = (w) => (w === 12 ? 'Full' : `${Math.round((w / 12) * 100)}%`);

export const cardTitle = (id) => BY_ID.get(id)?.title ?? id;

// Storage can be blocked (private mode, kiosk policies): then the layout lasts until reload.
export function loadLayout(storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(LAYOUT_KEY);
    return sanitize(raw ? JSON.parse(raw) : null);
  } catch {
    return defaultLayout();
  }
}

export function saveLayout(layout, storage = globalThis.localStorage) {
  try {
    if (isDefault(layout)) storage?.removeItem(LAYOUT_KEY);
    else storage?.setItem(LAYOUT_KEY, JSON.stringify(layout));
    return true;
  } catch {
    return false;
  }
}
