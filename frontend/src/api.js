// ---------- Admin session (PIN sign-in) ----------
// The bearer token lives in sessionStorage so it is forgotten when the browser closes.
// Storage can be blocked (private mode, kiosk policies); fall back to memory then.
const SESSION_KEY = 'wb-admin-session';
let memSession = null;
export const adminSession = {
  get() {
    let s = memSession;
    try { const raw = sessionStorage.getItem(SESSION_KEY); if (raw) s = JSON.parse(raw); } catch { /* storage blocked */ }
    if (s && s.token && Number(s.expires_at) * 1000 > Date.now()) return s;
    return null;
  },
  set(s) {
    memSession = s;
    try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(s)); } catch { /* storage blocked */ }
  },
  clear() {
    memSession = null;
    try { sessionStorage.removeItem(SESSION_KEY); } catch { /* storage blocked */ }
  },
};
export const SIGNED_OUT_EVENT = 'wb:admin-signed-out';

function authHeaders(withAuth) {
  if (!withAuth) return {};
  const s = adminSession.get();
  return s ? { Authorization: `Bearer ${s.token}` } : {};
}

function signedOut() {
  adminSession.clear();
  window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
}

async function req(method, url, body, withAuth = false) {
  const res = await fetch(url, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...authHeaders(withAuth) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && withAuth) signedOut();
    let msg = data.error || data.message;
    if (!msg && Array.isArray(data.detail)) msg = data.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
    const err = new Error(msg || (typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`));
    err.status = res.status;
    throw err;
  }
  return data;
}
export const api = {
  get: (u) => req('GET', u),
  post: (u, b) => req('POST', u, b || {}),
  put: (u, b) => req('PUT', u, b),
  del: (u) => req('DELETE', u),
};
// Same calls, but carrying the admin token. A 401 signs the admin out everywhere.
export const adminApi = {
  get: (u) => req('GET', u, undefined, true),
  post: (u, b) => req('POST', u, b || {}, true),
  put: (u, b) => req('PUT', u, b, true),
  del: (u) => req('DELETE', u, undefined, true),
};

// Same calls for counter actions that need the PIN (cancel a bill, expenses, targets): when
// nobody is signed in, or the token has expired, the PIN prompt opens and the call is retried.
export const PIN_NEEDED_EVENT = 'wb:pin-needed';
export function requirePin(reason) {
  return new Promise((resolve, reject) => {
    window.dispatchEvent(new CustomEvent(PIN_NEEDED_EVENT, { detail: { reason, resolve, reject } }));
  });
}
async function withPin(method, u, b, reason) {
  if (!adminSession.get()) await requirePin(reason);
  try {
    return await req(method, u, b, true);
  } catch (e) {
    if (e.status !== 401) throw e;
    await requirePin(reason);
    return req(method, u, b, true);
  }
}
export const pinApi = {
  post: (u, b, reason) => withPin('POST', u, b || {}, reason),
  put: (u, b, reason) => withPin('PUT', u, b, reason),
  del: (u, reason) => withPin('DELETE', u, undefined, reason),
};

// Fetches a protected plain-text resource (e.g. the Google Sheet setup script).
export async function adminText(url) {
  const res = await fetch(url, { headers: authHeaders(true) });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) signedOut();
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.text();
}

// Downloads a protected file (fetch with the token, then save the blob).
export async function adminDownload(url, fallbackName) {
  const res = await fetch(url, { headers: authHeaders(true) });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) signedOut();
    const err = new Error(data.error || `Download failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  const blob = await res.blob();
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  const name = m ? decodeURIComponent(m[1]) : fallbackName;
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export const inr = (n, dp = 0) => {
  const v = Number(n || 0);
  return (v < 0 ? '−₹' : '₹') + Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp });
};
export const inrShort = (n) => {
  n = Number(n || 0);
  if (n >= 1e5) return '₹' + (n / 1e5).toFixed(n % 1e5 === 0 ? 0 : 1) + 'L';
  if (n >= 1e3) return '₹' + (n / 1e3).toFixed(n % 1e3 === 0 ? 0 : 1) + 'k';
  return '₹' + Math.round(n);
};
// The shop's time zone (from GET /api/config). Dates and times on screen use it, not the tablet's
// own zone, so a tablet set to UTC still shows the same "today" as the reports.
let shopTimeZone = 'Asia/Kolkata';
export const setShopTimeZone = (tz) => {
  try { new Intl.DateTimeFormat('en-IN', { timeZone: tz }); shopTimeZone = tz; } catch { /* unknown zone: keep */ }
};
export const getShopTimeZone = () => shopTimeZone;
// YYYY-MM-DD in the shop's time zone ('en-CA' formats dates as ISO).
export const today = (d = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: shopTimeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
export const thisMonth = () => today().slice(0, 7);

// Category colours (validated for colour-blind separation) and item placeholders.
export const SERIES = ['#B97A10', '#7E4FB0', '#0092A0', '#D04A3A', '#5A6B7A'];
export const EMOJI = { Waffle: '🧇', 'Mini Waffle': '🍪', Bowl: '🥣', Snacks: '🥪', Combo: '🎁' };
