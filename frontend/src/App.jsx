import { useEffect, useState, useCallback } from 'react';
import { api, inr } from './api.js';
import Billing from './pages/Billing.jsx';
import Dashboard from './pages/Dashboard.jsx';
import DayEnd from './pages/DayEnd.jsx';
import Admin from './pages/Admin.jsx';
import { useConfig } from './config.jsx';

export const Logo = () => (
  <svg viewBox="0 0 64 64" aria-hidden="true">
    <rect x="4" y="4" width="56" height="56" rx="14" style={{ fill: 'var(--yellow)' }} />
    <g style={{ stroke: 'var(--choc)' }} strokeWidth="4" strokeLinecap="round" fill="none">
      <path d="M22 14v36M32 14v36M42 14v36M14 22h36M14 32h36M14 42h36" />
    </g>
  </svg>
);

const PAGES = [
  ['billing', 'Billing'],
  ['dashboard', 'Dashboard'],
  ['dayend', 'Day End'],
  ['admin', 'Admin'],
];

// Old links (#settings) land on the admin dashboard.
const ALIASES = { settings: 'admin' };
const pageFromHash = () => {
  const h = location.hash.slice(1);
  const p = ALIASES[h] || h;
  return PAGES.some(([k]) => k === p) ? p : 'billing';
};

export default function App() {
  const [page, setPage] = useState(pageFromHash);
  const { settings } = useConfig();
  const shop = settings('shop');
  const [summary, setSummary] = useState(null);
  const [toast, setToast] = useState('');
  const [now, setNow] = useState(new Date());

  const refresh = useCallback(() => api.get('/api/dashboard').then((d) => setSummary(d.target)).catch(() => {}), []);
  useEffect(() => { refresh(); const t = setInterval(refresh, 60_000); return () => clearInterval(t); }, [refresh]);
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 30_000); return () => clearInterval(t); }, []);
  useEffect(() => { if (location.hash.slice(1) !== page) location.hash = page; }, [page]);
  useEffect(() => {
    const h = () => { const p = pageFromHash(); setPage(p); if (location.hash.slice(1) !== p) location.replace(`#${p}`); };
    window.addEventListener('hashchange', h);
    return () => window.removeEventListener('hashchange', h);
  }, []);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(''), 2600); return () => clearTimeout(t); }, [toast]);

  const notify = (msg) => setToast(msg);
  const pct = summary ? Math.min(100, summary.todayPct) : 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">{shop.logo ? <img src={shop.logo} alt="" /> : <Logo />} <span>{shop.shop_name || 'Waffle Bros'}</span></div>
        <nav className="nav">
          {PAGES.map(([k, l]) => (
            <button key={k} className={page === k ? 'active' : ''} onClick={() => setPage(k)}>{l}</button>
          ))}
        </nav>
        <div className="spacer" />
        {summary && (
          <div className="today-chip num" title="Today's sales against today's goal">
            <span>Today <b>{inr(summary.todayRevenue)}</b>{summary.todayTarget > 0 && <> / {inr(summary.todayTarget)}</>}</span>
            <div className="bar"><div style={{ width: `${pct}%` }} /></div>
          </div>
        )}
        <div className="clock">{now.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })} · {now.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })}</div>
      </header>
      <main>
        {page === 'billing' && <Billing onOrder={refresh} notify={notify} goAdmin={() => setPage('admin')} />}
        {page === 'dashboard' && <Dashboard notify={notify} onChange={refresh} />}
        {page === 'dayend' && <DayEnd notify={notify} onChange={refresh} />}
        {page === 'admin' && <Admin notify={notify} onChange={refresh} />}
      </main>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
