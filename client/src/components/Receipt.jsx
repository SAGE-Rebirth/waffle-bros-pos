import { createPortal } from 'react-dom';
import { inr } from '../api.js';

// Rendered into #print-root so window.print() prints only the bill (80mm thermal size).
export function Receipt({ order, settings }) {
  if (!order) return null;
  let root = document.getElementById('print-root');
  if (!root) { root = document.createElement('div'); root.id = 'print-root'; document.body.appendChild(root); }
  const [d, t] = order.created_at.split(' ');
  return createPortal(
    <div className="receipt">
      <h1>{settings?.shop_name || 'Waffle Bros'}</h1>
      <div className="c">{settings?.shop_address}</div>
      {settings?.shop_phone && <div className="c">Ph: {settings.shop_phone}</div>}
      {settings?.gstin && <div className="c">GSTIN: {settings.gstin}</div>}
      <hr />
      <div>Bill: {order.bill_no}</div>
      <div>{d.split('-').reverse().join('/')} {t.slice(0, 5)} · {order.order_type} · {order.payment_method.toUpperCase()}</div>
      {order.customer_name && <div>Customer: {order.customer_name}</div>}
      <hr />
      <table>
        <tbody>
          {order.items.map((i) => (
            <tr key={i.id}><td>{i.name}<br />&nbsp;{i.qty} x {i.price}</td><td className="r">{(i.qty * i.price).toFixed(2)}</td></tr>
          ))}
        </tbody>
      </table>
      <hr />
      <table>
        <tbody>
          <tr><td>Subtotal</td><td className="r">{order.subtotal.toFixed(2)}</td></tr>
          {order.discount > 0 && <tr><td>Discount</td><td className="r">-{order.discount.toFixed(2)}</td></tr>}
          {order.tax > 0 && <tr><td>GST</td><td className="r">{order.tax.toFixed(2)}</td></tr>}
          <tr className="tot"><td>TOTAL</td><td className="r">{inr(order.total, 2)}</td></tr>
        </tbody>
      </table>
      <hr />
      <div className="c">Thank you! Come back for more waffles 🧇</div>
    </div>,
    root,
  );
}
