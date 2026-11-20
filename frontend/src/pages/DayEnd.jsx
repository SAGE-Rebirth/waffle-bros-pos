import { useEffect, useState, useCallback } from 'react';
import { api, inr, pinApi, today } from '../api.js';
import SalesCalendar from '../components/SalesCalendar.jsx';
import BillDetail from '../components/BillDetail.jsx';
import { itemsSummary } from '../bills.js';

const longDate = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });

// #dayend?date=YYYY-MM-DD opens a given day (the Dashboard calendar links here).
const dateFromHash = () => {
  const m = /[?&]date=(\d{4}-\d{2}-\d{2})/.exec(location.hash);
  return m && m[1] <= today() ? m[1] : today();
};

export default function DayEnd({ notify, onChange }) {
  const [date, setDate] = useState(dateFromHash);
  useEffect(() => {
    const want = date === today() ? '#dayend' : `#dayend?date=${date}`;
    if (location.hash !== want) history.replaceState(null, '', want);
  }, [date]);
  const [d, setD] = useState(null);
  const [orders, setOrders] = useState([]);
  const [rev, setRev] = useState(0); // bumps the calendar after a cancel
  const [open, setOpen] = useState(null); // the bill shown in the pop-up
  const load = useCallback(() => {
    api.get(`/api/day-end?date=${date}`).then(setD).catch((e) => notify(e.message));
    api.get(`/api/orders?date=${date}`).then((list) => setOrders([...list].sort((a, b) => b.created_at.localeCompare(a.created_at)))).catch(() => {});
  }, [date]);
  useEffect(() => { load(); }, [load]);

  const cancel = async (o) => {
    if (!window.confirm(`Cancel bill ${o.bill_no} (${inr(o.total)})? It will be removed from sales.`)) return;
    try {
      await pinApi.post(`/api/orders/${o.id}/cancel`, {}, `Enter the admin PIN to cancel bill ${o.bill_no}.`);
      notify(`Bill ${o.bill_no} cancelled`);
      load(); onChange(); setRev((n) => n + 1);
    } catch (e) { if (!e.cancelled) notify(e.message); }
  };

  if (!d) return <div className="page muted">Loading…</div>;
  const isToday = d.date === today();
  const maxQty = Math.max(1, ...d.items.map((i) => i.qty));
  const top = d.items.slice(0, 3);
  const weak = [...d.items].sort((a, b) => a.qty - b.qty).slice(0, 3).filter((i) => !top.includes(i));
  return (
    <div className="page">
      <div className="page-head">
        <h1>Day End Report</h1>
        <span className="muted">{longDate(d.date)}{isToday && ' · today so far'}</span>
        <span className="grow" />
        {!isToday && <button className="btn sm" onClick={() => setDate(today())}>Back to today</button>}
        <input type="date" style={{ width: 170 }} value={date} max={today()} onChange={(e) => e.target.value && setDate(e.target.value)} aria-label="Pick a date" />
      </div>
      <div className="dash">
        <div className="span-4 stack">
          <SalesCalendar selected={date} onSelect={setDate} refreshKey={rev} />
          <div className="card panel">
            <h3>{isToday ? 'What worked today' : 'What worked'}</h3>
            {top.length ? <ul className="steps">{top.map((i) => <li key={i.name}><b>{i.name}</b>: {i.qty} sold, {inr(i.revenue)}</li>)}</ul> : <div className="muted small">No sales on this day.</div>}
            {weak.length > 0 && <>
              <h3 style={{ marginTop: 14 }}>Sold the least</h3>
              <ul className="steps">{weak.map((i) => <li key={i.name}>{i.name}: {i.qty}</li>)}</ul>
            </>}
          </div>
        </div>

        <div className="span-8 stack">
          <div className="card panel">
            <div className="stats num" style={{ marginTop: 0 }}>
              <div className="stat"><div className="k">Sales</div><div className="v">{inr(d.revenue)}</div></div>
              <div className="stat"><div className="k">Bills</div><div className="v">{d.orders}</div>{d.cancelled.n > 0 && <div className="s">+ {d.cancelled.n} cancelled ({inr(d.cancelled.amount)})</div>}</div>
              <div className="stat"><div className="k">Average bill</div><div className="v">{inr(d.aov)}</div></div>
              <div className="stat"><div className="k">Cash / UPI / Card</div><div className="v" style={{ fontSize: 15, marginTop: 6 }}>
                {['cash', 'upi', 'card'].map((m) => inr(d.payments.find((p) => p.method === m)?.amount || 0)).join(' / ')}</div></div>
            </div>
          </div>

          <div className="card panel">
            <h3>Items sold</h3>
            {!d.items.length ? <div className="muted">No sales on this day.</div> : (
              <table className="tbl num">
                <thead><tr><th>Item</th><th>Category</th><th className="r">Qty</th><th className="r">Orders</th><th className="r">Revenue</th><th style={{ width: 100 }} /></tr></thead>
                <tbody>{d.items.map((i) => (
                  <tr key={i.name}><td><b>{i.name}</b></td><td className="muted">{i.category}</td><td className="r">{i.qty}</td><td className="r">{i.orders}</td><td className="r">{inr(i.revenue)}</td>
                    <td><div className="bar-inline"><div style={{ width: `${(i.qty / maxQty) * 100}%` }} /></div></td></tr>
                ))}</tbody>
              </table>
            )}
          </div>

          <div className="card panel">
            <h3>Not sold at all ({d.notSold.length})</h3>
            {d.notSold.length ? <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>{d.notSold.map((i) => <span key={i.name} className="pill warn">{i.name}</span>)}</div>
              : <div className="muted small">Every item on the menu sold at least once. 🎉</div>}
            {d.notSold.length > 0 && <p className="small muted" style={{ marginBottom: 0 }}>If an item keeps showing up here for a couple of weeks, consider replacing it or adding it to a combo.</p>}
          </div>
        </div>

        <div className="card panel span-12">
          <div className="panel-head">
            <h3>Bills ({orders.length})</h3>
            <a className="btn sm" href={`#bills?from=${date}&to=${date}`}>Open in Bills, with older days ›</a>
          </div>
          {!orders.length ? <div className="muted small">No bills on this day.</div> : (
            <div className="scroll" style={{ maxHeight: 440 }}>
              <table className="tbl num bills-tbl">
                <thead><tr><th>Bill</th><th>Time</th><th>Items</th><th>Type</th><th>Pay</th><th className="r">Total</th><th /></tr></thead>
                <tbody>{orders.map((o) => {
                  const s = itemsSummary(o.items);
                  return (
                    <tr key={o.id} className={`click${o.status === 'cancelled' ? ' cancelled' : ''}`} onClick={() => setOpen(o)} tabIndex={0}
                      onKeyDown={(e) => { if (e.key === 'Enter') setOpen(o); }}>
                      <td className="nowrap"><b>{o.bill_no}</b></td><td className="nowrap">{o.created_at.slice(11, 16)}</td>
                      <td className="bill-items">{s.text}{s.more > 0 && <span className="muted"> +{s.more} more</span>}</td>
                      <td className="small nowrap">{o.order_type}</td><td className="small nowrap">{o.payment_method.toUpperCase()}</td>
                      <td className="r nowrap"><b className="bill-total">{inr(o.total)}</b></td>
                      <td className="r nowrap">{o.status === 'paid'
                        ? <button className="btn ghost sm danger" onClick={(e) => { e.stopPropagation(); cancel(o); }}>Cancel</button>
                        : <span className="pill bad">Cancelled</span>}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      {open && <BillDetail order={open} notify={notify} onClose={() => setOpen(null)}
        onCancelled={(o) => { setOpen(o); load(); onChange(); setRev((n) => n + 1); }} />}
    </div>
  );
}
