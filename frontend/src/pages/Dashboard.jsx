import { useEffect, useState, useCallback } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ComposedChart, Line, Area, ReferenceLine, Cell, LabelList,
} from 'recharts';
import { api, inr, inrShort, pinApi, today, thisMonth, syncShopClock, SERIES } from '../api.js';
import { useConfig } from '../config.jsx';
import DashGrid from '../components/DashGrid.jsx';
import { CARDS, cardTitle, defaultLayout, isDefault, loadLayout, saveLayout, setHidden } from '../layout.js';

const HONEY = SERIES[0];
const PURPLE = SERIES[1];
const CHOC = '#4A2C1A';
const HONEY_SOFT = '#e8c78a'; // the week or month still in progress
const TARGET_FILL = '#f6ead4';
const GRID = '#f1e8d8';
const AXIS = { fontSize: 12, fill: '#9a8879' };
const ICON = { good: '✅', warn: '⚠️', info: '💡' };

function Ring({ pct, expected }) {
  const r = 86, c = 2 * Math.PI * r;
  const p = Math.min(100, pct);
  return (
    <div className="ring">
      <svg width="200" height="200" viewBox="0 0 200 200">
        <circle cx="100" cy="100" r={r} fill="none" stroke="#f1e6d3" strokeWidth="16" />
        {p > 0 && (
          <circle cx="100" cy="100" r={r} fill="none" stroke={pct >= expected ? '#2e7d32' : '#F6B92B'} strokeWidth="16" strokeLinecap="round"
            strokeDasharray={`${(p / 100) * c} ${c}`} />
        )}
        {/* tick showing where an even pace would be today */}
        <line x1="100" y1="6" x2="100" y2="22" stroke={CHOC} strokeWidth="3" strokeLinecap="round"
          transform={`rotate(${(Math.min(100, expected) / 100) * 360} 100 100)`} />
      </svg>
      <div className="center">
        <div>
          <div className="pct num">{Math.round(pct)}%</div>
          <div className="of">of monthly target</div>
          <div className="of small">even pace: {Math.round(expected)}%</div>
        </div>
      </div>
    </div>
  );
}

function Tip({ active, payload, label, labelFmt }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tt num">
      <div className="h">{labelFmt ? labelFmt(label, payload) : label}</div>
      {payload.filter((p) => p.value != null).map((p) => (
        <div className="r" key={p.dataKey}>
          <span><i className="sw" style={{ background: p.color || p.stroke }} />{p.name}</span>
          <b>{p.dataKey.toLowerCase().includes('orders') ? p.value : inr(p.value)}</b>
        </div>
      ))}
    </div>
  );
}

function TargetCard({ t, onSaved, notify }) {
  const [edit, setEdit] = useState(false);
  const [val, setVal] = useState(t.target);
  const save = async () => {
    try {
      await pinApi.put(`/api/targets/${t.month}`, { amount: Number(val), makeDefault: true }, 'Enter the admin PIN to change the target.');
      setEdit(false); onSaved(); notify('Target updated');
    } catch (e) { if (!e.cancelled) notify(e.message); }
  };
  const monthName = new Date(`${t.month}-01T00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
  const todayDone = t.todayRevenue >= t.todayTarget;
  return (
    <div className="card target-card">
      <Ring pct={t.progressPct} expected={t.expectedPct} />
      <div className="target-main">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>{monthName} · day {t.dayOfMonth} of {t.daysInMonth}</h2>
          {edit ? (
            <div className="row">
              <input style={{ width: 140 }} inputMode="numeric" value={val} onChange={(e) => setVal(e.target.value.replace(/\D/g, ''))} autoFocus onKeyDown={(e) => e.key === 'Enter' && save()} />
              <button className="btn primary sm" onClick={save}>Save</button>
              <button className="btn ghost sm" onClick={() => setEdit(false)}>Cancel</button>
            </div>
          ) : <button className="btn sm" onClick={() => { setVal(t.target); setEdit(true); }}>🎯 Set target</button>}
        </div>
        <div className="rev num">{inr(t.revenue)} <span>/ {inr(t.target)}</span></div>
        <div className="muted small">{t.remaining > 0 ? `${inr(t.remaining)} to go with ${t.daysLeft} days left (including today)` : 'Target reached this month 🎉'}</div>

        <div className="today-bar">
          <div className="lbl num"><span>Today: <b>{inr(t.todayRevenue)}</b> from {t.todayOrders} order{t.todayOrders === 1 ? '' : 's'}</span><span>Goal <b>{inr(t.todayTarget)}</b></span></div>
          <div className="track"><div className={`fill ${todayDone ? 'done' : ''}`} style={{ width: `${Math.min(100, t.todayPct)}%` }} /></div>
          <div className="small muted" style={{ marginTop: 6 }}>
            {todayDone ? 'Today’s goal is done. Anything extra lowers tomorrow’s goal.'
              : `${inr(t.todayRemaining)} more today${t.ordersNeededToday ? ` ≈ ${t.ordersNeededToday} orders at ${inr(t.aov)} avg bill` : ''}`}
          </div>
        </div>

        <div className="stats num">
          <div className="stat"><div className="k">Needed per day from tomorrow</div><div className="v">{inr(t.requiredDailyFromTomorrow)}</div><div className="s">even pace {inr(t.evenDailyTarget)}</div></div>
          <div className="stat"><div className="k">Projected month end</div><div className="v" style={{ color: t.projected >= t.target ? '#2e7d32' : '#b45309' }}>{inr(t.projected)}</div><div className="s">at {inr(t.avgDaily)}/day avg</div></div>
          <div className="stat"><div className="k">Expenses this month</div><div className="v">{inr(t.expenses.total)}</div><div className="s">break-even {inr(t.breakEvenDaily)}/day</div></div>
          <div className="stat"><div className="k">Net profit so far</div><div className="v" style={{ color: t.netProfit >= 0 ? '#2e7d32' : '#b3261e' }}>{inr(t.netProfit)}</div><div className="s">{t.orders} orders · avg {inr(t.aov)}</div></div>
        </div>
      </div>
    </div>
  );
}

const hourRange = (h) => `${hourLabel(h)} – ${hourLabel((h + 1) % 24)}`;
function hourLabel(h) { return `${(h + 11) % 12 + 1}${h < 12 ? 'am' : 'pm'}`; }
const dayFmt = (iso) => iso ? new Date(`${iso}T00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' }) : '';

function Charts({ c, now }) {
  const [tab, setTab] = useState('daily');
  const views = { hourly: 'Hourly', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };
  const nowHour = now.getHours();
  const nowLabel = c.hourly.find((h) => h.hour === nowHour)?.label;
  const todayDay = now.getDate();
  const avgName = c.hourlyDays ? `Average day (last 4 weeks, ${c.hourlyDays} day${c.hourlyDays === 1 ? '' : 's'} with sales)` : 'Average day (no earlier sales yet)';
  return (
    <div className="card panel sales-card">
      <div className="panel-head">
        <h3>Sales</h3>
        <div className="seg">{Object.entries(views).map(([k, l]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
      </div>
      {tab === 'hourly' && <>
        <div className="legend" style={{ marginBottom: 8 }}>
          <span><i style={{ background: HONEY }} />Today, by the hour the bill was made</span>
          <span><i className="line-key" style={{ background: PURPLE }} />{avgName}</span>
          {nowLabel && <span><i className="now-key" />Now ({now.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' })})</span>}
        </div>
        <div className="chart-wrap tall"><ResponsiveContainer>
          <ComposedChart data={c.hourly} margin={{ top: 18, right: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval={0} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} allowDecimals={false} />
            <Tooltip content={<Tip labelFmt={(l, p) => hourRange(p[0]?.payload?.hour ?? 0)} />} cursor={{ fill: '#fff3cf88' }} />
            {nowLabel && <ReferenceLine x={nowLabel} stroke={CHOC} strokeDasharray="3 3" strokeWidth={1.5} label={{ value: 'now', position: 'top', fill: CHOC, fontSize: 11 }} />}
            <Bar dataKey="today" name="Today" fill={HONEY} radius={[4, 4, 0, 0]} maxBarSize={28} />
            {c.hourlyDays > 0 && <Line dataKey="average" name="Average day" stroke={PURPLE} strokeWidth={2} dot={{ r: 3, fill: PURPLE }} activeDot={{ r: 5 }} />}
          </ComposedChart>
        </ResponsiveContainer></div>
      </>}
      {tab === 'daily' && <>
        <div className="legend" style={{ marginBottom: 8 }}><span><i style={{ background: HONEY }} />Revenue per day</span><span><i className="dash-key" />Daily target (even pace)</span></div>
        <div className="chart-wrap"><ResponsiveContainer>
          <ComposedChart data={c.daily} margin={{ top: 18, right: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="day" tick={AXIS} axisLine={false} tickLine={false} interval={1} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => dayFmt(p[0]?.payload?.date)} />} cursor={{ fill: '#fff3cf88' }} />
            <ReferenceLine x={todayDay} stroke={CHOC} strokeDasharray="3 3" strokeWidth={1.5} label={{ value: 'today', position: 'top', fill: CHOC, fontSize: 11 }} />
            <Bar dataKey="revenue" name="Revenue" fill={HONEY} radius={[4, 4, 0, 0]} maxBarSize={18} />
            <ReferenceLine y={c.daily[0]?.dailyTarget} stroke={CHOC} strokeDasharray="5 4" strokeWidth={2} ifOverflow="extendDomain" />
          </ComposedChart>
        </ResponsiveContainer></div>
        <div className="legend" style={{ margin: '14px 0 8px' }}><span><i style={{ background: HONEY }} />Running total this month</span><span><i className="dash-key" />Where you need to be</span></div>
        <div className="chart-wrap" style={{ height: 200 }}><ResponsiveContainer>
          <ComposedChart data={c.daily} margin={{ top: 18, right: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="day" tick={AXIS} axisLine={false} tickLine={false} interval={1} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => dayFmt(p[0]?.payload?.date)} />} />
            <Area dataKey="cumulative" name="Running total" stroke={HONEY} fill={HONEY} fillOpacity={0.18} strokeWidth={2} connectNulls={false} />
            <Line dataKey="pace" name="Target pace" stroke={CHOC} strokeDasharray="5 4" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer></div>
      </>}
      {tab === 'weekly' && <>
        <div className="legend" style={{ marginBottom: 8 }}>
          <span><i style={{ background: HONEY }} />Revenue per week (Monday to Sunday)</span>
          <span><i style={{ background: HONEY_SOFT }} />This week so far</span>
        </div>
        <div className="chart-wrap tall"><ResponsiveContainer>
          <BarChart data={c.weekly} margin={{ top: 22, right: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={8} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => `${l}${p[0]?.payload?.current ? ' (this week so far)' : ''} · ${p[0]?.payload?.orders ?? 0} bills`} />} cursor={{ fill: '#fff3cf88' }} />
            <Bar dataKey="revenue" name="Revenue" radius={[4, 4, 0, 0]} maxBarSize={56}>
              {c.weekly.map((w) => <Cell key={w.start} fill={w.current ? HONEY_SOFT : HONEY} />)}
              <LabelList dataKey="revenue" position="top" formatter={inrShort} style={{ fontSize: 11, fill: CHOC }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer></div>
        {c.weekly.length < 3 && <p className="small muted card-foot">Weeks start from your first bill, so more bars appear as the shop keeps trading.</p>}
      </>}
      {tab === 'monthly' && <>
        <div className="legend" style={{ marginBottom: 8 }}>
          <span><i style={{ background: HONEY }} />Revenue</span>
          <span><i style={{ background: TARGET_FILL, border: `1px dashed ${CHOC}` }} />Still to go to reach the target</span>
        </div>
        <div className="chart-wrap tall"><ResponsiveContainer>
          <BarChart data={c.monthly.map((m) => ({
            ...m,
            pct: m.target ? Math.round((m.revenue / m.target) * 100) : null,
            rest: Math.max(0, (m.target || 0) - m.revenue), // the part of the target still to earn
          }))} margin={{ top: 26, right: 8 }}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} interval="preserveStartEnd" minTickGap={8} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => {
              const m = p[0]?.payload;
              return `${l}${m?.current ? ' (so far)' : ''}${m?.pct != null ? ` · ${m.pct}% of ${inr(m.target)}` : ''}`;
            }} />} cursor={{ fill: '#fff3cf88' }} />
            <Bar dataKey="revenue" name="Revenue" stackId="m" fill={HONEY} maxBarSize={72} />
            <Bar dataKey="rest" name="Still to go" stackId="m" fill={TARGET_FILL} stroke={CHOC} strokeDasharray="4 3" radius={[4, 4, 0, 0]} maxBarSize={72}>
              <LabelList dataKey="pct" position="top" formatter={(v) => (v == null ? '' : `${v}%`)} style={{ fontSize: 11, fill: CHOC, fontWeight: 700 }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer></div>
        {c.monthly.length < 3 && <p className="small muted card-foot">Months start from your first bill. The full bar is the month's target; the % is how much of it was reached.</p>}
      </>}
    </div>
  );
}

function SplitBars({ rows, color, valueKey = 'value', fmt = inr, empty = 'No sales yet.' }) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey]));
  if (!rows.length || rows.every((r) => !r[valueKey])) return <div className="muted small">{empty}</div>;
  return (
    <div className="split num">
      {rows.map((r, i) => (
        <div className="r" key={r.name || r.day}>
          <span style={{ textTransform: 'capitalize' }}>{r.name || r.day}{r.note && <span className="muted small"> {r.note}</span>}</span>
          <div className="track"><div style={{ width: `${(r[valueKey] / max) * 100}%`, background: typeof color === 'function' ? color(r, i) : color }} /></div>
          <b style={{ textAlign: 'right' }}>{fmt(r[valueKey])}</b>
        </div>
      ))}
    </div>
  );
}

// "1 – 20 Nov" for the dates an item-stats period covers (`to` is exclusive).
const shortDate = (iso) => new Date(`${iso}T00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
function rangeText({ from, to }) {
  if (!from || !to) return '';
  if (from === '0000-00-00') return 'All time';
  const last = new Date(`${to}T00:00`);
  last.setDate(last.getDate() - 1);
  const end = `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`;
  return from === end ? shortDate(from) : `${shortDate(from)} – ${shortDate(end)}`;
}

function Items({ initial }) {
  const [period, setPeriod] = useState(initial.period);
  const [data, setData] = useState(initial);
  const [sort, setSort] = useState('revenue');
  const [err, setErr] = useState('');
  useEffect(() => {
    // Ignore a reply that arrives after the period was changed again, so the table never shows
    // one period's numbers under another period's tab.
    let live = true;
    setErr('');
    if (period === initial.period) setData(initial);
    else {
      api.get(`/api/items/stats?period=${period}`)
        .then((x) => { if (live) setData(x); })
        .catch((e) => { if (live) setErr(e.message); });
    }
    return () => { live = false; };
  }, [period, initial]);
  const loading = data.period !== period && !err;
  const rows = data.items.filter((i) => i.qty > 0 || i.active).sort((a, b) => b[sort] - a[sort]);
  const max = Math.max(1, ...rows.map((r) => r[sort]));
  const F = ({ k, i, s }) => (
    <div className="f"><div className="k">{k}</div><div className="n">{i ? i.name : '—'}</div><div className="s num">{i ? s(i) : 'No sales yet'}</div></div>
  );
  return (
    <div className={`card panel fill-card items-card${loading ? ' loading' : ''}`}>
      <div className="panel-head">
        <div>
          <h3>What's selling</h3>
          <div className="small muted num">{rangeText(data)}{data.bills != null && ` · ${data.bills} bill${data.bills === 1 ? '' : 's'} · ${inr(data.revenue)}`}</div>
        </div>
        <div className="seg">{[['today', 'Today'], ['week', '7 days'], ['month', 'This month'], ['all', 'All time']].map(([k, l]) =>
          <button key={k} className={period === k ? 'active' : ''} onClick={() => setPeriod(k)}>{l}</button>)}</div>
      </div>
      {err && <div className="err small">{err}</div>}
      <div className="fav">
        <F k="🏆 Best seller" i={data.bestSeller} s={(i) => `${inr(i.revenue)} earned`} />
        <F k="🔥 Most popular" i={data.mostPopular} s={(i) => `${i.qty} sold`} />
        <F k="❤️ Customer favourite" i={data.customerFavourite} s={(i) => `in ${i.orders} separate orders`} />
      </div>
      <div className="scroll grow-scroll" style={{ minHeight: 420 }}>
        <table className="tbl num">
          <thead><tr>
            <th>Item</th>
            <th className="r" style={{ cursor: 'pointer' }} onClick={() => setSort('qty')}>Sold{sort === 'qty' && ' ▾'}</th>
            <th className="r" style={{ cursor: 'pointer' }} onClick={() => setSort('orders')}>Orders{sort === 'orders' && ' ▾'}</th>
            <th className="r" style={{ cursor: 'pointer' }} onClick={() => setSort('revenue')}>Revenue{sort === 'revenue' && ' ▾'}</th>
            <th className="barc" style={{ width: 90 }} />
            <th className="r marginc">Margin</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><b>{r.name}</b> <span className="muted small">{r.code}</span>{!r.active && <span className="pill" style={{ marginLeft: 6 }}>hidden</span>}</td>
                <td className="r">{r.qty}</td>
                <td className="r">{r.orders}</td>
                <td className="r">{inr(r.revenue)}</td>
                <td className="barc"><div className="bar-inline"><div style={{ width: `${(r[sort] / max) * 100}%` }} /></div></td>
                <td className="r marginc">{r.margin == null ? <span className="muted">—</span> : <span className={`pill ${r.margin >= 60 ? 'good' : r.margin >= 50 ? '' : 'warn'}`}>{Math.round(r.margin)}%</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Expenses({ month, onChange, notify }) {
  const { settings } = useConfig();
  const cats = settings('targets').expense_categories?.length ? settings('targets').expense_categories : ['other'];
  const [data, setData] = useState(null);
  const [f, setF] = useState({ category: '', amount: '', date: today(), note: '', recurring: false });
  const load = useCallback(() => api.get(`/api/expenses?month=${month}`).then(setData), [month]);
  useEffect(() => { load(); }, [load]);
  const category = cats.includes(f.category) ? f.category : cats.includes('ingredients') ? 'ingredients' : cats[0];
  const add = async () => {
    try {
      await pinApi.post('/api/expenses', { ...f, category, amount: Number(f.amount) }, 'Enter the admin PIN to add an expense.');
      setF({ ...f, amount: '', note: '', recurring: false });
      load(); onChange(); notify('Expense added');
    } catch (e) { if (!e.cancelled) notify(e.message); }
  };
  const del = async (id) => {
    try { await pinApi.del(`/api/expenses/${id}`, 'Enter the admin PIN to delete this expense.'); load(); onChange(); }
    catch (e) { if (!e.cancelled) notify(e.message); }
  };
  const list = data ? [...data.recurring.map((e) => ({ ...e, rec: true })), ...data.oneOff] : [];
  return (
    <div className="card panel fill-card">
      <div className="panel-head"><h3>Expenses this month</h3>{data && <b className="num">{inr(data.total)}</b>}</div>
      <div className="exp-form">
        <select value={category} onChange={(e) => setF({ ...f, category: e.target.value })}>
          {cats.map((c) => <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>)}
        </select>
        <input placeholder="Amount ₹" inputMode="numeric" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value.replace(/[^\d.]/g, '') })} />
        <input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />
        <input className="full" placeholder="Note (optional)" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <label className="row small" style={{ gridColumn: 'span 2' }}><input type="checkbox" style={{ width: 'auto' }} checked={f.recurring} onChange={(e) => setF({ ...f, recurring: e.target.checked })} /> Repeats every month (rent, salary)</label>
        <button className="btn primary" onClick={add} disabled={!f.amount}>Add</button>
      </div>
      {data?.byCategory?.length > 0 && <div style={{ marginBottom: 12 }}><SplitBars rows={data.byCategory.map((c) => ({ name: c.category, value: c.amount }))} color="#8a5a0b" /></div>}
      <div className="scroll grow-scroll" style={{ minHeight: 160 }}>
        <table className="tbl num">
          <tbody>
            {list.map((e) => (
              <tr key={e.id}>
                <td className="small">{e.rec ? <span className="pill">monthly</span> : e.date.slice(8) + '/' + e.date.slice(5, 7)}</td>
                <td><span style={{ textTransform: 'capitalize' }}>{e.category}</span><div className="muted small">{e.note}</div></td>
                <td className="r">{inr(e.amount)}</td>
                <td className="r"><button className="btn ghost sm danger" onClick={() => del(e.id)} aria-label="Delete">✕</button></td>
              </tr>
            ))}
            {data && !list.length && <tr><td className="muted">No expenses yet. Add rent, salaries and stock purchases to see real profit.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------- Sales calendar ----------
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const shiftMonth = (m, by) => {
  const [y, mo] = m.split('-').map(Number);
  const d = new Date(y, mo - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};
const monthTitle = (m) => new Date(`${m}-01T00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });

function dayTone(d, dailyTarget) {
  if (d.future) return 'future';
  if (!d.orders) return 'none';
  if (dailyTarget > 0 && d.revenue >= dailyTarget) return 'hit';
  if (dailyTarget > 0 && d.revenue >= dailyTarget / 2) return 'half';
  return 'some';
}

function DayDetail({ date }) {
  const [d, setD] = useState(null);
  useEffect(() => {
    setD(null);
    api.get(`/api/day-end?date=${date}`).then(setD).catch(() => setD(false));
  }, [date]);
  const open = () => { location.hash = date === today() ? 'dayend' : `dayend?date=${date}`; };
  return (
    <div className="cal-detail">
      <div className="cal-detail-head">
        <h3>{dayFmt(date)}{date === today() && <span className="pill" style={{ marginLeft: 8 }}>today</span>}</h3>
      </div>
      {d === null && <div className="muted small">Loading…</div>}
      {d === false && <div className="err">Could not load this day.</div>}
      {d && <>
        <div className="cal-stats num">
          <div><div className="k">Sales</div><div className="v">{inr(d.revenue)}</div></div>
          <div><div className="k">Bills</div><div className="v">{d.orders}</div></div>
          <div><div className="k">Avg bill</div><div className="v">{inr(d.aov)}</div></div>
        </div>
        {d.payments.length > 0 && (
          <div className="small muted" style={{ marginBottom: 10 }}>
            {d.payments.map((p) => `${p.method.toUpperCase()} ${inr(p.amount)}`).join(' · ')}
            {d.cancelled.n > 0 && ` · ${d.cancelled.n} cancelled (${inr(d.cancelled.amount)})`}
          </div>
        )}
        {d.items.length ? (
          <table className="tbl num small-tbl">
            <tbody>{d.items.slice(0, 6).map((i) => (
              <tr key={i.name}><td>{i.name}</td><td className="r">×{i.qty}</td><td className="r">{inr(i.revenue)}</td></tr>
            ))}</tbody>
          </table>
        ) : <div className="muted small">No sales on this day{d.cancelled.n > 0 ? ` (${d.cancelled.n} cancelled bill${d.cancelled.n === 1 ? '' : 's'})` : ''}.</div>}
        {d.items.length > 6 && <div className="muted small" style={{ marginTop: 6 }}>+ {d.items.length - 6} more items</div>}
      </>}
      <button className="btn sm" style={{ marginTop: 'auto' }} onClick={open}>Open full Day End report →</button>
    </div>
  );
}

function SalesCalendar({ month: current }) {
  const [month, setMonth] = useState(current);
  const [cal, setCal] = useState(null);
  const [err, setErr] = useState('');
  const [picked, setPicked] = useState(today());
  useEffect(() => { setMonth(current); }, [current]);
  useEffect(() => {
    api.get(`/api/calendar?month=${month}`).then((c) => { setCal(c); setErr(''); }).catch((e) => setErr(e.message));
  }, [month]);
  useEffect(() => {
    // Keep a selected day inside the month on screen: today if it is this month, else the best day.
    if (!cal || cal.month !== month || picked.startsWith(month)) return;
    setPicked(cal.today.startsWith(month) ? cal.today : cal.bestDay || `${month}-01`);
  }, [cal, month]); // eslint-disable-line react-hooks/exhaustive-deps

  const lead = cal ? cal.days[0].weekday : 0;
  const atCurrent = month >= current;
  return (
    <div className="card panel">
      <div className="panel-head">
        <h3>Sales calendar</h3>
        <div className="row">
          <button className="btn sm" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">‹</button>
          <b className="cal-month">{monthTitle(month)}</b>
          <button className="btn sm" disabled={atCurrent} onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Next month">›</button>
          {!atCurrent && <button className="btn ghost sm" onClick={() => { setMonth(current); setPicked(today()); }}>This month</button>}
        </div>
      </div>
      {err && <div className="err">{err}</div>}
      {cal && cal.month === month && (
        <div className="cal-layout">
          <div>
            <div className="cal-summary num small">
              <span><b>{inr(cal.revenue)}</b> from {cal.orders} bill{cal.orders === 1 ? '' : 's'}</span>
              <span>{cal.tradingDays} day{cal.tradingDays === 1 ? '' : 's'} with sales · avg <b>{inr(cal.avgDaily)}</b>/day</span>
              <span>Daily goal at an even pace <b>{inr(cal.dailyTarget)}</b></span>
            </div>
            <div className="cal-grid" role="grid" aria-label={`Sales in ${monthTitle(month)}`}>
              {WEEKDAYS.map((w) => <div key={w} className="cal-wd">{w}</div>)}
              {Array.from({ length: lead }, (_, i) => <div key={`pad${i}`} />)}
              {cal.days.map((d) => (
                <button key={d.date} type="button" disabled={d.future}
                  className={`cal-day ${dayTone(d, cal.dailyTarget)}${d.today ? ' today' : ''}${picked === d.date ? ' picked' : ''}`}
                  onClick={() => setPicked(d.date)}
                  title={d.future ? '' : `${dayFmt(d.date)}: ${inr(d.revenue)} from ${d.orders} bill${d.orders === 1 ? '' : 's'}`}>
                  <span className="n">{d.day}</span>
                  {!d.future && <span className="rv num">{d.orders ? inrShort(d.revenue) : '—'}</span>}
                  {!d.future && d.orders > 0 && <span className="oc num">{d.orders} bill{d.orders === 1 ? '' : 's'}</span>}
                </button>
              ))}
            </div>
            <div className="legend cal-legend">
              <span><i className="cal-key hit" />Met the daily goal</span>
              <span><i className="cal-key half" />Half or more</span>
              <span><i className="cal-key some" />Under half</span>
              <span><i className="cal-key none" />No sales</span>
            </div>
          </div>
          {picked.startsWith(month) && <DayDetail date={picked} />}
        </div>
      )}
    </div>
  );
}

export default function Dashboard({ notify, onChange }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const [layout, setLayout] = useState(loadLayout);
  const [editing, setEditing] = useState(false);
  const load = useCallback(() => api.get('/api/dashboard?period=month').then((x) => { syncShopClock(x.now); setD(x); setErr(''); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);
  useEffect(() => { saveLayout(layout); }, [layout]);
  const changed = () => { load(); onChange(); };
  if (err) return <div className="page err">{err}</div>;
  if (!d) return <div className="page muted">Loading dashboard…</div>;
  const cards = {
    target: <TargetCard t={d.target} onSaved={changed} notify={notify} />,
    sales: <Charts c={d.charts} now={new Date(d.now)} />,
    insights: (
      <div className="card panel insights-card">
        <h3>Insights</h3>
        <div className="insights">
          {d.insights.map((i, k) => (
            <div key={k} className={`insight ${i.tone}`}><span className="ic">{ICON[i.tone]}</span><div><b>{i.title}</b><p>{i.text}</p></div></div>
          ))}
        </div>
      </div>
    ),
    calendar: <SalesCalendar month={d.target.month} />,
    items: <Items initial={d.items} />,
    expenses: <Expenses month={thisMonth()} onChange={changed} notify={notify} />,
    categories: (
      <div className="card panel">
        <h3>Sales by category · this month</h3>
        <SplitBars rows={d.charts.categorySplit} color={(r, i) => SERIES[i % SERIES.length]} />
      </div>
    ),
    weekdays: (
      <div className="card panel">
        <h3>Average sales by weekday · last 8 weeks</h3>
        <SplitBars rows={d.charts.weekday.map((w) => ({ name: w.day, value: w.average, note: w.days ? `×${w.days}` : '' }))} color={HONEY}
          empty="No sales before today in the last 8 weeks yet." />
        <p className="small muted card-foot">Average of the days that had sales (×N is how many such days), today not included.</p>
      </div>
    ),
    payments: (
      <div className="card panel">
        <h3>Payment methods · this month</h3>
        <SplitBars rows={d.charts.paymentSplit.map((p) => ({ ...p, name: p.name.toUpperCase() }))} color={PURPLE} />
      </div>
    ),
  };
  const hidden = CARDS.filter((c) => layout.hidden.includes(c.id));
  return (
    <div className="page">
      <div className="page-head">
        <h1>Dashboard</h1>
        <span className="muted small">{editing ? 'Customising the layout' : `Updates every minute${hidden.length ? ` · ${hidden.length} card${hidden.length === 1 ? '' : 's'} hidden` : ''}`}</span>
        <div className="spacer" style={{ flex: 1 }} />
        {editing ? <>
          <button className="btn sm" disabled={isDefault(layout)} onClick={() => { setLayout(defaultLayout()); notify('Layout reset'); }}>↺ Reset layout</button>
          <button className="btn primary sm" onClick={() => setEditing(false)}>Done</button>
        </> : <>
          <button className="btn sm" onClick={() => setEditing(true)}>✥ Customise</button>
          <button className="btn sm" onClick={load}>↻ Refresh</button>
        </>}
      </div>
      {editing && (
        <div className="customise-bar">
          <span className="small">Drag a card by its <b>⠿</b> handle, or use ◀ ▶ to move it and − + to change its width. The layout is saved on this device only.</span>
          {hidden.length > 0 && (
            <div className="row hidden-cards">
              <span className="small muted">Hidden:</span>
              {hidden.map((c) => (
                <button key={c.id} className="btn sm" onClick={() => setLayout(setHidden(layout, c.id, false))} aria-label={`Show ${cardTitle(c.id)}`}>+ {c.title}</button>
              ))}
            </div>
          )}
        </div>
      )}
      <DashGrid layout={layout} cards={cards} editing={editing} onChange={setLayout} />
    </div>
  );
}
