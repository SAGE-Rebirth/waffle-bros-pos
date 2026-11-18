import { useEffect, useMemo, useState } from 'react';
import { api, inr, EMOJI } from '../api.js';
import { Receipt } from '../components/Receipt.jsx';

export default function Billing({ onOrder, notify, goSettings }) {
  const [menu, setMenu] = useState({ categories: [], items: [] });
  const [settings, setSettings] = useState({});
  const [cat, setCat] = useState('all');
  const [q, setQ] = useState('');
  const [cart, setCart] = useState([]); // [{item, qty}]
  const [pay, setPay] = useState('upi');
  const [type, setType] = useState('dine-in');
  const [discount, setDiscount] = useState('');
  const [showCustomer, setShowCustomer] = useState(false);
  const [customer, setCustomer] = useState({ name: '', phone: '' });
  const [busy, setBusy] = useState(false);
  const [printOrder, setPrintOrder] = useState(null);
  const [lastOrder, setLastOrder] = useState(null);

  useEffect(() => {
    api.get('/api/menu').then(setMenu).catch((e) => notify(e.message));
    api.get('/api/settings').then(setSettings).catch(() => {});
  }, []);

  const active = menu.items.filter((i) => i.active);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return active.filter((i) => (cat === 'all' || i.category_id === cat) && (!s || i.name.toLowerCase().includes(s) || i.code.toLowerCase().includes(s)));
  }, [active, cat, q]);

  const add = (item) => setCart((c) => {
    const ex = c.find((l) => l.item.id === item.id);
    return ex ? c.map((l) => (l === ex ? { ...l, qty: l.qty + 1 } : l)) : [...c, { item, qty: 1 }];
  });
  const setQty = (id, qty) => setCart((c) => (qty <= 0 ? c.filter((l) => l.item.id !== id) : c.map((l) => (l.item.id === id ? { ...l, qty } : l))));
  const clear = () => { setCart([]); setDiscount(''); setCustomer({ name: '', phone: '' }); setShowCustomer(false); };

  const subtotal = cart.reduce((s, l) => s + l.item.price * l.qty, 0);
  const disc = Math.min(subtotal, Math.max(0, Number(discount) || 0));
  const gst = Number(settings.gst_rate || 0);
  const tax = Math.round((subtotal - disc) * gst) / 100;
  const total = subtotal - disc + tax;
  const qtyOf = (id) => cart.find((l) => l.item.id === id)?.qty || 0;

  const charge = async (print) => {
    if (!cart.length || busy) return;
    setBusy(true);
    try {
      const order = await api.post('/api/orders', {
        items: cart.map((l) => ({ item_id: l.item.id, qty: l.qty })),
        payment_method: pay, order_type: type, discount: disc,
        customer_name: customer.name || null, customer_phone: customer.phone || null,
      });
      setLastOrder(order);
      clear();
      onOrder();
      notify(`Bill ${order.bill_no} saved · ${inr(order.total)}`);
      if (print) { setPrintOrder(order); setTimeout(() => window.print(), 80); }
    } catch (e) { notify(e.message); }
    setBusy(false);
  };

  // Keyboard: type an item ID (e.g. W05) in search and press Enter to add it. Ctrl+Enter charges.
  const onSearchKey = (e) => {
    if (e.key === 'Enter') {
      const exact = active.find((i) => i.code.toLowerCase() === q.trim().toLowerCase()) || (shown.length === 1 ? shown[0] : null);
      if (exact) { add(exact); setQ(''); }
    }
  };
  useEffect(() => {
    const h = (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) charge(true); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  });

  const catName = cat === 'all' ? 'All items' : menu.categories.find((c) => c.id === cat)?.name;

  return (
    <div className="billing">
      <aside className="cats">
        <div className="label">Menu</div>
        <button className={cat === 'all' ? 'active' : ''} onClick={() => setCat('all')}>
          ⭐ All <span className="count">{active.length}</span>
        </button>
        {menu.categories.map((c) => (
          <button key={c.id} className={cat === c.id ? 'active' : ''} onClick={() => setCat(c.id)}>
            {EMOJI[c.name] || '🍽️'} {c.name} <span className="count">{active.filter((i) => i.category_id === c.id).length}</span>
          </button>
        ))}
        <div className="grow" />
        <button onClick={goSettings}>⚙️ Settings</button>
      </aside>

      <section className="menu-pane">
        <div className="menu-head">
          <h2>{catName}</h2>
          <input placeholder="Search or type item ID + Enter" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onSearchKey} autoFocus />
        </div>
        <div className="grid">
          {shown.map((i) => (
            <button key={i.id} className="item" onClick={() => add(i)}>
              {qtyOf(i.id) > 0 && <span className="qty-badge">{qtyOf(i.id)}</span>}
              <div className="img">{i.image ? <img src={i.image} alt="" /> : EMOJI[i.category] || '🧇'}</div>
              <div className="name">{i.name}</div>
              <div className="meta">
                <span className="price num">{inr(i.price)}</span>
                <span className="row" style={{ gap: 6 }}>{i.veg ? <span className="veg" title="Veg" /> : null}<span className="code">{i.code}</span></span>
              </div>
            </button>
          ))}
          {!shown.length && <div className="muted" style={{ padding: 20 }}>No items match.</div>}
        </div>
      </section>

      <aside className="invoice">
        <div className="inv-head">
          <h2>Current order</h2>
          {cart.length > 0 ? <button className="btn ghost sm" onClick={clear}>Clear</button>
            : lastOrder && <button className="btn sm" onClick={() => { setPrintOrder(lastOrder); setTimeout(() => window.print(), 80); }}>Reprint {lastOrder.bill_no.split('-')[1]}</button>}
        </div>
        <div className="inv-lines">
          {!cart.length && <div className="inv-empty"><div className="big">🧇</div>Tap items to start a bill</div>}
          {cart.map((l) => (
            <div className="line" key={l.item.id}>
              <div><div className="n">{l.item.name}</div><div className="p num">{l.item.code} · {inr(l.item.price)}</div></div>
              <div className="stepper">
                <button onClick={() => setQty(l.item.id, l.qty - 1)} aria-label="Less">−</button>
                <span className="num">{l.qty}</span>
                <button onClick={() => setQty(l.item.id, l.qty + 1)} aria-label="More">+</button>
              </div>
              <div className="t num">{inr(l.item.price * l.qty)}</div>
            </div>
          ))}
        </div>
        <div className="inv-foot">
          <div className="seg" style={{ width: '100%' }}>
            {['dine-in', 'takeaway', 'delivery'].map((t) => (
              <button key={t} style={{ flex: 1 }} className={type === t ? 'active' : ''} onClick={() => setType(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
            ))}
          </div>
          {showCustomer ? (
            <div className="row">
              <input placeholder="Customer name" value={customer.name} onChange={(e) => setCustomer({ ...customer, name: e.target.value })} />
              <input placeholder="Phone" inputMode="tel" value={customer.phone} onChange={(e) => setCustomer({ ...customer, phone: e.target.value })} />
            </div>
          ) : (
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <button className="btn ghost sm" onClick={() => setShowCustomer(true)}>+ Customer</button>
              <label className="row small muted" style={{ gap: 6 }}>Discount ₹<input style={{ width: 80, padding: '5px 8px' }} inputMode="numeric" value={discount} onChange={(e) => setDiscount(e.target.value.replace(/[^\d.]/g, ''))} /></label>
            </div>
          )}
          <div className="sum num">
            <div><span>Items ({cart.reduce((s, l) => s + l.qty, 0)})</span><span>{inr(subtotal)}</span></div>
            {disc > 0 && <div><span>Discount</span><span>−{inr(disc)}</span></div>}
            {gst > 0 && <div><span>GST {gst}%</span><span>{inr(tax, 2)}</span></div>}
            <div className="total"><span>Order amount</span><span>{inr(total, gst > 0 ? 2 : 0)}</span></div>
          </div>
          <div className="pay">
            {[['upi', 'UPI'], ['cash', 'Cash'], ['card', 'Card']].map(([k, l]) => (
              <button key={k} className={pay === k ? 'active' : ''} onClick={() => setPay(k)}>{l}</button>
            ))}
          </div>
          <div className="charge">
            <button className="btn" disabled={!cart.length || busy} onClick={() => charge(false)}>Save</button>
            <button className="btn dark" disabled={!cart.length || busy} onClick={() => charge(true)} title="Ctrl + Enter">Save & Print</button>
          </div>
        </div>
      </aside>
      <Receipt order={printOrder} settings={settings} />
    </div>
  );
}
