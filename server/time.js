// All timestamps are stored in the shop computer's local time, which keeps
// "today", "this hour" and "this month" simple to query.
const pad = (n) => String(n).padStart(2, '0');

export const fmtDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const fmtDateTime = (d) => `${fmtDate(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
export const fmtMonth = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
export const daysInMonth = (y, m0) => new Date(y, m0 + 1, 0).getDate();
export const parseDate = (s) => {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, m - 1, d || 1);
};
export const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const startOfWeek = (d) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); const wd = (x.getDay() + 6) % 7; return addDays(x, -wd); }; // Monday
