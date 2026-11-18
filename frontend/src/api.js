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
export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
export const thisMonth = () => today().slice(0, 7);

// Category colours (validated for colour-blind separation) and item placeholders.
export const SERIES = ['#B97A10', '#7E4FB0', '#0092A0', '#D04A3A'];
export const EMOJI = { Waffle: '🧇', Sandwich: '🥪', Combo: '🥤', 'Mini Waffle': '🍪' };
