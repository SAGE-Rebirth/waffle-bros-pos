import { useEffect, useState } from 'react';
import { inr, pinApi } from '../api.js';
import { Receipt } from './Receipt.jsx';
import { useConfig } from '../config.jsx';

const longWhen = (createdAt) => {
  const [d, t] = createdAt.split(' ');
  const day = new Date(`${d}T00:00:00Z`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  return `${day}, ${t.slice(0, 5)}`;
};
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// One bill in a pop-up: every line, the totals, reprint, and cancel (asks for the PIN).
export default function BillDetail({ order, onClose, onCancelled, notify }) {
  const { settings: cfg, enabled } = useConfig();
  const [printing, setPrinting] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);

  if (!order) return null;
  const cancelled = order.status === 'cancelled';
  const print = () => { setPrinting(order); setTimeout(() => window.print(), 80); };
  const cancel = async () => {
    if (!window.confirm(`Cancel bill ${order.bill_no} (${inr(order.total)})? It will be removed from sales.`)) return;
    setBusy(true);
    try {
      const updated = await pinApi.post(`/api/orders/${order.id}/cancel`, {}, `Enter the admin PIN to cancel bill ${order.bill_no}.`);
      notify(`Bill ${order.bill_no} cancelled`);
      onCancelled(updated);
    } catch (e) { if (!e.cancelled) notify(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="modal-bg" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal bill-modal" role="dialog" aria-modal="true" aria-label={`Bill ${order.bill_no}`}>
        <div className="bill-modal-head">
          <h2>{order.bill_no}</h2>
          <span className={`pill ${cancelled ? 'bad' : 'good'}`}>{cancelled ? 'Cancelled' : 'Paid'}</span>
          <span className="grow" />
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="bill-meta small">
          <span>{longWhen(order.created_at)}</span>
          <span>{cap(order.order_type)}</span>
          <span>{order.payment_method.toUpperCase()}</span>
          {order.source !== 'counter' && <span>{cap(order.source)}</span>}
        </div>
        {(order.customer_name || order.customer_phone || order.delivery_address || order.note) && (
          <div className="bill-customer small">
            {order.customer_name && <div><span className="muted">Customer</span> {order.customer_name}</div>}
            {order.customer_phone && <div><span className="muted">Phone</span> {order.customer_phone}</div>}
            {order.delivery_address && <div><span className="muted">Address</span> {order.delivery_address}</div>}
            {order.note && <div><span className="muted">Note</span> {order.note}</div>}
          </div>
        )}
        <table className="tbl num bill-lines">
          <thead><tr><th>Item</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Amount</th></tr></thead>
          <tbody>{order.items.map((i) => (
            <tr key={i.id}><td><b>{i.name}</b><div className="muted small">{i.category}</div></td>
              <td className="r">{i.qty}</td><td className="r">{inr(i.price)}</td><td className="r">{inr(i.price * i.qty)}</td></tr>
          ))}</tbody>
        </table>
        <table className="tbl num bill-totals">
          <tbody>
            <tr><td>Subtotal</td><td className="r">{inr(order.subtotal, 2)}</td></tr>
            {order.discount > 0 && <tr><td>Discount</td><td className="r">−{inr(order.discount, 2)}</td></tr>}
            {order.tax > 0 && <tr><td>GST</td><td className="r">{inr(order.tax, 2)}</td></tr>}
            <tr className="tot"><td>Total</td><td className="r">{inr(order.total, 2)}</td></tr>
          </tbody>
        </table>
        {cancelled && <p className="small muted">This bill was cancelled. It is kept for the record but not counted in sales.</p>}
        <div className="row bill-actions">
          {!cancelled && <button className="btn ghost danger" disabled={busy} onClick={cancel}>Cancel bill</button>}
          <span className="grow" />
          <button className="btn" onClick={print}>Print receipt</button>
          <button className="btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
      <Receipt order={printing} shop={cfg('shop')} gstin={enabled('gst') ? cfg('gst').gstin : ''} />
    </div>
  );
}
