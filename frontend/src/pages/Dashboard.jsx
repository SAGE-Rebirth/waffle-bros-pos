import { useEffect, useState, useCallback } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, Cell, XAxis, YAxis, Tooltip, CartesianGrid, ComposedChart, Line, Area, ReferenceLine,
} from 'recharts';
import { api, inr, inrShort, pinApi, today, SERIES } from '../api.js';
import { useConfig } from '../config.jsx';

const HONEY = SERIES[0];
const PURPLE = SERIES[1];
const CHOC = '#4A2C1A';
const GRID = '#f1e8d8';
const AXIS = { fontSize: 12, fill: '#9a8879' };
const ICON = { good: '✅', warn: '⚠️', info: '💡' };
const TODAY_BAR = '#4A2C1A';
const hourLabel = (h) => `${((h % 24) + 11) % 12 + 1}${h % 24 < 12 ? 'am' : 'pm'}`;
// '2026-11-20' -> 'Fri 20/11' (the date is already shop-local; read it as UTC so nothing shifts).
const dayLabel = (iso) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'UTC' }) : '');

function Ring({ pct, expected }) {
  const r = 86, c = 2 * Math.PI * r;
  const p = Math.min(100, pct);
  return (
    <div className="ring">
      <svg width="200" height="200" viewBox="0 0 200 200">
        <circle cx="100" cy="100" r={r} fill="none" stroke="#f1e6d3" strokeWidth="16" />
        <circle cx="100" cy="100" r={r} fill="none" stroke={pct >= expected ? '#2e7d32' : '#F6B92B'} strokeWidth="16" strokeLinecap="round"
          strokeDasharray={`${(p / 100) * c} ${c}`} />
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
    <div className="card target-card span-12">
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

function Charts({ c, today }) {
  const [tab, setTab] = useState('daily');
  const views = { hourly: 'Hourly', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly' };
  return (
    <div className="card panel span-8">
      <div className="panel-head">
        <h3>Sales</h3>
        <div className="seg">{Object.entries(views).map(([k, l]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
      </div>
      {tab === 'hourly' && <>
        <div className="legend" style={{ marginBottom: 8 }}><span><i style={{ background: HONEY }} />Today ({dayLabel(today)})</span><span><i style={{ background: PURPLE }} />Average trading day (last 4 weeks)</span></div>
        <div className="chart-wrap"><ResponsiveContainer>
          <BarChart data={c.hourly} barGap={2}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => { const h = p[0]?.payload?.hour; return h == null ? l : `${l} to ${hourLabel(h + 1)}`; }} />} cursor={{ fill: '#fff3cf88' }} />
            <Bar dataKey="today" name="Today" fill={HONEY} radius={[4, 4, 0, 0]} maxBarSize={22} />
            <Bar dataKey="average" name="Average day" fill={PURPLE} radius={[4, 4, 0, 0]} maxBarSize={22} />
          </BarChart>
        </ResponsiveContainer></div>
      </>}
      {tab === 'daily' && <>
        <div className="legend" style={{ marginBottom: 8 }}><span><i style={{ background: HONEY }} />Revenue per day</span><span><i style={{ background: TODAY_BAR }} />Today</span><span><i className="dash-key" />Daily target (even pace)</span></div>
        <div className="chart-wrap"><ResponsiveContainer>
          <ComposedChart data={c.daily}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="day" tick={{ ...AXIS, fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => dayLabel(p[0]?.payload?.date)} />} cursor={{ fill: '#fff3cf88' }} />
            <Bar dataKey="revenue" name="Revenue" fill={HONEY} radius={[4, 4, 0, 0]} maxBarSize={18}>
              {c.daily.map((r) => <Cell key={r.date} fill={r.date === today ? TODAY_BAR : HONEY} />)}
            </Bar>
            <ReferenceLine y={c.daily[0]?.dailyTarget} stroke={CHOC} strokeDasharray="5 4" strokeWidth={2} ifOverflow="extendDomain" />
          </ComposedChart>
        </ResponsiveContainer></div>
        <div className="legend" style={{ margin: '14px 0 8px' }}><span><i style={{ background: HONEY }} />Running total this month</span><span><i className="dash-key" />Where you need to be</span></div>
        <div className="chart-wrap" style={{ height: 200 }}><ResponsiveContainer>
          <ComposedChart data={c.daily}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="day" tick={{ ...AXIS, fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip labelFmt={(l, p) => dayLabel(p[0]?.payload?.date)} />} />
            <Area dataKey="cumulative" name="Running total" stroke={HONEY} fill={HONEY} fillOpacity={0.18} strokeWidth={2} connectNulls={false} />
            <Line dataKey="pace" name="Target pace" stroke={CHOC} strokeDasharray="5 4" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer></div>
      </>}
      {tab === 'weekly' && <div className="chart-wrap"><ResponsiveContainer>
        <BarChart data={c.weekly}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="week" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
          <Tooltip content={<Tip labelFmt={(l) => `Week of ${l} (Mon to Sun)`} />} cursor={{ fill: '#fff3cf88' }} />
          <Bar dataKey="revenue" name="Revenue" fill={HONEY} radius={[4, 4, 0, 0]} maxBarSize={36} />
        </BarChart>
      </ResponsiveContainer></div>}
      {tab === 'monthly' && <>
        <div className="legend" style={{ marginBottom: 8 }}><span><i style={{ background: HONEY }} />Revenue</span><span><i className="dash-key" />Target</span></div>
        <div className="chart-wrap"><ResponsiveContainer>
          <ComposedChart data={c.monthly}>
            <CartesianGrid vertical={false} stroke={GRID} />
            <XAxis dataKey="month" tick={AXIS} axisLine={false} tickLine={false} />
            <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={inrShort} width={48} />
            <Tooltip content={<Tip />} cursor={{ fill: '#fff3cf88' }} />
            <Bar dataKey="revenue" name="Revenue" fill={HONEY} radius={[4, 4, 0, 0]} maxBarSize={36} />
            <Line dataKey="target" name="Target" stroke={CHOC} strokeDasharray="5 4" strokeWidth={2} dot={{ r: 4, fill: CHOC, stroke: '#fff', strokeWidth: 2 }} />
          </ComposedChart>
        </ResponsiveContainer></div>
      </>}
    </div>
  );
}

function SplitBars({ rows, color, valueKey = 'value', fmt = inr }) {
  const max = Math.max(1, ...rows.map((r) => r[valueKey]));
  if (!rows.length) return <div className="muted small">No sales yet.</div>;
  return (
    <div className="split num">
      {rows.map((r, i) => (
        <div className="r" key={r.name || r.day}>
          <span style={{ textTransform: 'capitalize' }}>{r.name || r.day}</span>
          <div className="track"><div style={{ width: `${(r[valueKey] / max) * 100}%`, background: typeof color === 'function' ? color(r, i) : color }} /></div>
          <b style={{ textAlign: 'right' }}>{fmt(r[valueKey])}</b>
        </div>
      ))}
    </div>
  );
}

function Items({ initial }) {
  const [period, setPeriod] = useState(initial.period);
  const [data, setData] = useState(initial);
  const [sort, setSort] = useState('revenue');
  useEffect(() => {
    if (period === initial.period) setData(initial);
    else api.get(`/api/items/stats?period=${period}`).then(setData);
  }, [period, initial]);
  const rows = data.items.filter((i) => i.qty > 0 || i.active).sort((a, b) => b[sort] - a[sort]);
  const max = Math.max(1, ...rows.map((r) => r[sort]));
  const F = ({ k, i, s }) => (
    <div className="f"><div className="k">{k}</div><div className="n">{i ? i.name : '—'}</div><div className="s num">{i ? s(i) : 'No sales yet'}</div></div>
  );
  return (
    <div className="card panel span-7 col">
      <div className="panel-head">
        <h3>What's selling</h3>
        <div className="seg">{[['today', 'Today'], ['week', '7 days'], ['month', 'This month'], ['all', 'All time']].map(([k, l]) =>
          <button key={k} className={period === k ? 'active' : ''} onClick={() => setPeriod(k)}>{l}</button>)}</div>
      </div>
      <div className="fav">
        <F k="🏆 Best seller" i={data.bestSeller} s={(i) => `${inr(i.revenue)} earned`} />
        <F k="🔥 Most popular" i={data.mostPopular} s={(i) => `${i.qty} sold`} />
        <F k="❤️ Customer favourite" i={data.customerFavourite} s={(i) => `in ${i.orders} separate orders`} />
      </div>
      <div className="scroll" style={{ maxHeight: 420 }}>
        <table className="tbl num">
          <thead><tr>
            <th>Item</th>
            <th className="r" style={{ cursor: 'pointer' }} onClick={() => setSort('qty')}>Sold{sort === 'qty' && ' ▾'}</th>
            <th className="r" style={{ cursor: 'pointer' }} onClick={() => setSort('orders')}>Orders{sort === 'orders' && ' ▾'}</th>
            <th className="r" style={{ cursor: 'pointer' }} onClick={() => setSort('revenue')}>Revenue{sort === 'revenue' && ' ▾'}</th>
            <th style={{ width: 90 }} />
            <th className="r">Margin</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td><b>{r.name}</b> <span className="muted small">{r.code}</span>{!r.active && <span className="pill" style={{ marginLeft: 6 }}>hidden</span>}</td>
                <td className="r">{r.qty}</td>
                <td className="r">{r.orders}</td>
                <td className="r">{inr(r.revenue)}</td>
                <td><div className="bar-inline"><div style={{ width: `${(r[sort] / max) * 100}%` }} /></div></td>
                <td className="r">{r.margin == null ? <span className="muted">—</span> : <span className={`pill ${r.margin >= 60 ? 'good' : r.margin >= 50 ? '' : 'warn'}`}>{Math.round(r.margin)}%</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Expenses({ month, day, onChange, notify }) {
  const { settings } = useConfig();
  const cats = settings('targets').expense_categories?.length ? settings('targets').expense_categories : ['other'];
  const [data, setData] = useState(null);
  const [f, setF] = useState({ category: '', amount: '', date: day || today(), note: '', recurring: false });
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
    <div className="card panel span-5 col">
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
      <div className="scroll fill">
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

export default function Dashboard({ notify, onChange }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => api.get('/api/dashboard?period=month').then((x) => { setD(x); setErr(''); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, [load]);
  const changed = () => { load(); onChange(); };
  if (err) return <div className="page err">{err}</div>;
  if (!d) return <div className="page muted">Loading dashboard…</div>;
  return (
    <div className="page">
      <div className="page-head">
        <h1>Dashboard</h1>
        <span className="muted small">{dayLabel(d.today)} · as of {d.now.slice(11, 16)} · updates every minute</span>
        <div className="spacer" style={{ flex: 1 }} />
        <a className="btn sm" href="#dayend">📅 Any day's sales</a>
        <button className="btn sm" onClick={load}>↻ Refresh</button>
      </div>
      <div className="dash">
        <TargetCard t={d.target} onSaved={changed} notify={notify} />
        <Charts c={d.charts} today={d.today} />
        <div className="card panel span-4 insights-card col">
          <h3>Insights</h3>
          <div className="insights fill scroll">
            {d.insights.map((i, k) => (
              <div key={k} className={`insight ${i.tone}`}><span className="ic">{ICON[i.tone]}</span><div><b>{i.title}</b><p>{i.text}</p></div></div>
            ))}
          </div>
        </div>
        <Items initial={d.items} />
        <Expenses month={d.target.month} day={d.today} onChange={changed} notify={notify} />
        <div className="card panel span-4">
          <h3>Sales by category · this month</h3>
          <SplitBars rows={d.charts.categorySplit} color={(r, i) => SERIES[i % SERIES.length]} />
        </div>
        <div className="card panel span-4">
          <h3>Average sales by weekday · last 8 weeks</h3>
          <SplitBars rows={d.charts.weekday.map((w) => ({ name: w.day, value: w.average }))} color={HONEY} />
          <p className="small muted card-note">Average of the days that had sales, up to yesterday. Today joins tomorrow.</p>
        </div>
        <div className="card panel span-4">
          <h3>Payment methods · this month</h3>
          <SplitBars rows={d.charts.paymentSplit.map((p) => ({ ...p, name: p.name.toUpperCase() }))} color={PURPLE} />
        </div>
      </div>
    </div>
  );
}
