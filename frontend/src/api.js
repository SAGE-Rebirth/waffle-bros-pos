async function req(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.message || `Request failed (${res.status})`);
  return data;
}
export const api = {
  get: (u) => req('GET', u),
  post: (u, b) => req('POST', u, b || {}),
  put: (u, b) => req('PUT', u, b),
  del: (u) => req('DELETE', u),
};

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
