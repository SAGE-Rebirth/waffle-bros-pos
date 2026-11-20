import { useEffect, useRef, useState } from 'react';
import { api, inr, today } from '../api.js';
import BillDetail from '../components/BillDetail.jsx';
import { RANGES, apiQuery, filtersQuery, itemsSummary, pageWindow, parseFilters, rangeFor, rangeKey } from '../bills.js';

const shortDate = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const hashQuery = () => (location.hash.split('?')[1] || '');

// Every bill ever made, a page at a time: quick date ranges or any dates, search, paid/cancelled.
// The filters live in the address (#bills?from=…&to=…), so Day End can link to a day's bills.
export default function Bills({ notify, onChange }) {
  const [f, setF] = useState(() => parseFilters(hashQuery(), today()));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(null);
  const [search, setSearch] = useState(f.q);
  const seq = useRef(0);

  const update = (patch) => setF((old) => ({ ...old, page: 1, ...patch }));

  // Typing in the search box waits a moment before asking the server.
  useEffect(() => {
    if (search === f.q) return undefined;
    const t = setTimeout(() => update({ q: search }), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    const want = `#bills?${filtersQuery(f)}`;
    if (location.hash !== want) history.replaceState(null, '', want);
  }, [f]);

  const load = () => {
    const mine = ++seq.current;
    setLoading(true);
    api.get(`/api/bills?${apiQuery(f)}`).then((d) => {
      if (mine !== seq.current) return; // an older request finishing late
      if (d.page > d.pages) { setF((old) => ({ ...old, page: d.pages })); return; }
      setData(d);
    }).catch((e) => notify(e.message)).finally(() => { if (mine === seq.current) setLoading(false); });
  };
  useEffect(load, [f]);

  const t = today();
  const range = rangeKey(f.from, f.to, t);
  const setDay = (k, v) => {
    const next = { ...f, [k]: v };
    if (next.from && next.to && next.from > next.to) next[k === 'from' ? 'to' : 'from'] = v;
    update({ from: next.from, to: next.to });
  };
  const rangeLabel = !f.from && !f.to ? 'all time'
    : f.from === f.to ? shortDate(f.from)
      : `${f.from ? shortDate(f.from) : 'the start'} – ${f.to ? shortDate(f.to) : 'today'}`;

  const first = data && data.total ? (data.page - 1) * data.page_size + 1 : 0;
  const last = data ? Math.min(data.total, data.page * data.page_size) : 0;
  const go = (p) => { setF((old) => ({ ...old, page: p })); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  return (
    <div className="page">
      <div className="page-head">
        <h1>Bills</h1>
        <span className="muted">{rangeLabel}</span>
      </div>

      <div className="card panel bills-filters">
        <div className="seg" role="group" aria-label="Date range">
          {RANGES.map(([k, l]) => (
            <button key={k} className={range === k ? 'active' : ''} onClick={() => update(rangeFor(k, t))}>{l}</button>
          ))}
        </div>
        <label className="bf-date"><span className="muted small">From</span>
          <input type="date" value={f.from} max={f.to || t} onChange={(e) => setDay('from', e.target.value)} /></label>
        <label className="bf-date"><span className="muted small">To</span>
          <input type="date" value={f.to} min={f.from || undefined} max={t} onChange={(e) => setDay('to', e.target.value)} /></label>
        <input className="bf-search" type="search" placeholder="Bill no., item or customer" value={search} maxLength={40}
          onChange={(e) => setSearch(e.target.value)} aria-label="Search bills" />
        <select value={f.payment} onChange={(e) => update({ payment: e.target.value })} aria-label="Payment method" className="bf-pay">
          <option value="">All payments</option><option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option>
        </select>
      </div>

      <div className="card panel">
        <div className="panel-head">
          <div className="seg" role="group" aria-label="Status">
            {[['all', 'All', data && data.paid + data.cancelled], ['paid', 'Paid', data?.paid], ['cancelled', 'Cancelled', data?.cancelled]].map(([k, l, n]) => (
              <button key={k} className={f.status === k ? 'active' : ''} onClick={() => update({ status: k })}>{l}{n != null && <span className="seg-n">{n}</span>}</button>
            ))}
          </div>
          {data && <span className="muted small num">{data.paid} paid · {inr(data.paid_total)}{loading && ' · loading…'}</span>}
        </div>

        {!data ? <div className="muted">Loading…</div> : !data.items.length ? (
          <div className="empty-bills muted">No bills{f.q.trim() ? ` matching “${f.q.trim()}”` : ''} for {rangeLabel}.{range !== 'all' && <> <button className="btn ghost sm" onClick={() => update(rangeFor('all', t))}>Search all time</button></>}</div>
        ) : (
          <div className="scroll">
            <table className="tbl num bills-tbl">
              <thead><tr><th>Bill</th><th>When</th><th>Items</th><th>Type</th><th>Pay</th><th className="r">Total</th><th /></tr></thead>
              <tbody>{data.items.map((o) => {
                const s = itemsSummary(o.items);
                const [d, tm] = o.created_at.split(' ');
                return (
                  <tr key={o.id} className={`click${o.status === 'cancelled' ? ' cancelled' : ''}`} onClick={() => setOpen(o)} tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') setOpen(o); }}>
                    <td className="nowrap"><b>{o.bill_no}</b></td>
                    <td className="nowrap">{d === t ? '' : `${shortDate(d)}, `}{tm.slice(0, 5)}</td>
                    <td className="bill-items">{s.text}{s.more > 0 && <span className="muted"> +{s.more} more</span>}</td>
                    <td className="small nowrap">{o.order_type}</td>
                    <td className="small nowrap">{o.payment_method.toUpperCase()}</td>
                    <td className="r nowrap"><b className="bill-total">{inr(o.total)}</b></td>
                    <td className="r nowrap">{o.status === 'cancelled' ? <span className="pill bad">Cancelled</span> : <span className="chev" aria-hidden="true">›</span>}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        )}

        {data && data.total > 0 && (
          <div className="pager">
            <span className="muted small num">Showing {first}–{last} of {data.total}</span>
            <span className="grow" />
            {data.pages > 1 && <div className="pager-btns num">
              <button className="btn sm" disabled={data.page <= 1} onClick={() => go(data.page - 1)}>‹ Prev</button>
              {pageWindow(data.page, data.pages).map((p, i) => (p === '…'
                ? <span key={`gap${i}`} className="muted">…</span>
                : <button key={p} className={`btn sm${p === data.page ? ' primary' : ''}`} aria-current={p === data.page ? 'page' : undefined} onClick={() => go(p)}>{p}</button>))}
              <button className="btn sm" disabled={data.page >= data.pages} onClick={() => go(data.page + 1)}>Next ›</button>
            </div>}
            <select value={f.size} onChange={(e) => update({ size: Number(e.target.value) })} aria-label="Bills per page" className="pager-size">
              {[25, 50, 100].map((n) => <option key={n} value={n}>{n} per page</option>)}
            </select>
          </div>
        )}
      </div>

      {open && <BillDetail order={open} notify={notify} onClose={() => setOpen(null)}
        onCancelled={(o) => { setOpen(o); load(); onChange(); }} />}
    </div>
  );
}
