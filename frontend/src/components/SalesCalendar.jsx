import { useEffect, useState } from 'react';
import { api, inr, inrShort } from '../api.js';

const WEEK = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const monthTitle = (key) => new Date(`${key}-01T00:00:00Z`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric', timeZone: 'UTC' });
const shiftMonth = (key, by) => {
  const [y, m] = key.split('-').map(Number);
  const i = y * 12 + (m - 1) + by;
  return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`;
};

// A month of shop-local days with each day's paid sales. Tap a day to open its day-end report.
export default function SalesCalendar({ selected, onSelect, refreshKey }) {
  const [month, setMonth] = useState(selected.slice(0, 7));
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');

  useEffect(() => { setMonth(selected.slice(0, 7)); }, [selected]);
  useEffect(() => {
    let live = true;
    api.get(`/api/calendar?month=${month}`)
      .then((d) => { if (live) { setData(d); setErr(''); } })
      .catch((e) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [month, refreshKey]);

  const thisMonth = data?.today?.slice(0, 7);
  const ready = data && data.month === month;
  // Monday-first grid: blank cells before the 1st.
  const lead = ready ? WEEK.indexOf(data.days[0].weekday) : 0;

  return (
    <div className="card panel cal">
      <div className="cal-head">
        <button className="btn ghost sm" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">‹</button>
        <h3>{monthTitle(month)}</h3>
        <button className="btn ghost sm" onClick={() => setMonth(shiftMonth(month, 1))} disabled={thisMonth && month >= thisMonth} aria-label="Next month">›</button>
      </div>
      {err && <div className="err">{err}</div>}
      <div className="cal-grid" role="grid" aria-label={`Sales in ${monthTitle(month)}`}>
        {WEEK.map((w) => <div key={w} className="cal-wd">{w.slice(0, 2)}</div>)}
        {Array.from({ length: lead }, (_, i) => <div key={`b${i}`} />)}
        {ready && data.days.map((d) => {
          const hit = d.revenue > 0 && data.dailyTarget > 0 && d.revenue >= data.dailyTarget;
          const heat = d.revenue > 0 && data.dailyTarget > 0 ? Math.min(1, d.revenue / data.dailyTarget) : 0;
          const cls = ['cal-day', d.future && 'future', d.today && 'today', d.date === selected && 'sel', d.revenue > 0 && 'sold', hit && 'hit'].filter(Boolean).join(' ');
          return (
            <button key={d.date} className={cls} disabled={d.future} onClick={() => onSelect(d.date)}
              style={d.revenue > 0 ? { '--heat': 0.25 + heat * 0.75 } : undefined}
              title={d.future ? '' : `${d.weekday} ${d.day}: ${inr(d.revenue)} from ${d.orders} bill${d.orders === 1 ? '' : 's'}${d.cancelled ? `, ${d.cancelled} cancelled` : ''}`}>
              <span className="n">{d.day}</span>
              <span className="v num">{d.future ? '' : d.revenue > 0 ? inrShort(d.revenue) : '·'}</span>
            </button>
          );
        })}
      </div>
      {ready && (
        <div className="cal-foot num">
          <div><span className="muted">Month</span><b>{inr(data.revenue)}</b></div>
          <div><span className="muted">Bills</span><b>{data.orders}</b></div>
          <div><span className="muted">Days open</span><b>{data.tradingDays}</b></div>
        </div>
      )}
      <div className="cal-key small muted">
        <span><i className="k sold" />Sales</span><span><i className="k hit" />Daily target met ({ready ? inrShort(data.dailyTarget) : '…'})</span><span><i className="k today" />Today</span>
      </div>
    </div>
  );
}
