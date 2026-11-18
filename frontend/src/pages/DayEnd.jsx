import { useEffect, useState, useCallback } from 'react';
import { api, inr, today } from '../api.js';

export default function DayEnd({ notify, onChange }) {
  const [date, setDate] = useState(today());
  const [d, setD] = useState(null);
  const [orders, setOrders] = useState([]);
  const load = useCallback(() => {
    api.get(`/api/day-end?date=${date}`).then(setD).catch((e) => notify(e.message));
    api.get(`/api/orders?date=${date}`).then(setOrders).catch(() => {});
  }, [date]);
  useEffect(() => { load(); }, [load]);

  const cancel = async (o) => {
    if (!window.confirm(`Cancel bill ${o.bill_no} (${inr(o.total)})? It will be removed from sales.`)) return;
    await api.post(`/api/orders/${o.id}/cancel`);
    notify(`Bill ${o.bill_no} cancelled`);
    load(); onChange();
  };

  if (!d) return <div className="page muted">Loading…</div>;
  const maxQty = Math.max(1, ...d.items.map((i) => i.qty));
  const top = d.items.slice(0, 3);
  const weak = [...d.items].sort((a, b) => a.qty - b.qty).slice(0, 3).filter((i) => !top.includes(i));
  return (
    <div className="page">
      <div className="page-head">
        <h1>Day End Report</h1>
        <input type="date" style={{ width: 170 }} value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
      </div>
      <div className="dash">
        <div className="card panel span-12">
          <div className="stats num" style={{ marginTop: 0 }}>
            <div className="stat"><div className="k">Sales</div><div className="v">{inr(d.revenue)}</div></div>
            <div className="stat"><div className="k">Orders</div><div className="v">{d.orders}</div></div>
            <div className="stat"><div className="k">Average bill</div><div className="v">{inr(d.aov)}</div></div>
            <div className="stat"><div className="k">Cash / UPI / Card</div><div className="v small" style={{ fontSize: 15 }}>
              {['cash', 'upi', 'card'].map((m) => inr(d.payments.find((p) => p.method === m)?.amount || 0)).join(' / ')}</div>
              {d.cancelled.n > 0 && <div className="s">{d.cancelled.n} cancelled ({inr(d.cancelled.amount)})</div>}</div>
          </div>
        </div>

        <div className="card panel span-7">
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

        <div className="span-5" style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
          <div className="card panel">
            <h3>What worked today</h3>
            {top.length ? <ul className="steps">{top.map((i) => <li key={i.name}><b>{i.name}</b>: {i.qty} sold, {inr(i.revenue)}</li>)}</ul> : <div className="muted small">Nothing yet.</div>}
            {weak.length > 0 && <>
              <h3 style={{ marginTop: 14 }}>Sold the least</h3>
              <ul className="steps">{weak.map((i) => <li key={i.name}>{i.name}: {i.qty}</li>)}</ul>
            </>}
          </div>
          <div className="card panel">
            <h3>Not sold at all ({d.notSold.length})</h3>
            {d.notSold.length ? <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>{d.notSold.map((i) => <span key={i.name} className="pill warn">{i.name}</span>)}</div>
              : <div className="muted small">Every item on the menu sold at least once. 🎉</div>}
            {d.notSold.length > 0 && <p className="small muted" style={{ marginBottom: 0 }}>If an item keeps showing up here for a couple of weeks, consider replacing it or adding it to a combo.</p>}
          </div>
        </div>

        <div className="card panel span-12">
          <h3>Bills ({orders.length})</h3>
          <div className="scroll" style={{ maxHeight: 400 }}>
            <table className="tbl num">
              <thead><tr><th>Bill</th><th>Time</th><th>Items</th><th>Type</th><th>Pay</th><th className="r">Total</th><th /></tr></thead>
              <tbody>{orders.map((o) => (
                <tr key={o.id} style={o.status === 'cancelled' ? { opacity: 0.5, textDecoration: 'line-through' } : null}>
                  <td><b>{o.bill_no}</b></td><td>{o.created_at.slice(11, 16)}</td>
                  <td className="small">{o.items.map((i) => `${i.name} ×${i.qty}`).join(', ')}</td>
                  <td className="small">{o.order_type}</td><td className="small">{o.payment_method.toUpperCase()}</td>
                  <td className="r">{inr(o.total)}</td>
                  <td className="r">{o.status === 'paid' && <button className="btn ghost sm danger" onClick={() => cancel(o)}>Cancel</button>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
