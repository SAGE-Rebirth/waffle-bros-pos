import { useEffect, useState } from 'react';
import { api, inr, EMOJI } from '../api.js';

// Shrinks an uploaded photo to a small square JPEG so the database stays light.
function toThumb(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const size = 320;
      const c = document.createElement('canvas');
      c.width = size; c.height = Math.round(size * 0.75);
      const s = Math.max(c.width / img.width, c.height / img.height);
      const w = img.width * s, h = img.height * s;
      c.getContext('2d').drawImage(img, (c.width - w) / 2, (c.height - h) / 2, w, h);
      resolve(c.toDataURL('image/jpeg', 0.82));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

function ItemModal({ item, categories, onClose, onSaved }) {
  const [f, setF] = useState(item);
  const [err, setErr] = useState('');
  const save = async () => {
    try {
      const body = { ...f, price: Number(f.price), cost: Number(f.cost || 0) };
      if (f.id) await api.put(`/api/items/${f.id}`, body); else await api.post('/api/items', body);
      onSaved();
    } catch (e) { setErr(e.message); }
  };
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{f.id ? 'Edit item' : 'New item'}</h2>
        <div className="form-grid">
          <label className="field">Item ID<input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} placeholder="W10" /></label>
          <label className="field">Category
            <select value={f.category_id} onChange={(e) => setF({ ...f, category_id: Number(e.target.value) })}>
              {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="field full">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="field">Selling price ₹<input inputMode="numeric" value={f.price} onChange={(e) => setF({ ...f, price: e.target.value.replace(/[^\d.]/g, '') })} /></label>
          <label className="field">Ingredient cost ₹ <span className="muted" style={{ fontWeight: 400 }}>(optional, for margin)</span><input inputMode="numeric" value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value.replace(/[^\d.]/g, '') })} /></label>
          <div className="field full">
            Photo
            <div className="row">
              <div className="thumb" style={{ width: 80, height: 60 }}>{f.image ? <img src={f.image} alt="" /> : '🧇'}</div>
              <input type="file" accept="image/*" onChange={async (e) => e.target.files[0] && setF({ ...f, image: await toThumb(e.target.files[0]) })} />
              {f.image && <button className="btn ghost sm" onClick={() => setF({ ...f, image: null })}>Remove</button>}
            </div>
          </div>
          <label className="row small"><input type="checkbox" style={{ width: 'auto' }} checked={!!f.veg} onChange={(e) => setF({ ...f, veg: e.target.checked ? 1 : 0 })} /> Veg</label>
          <label className="row small"><input type="checkbox" style={{ width: 'auto' }} checked={!!f.active} onChange={(e) => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Show on billing screen</label>
        </div>
        {err && <p className="err">{err}</p>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 18 }}>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  );
}

function MenuTab({ notify }) {
  const [menu, setMenu] = useState({ categories: [], items: [] });
  const [editing, setEditing] = useState(null);
  const [newCat, setNewCat] = useState('');
  const load = () => api.get('/api/menu').then(setMenu);
  useEffect(() => { load(); }, []);
  const remove = async (i) => {
    if (!window.confirm(`Remove ${i.name}?`)) return;
    const r = await api.del(`/api/items/${i.id}`);
    notify(r.hidden ? `${i.name} hidden (it has past sales)` : `${i.name} deleted`);
    load();
  };
  const addCat = async () => {
    try { await api.post('/api/categories', { name: newCat }); setNewCat(''); load(); } catch (e) { notify(e.message); }
  };
  const blank = { code: '', name: '', category_id: menu.categories[0]?.id, price: '', cost: '', image: null, veg: 1, active: 1 };
  return (
    <div className="card panel">
      <div className="panel-head">
        <h3>Menu items ({menu.items.length})</h3>
        <div className="row">
          <input placeholder="New category" value={newCat} onChange={(e) => setNewCat(e.target.value)} style={{ width: 160 }} />
          <button className="btn sm" disabled={!newCat.trim()} onClick={addCat}>Add category</button>
          <button className="btn primary sm" onClick={() => setEditing(blank)}>+ New item</button>
        </div>
      </div>
      <table className="tbl num">
        <thead><tr><th /><th>ID</th><th>Name</th><th>Category</th><th className="r">Price</th><th className="r">Cost</th><th className="r">Margin</th><th>Status</th><th /></tr></thead>
        <tbody>{menu.items.map((i) => (
          <tr key={i.id}>
            <td><div className="thumb">{i.image ? <img src={i.image} alt="" /> : EMOJI[i.category] || '🧇'}</div></td>
            <td><b>{i.code}</b></td><td>{i.name}</td><td className="muted">{i.category}</td>
            <td className="r">{inr(i.price)}</td><td className="r muted">{i.cost ? inr(i.cost) : '—'}</td>
            <td className="r">{i.cost ? `${Math.round(((i.price - i.cost) / i.price) * 100)}%` : '—'}</td>
            <td>{i.active ? <span className="pill good">On menu</span> : <span className="pill">Hidden</span>}</td>
            <td className="r" style={{ whiteSpace: 'nowrap' }}>
              <button className="btn sm" onClick={() => setEditing(i)}>Edit</button>{' '}
              <button className="btn ghost sm danger" onClick={() => remove(i)}>Remove</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      {editing && <ItemModal item={editing} categories={menu.categories} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); notify('Menu saved'); }} />}
    </div>
  );
}

function ShopTab({ s, set, save }) {
  return (
    <div className="card panel" style={{ maxWidth: 720 }}>
      <h3>Shop details (printed on bills)</h3>
      <div className="form-grid">
        <label className="field">Shop name<input value={s.shop_name} onChange={(e) => set({ shop_name: e.target.value })} /></label>
        <label className="field">Phone<input value={s.shop_phone} onChange={(e) => set({ shop_phone: e.target.value })} /></label>
        <label className="field full">Address<input value={s.shop_address} onChange={(e) => set({ shop_address: e.target.value })} /></label>
        <label className="field">GSTIN<input value={s.gstin} onChange={(e) => set({ gstin: e.target.value })} placeholder="Leave blank if not registered" /></label>
        <label className="field">GST rate %<input inputMode="numeric" value={s.gst_rate} onChange={(e) => set({ gst_rate: e.target.value })} /></label>
        <label className="field">Default monthly target ₹<input inputMode="numeric" value={s.default_target} onChange={(e) => set({ default_target: e.target.value })} /></label>
        <div className="row">
          <label className="field">Opens (hour)<input inputMode="numeric" value={s.open_hour} onChange={(e) => set({ open_hour: e.target.value })} /></label>
          <label className="field">Closes (hour)<input inputMode="numeric" value={s.close_hour} onChange={(e) => set({ close_hour: e.target.value })} /></label>
        </div>
      </div>
      <div className="row" style={{ marginTop: 16 }}><button className="btn primary" onClick={save}>Save</button></div>
    </div>
  );
}

function SheetsTab({ s, set, save, notify }) {
  const [syncing, setSyncing] = useState(false);
  const sync = async () => {
    setSyncing(true);
    try { await save(); const r = await api.post('/api/sync'); notify(r.message); } catch (e) { notify(e.message); }
    setSyncing(false);
  };
  return (
    <div className="card panel" style={{ maxWidth: 820 }}>
      <h3>Google Sheet sync</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Every 5 minutes (when online) new bills, items sold and expenses are added to your sheet, and a Daily summary tab is refreshed. Billing keeps working offline; it catches up later.</p>
      <div className="form-grid">
        <label className="row small full"><input type="checkbox" style={{ width: 'auto' }} checked={s.sheets_enabled === '1'} onChange={(e) => set({ sheets_enabled: e.target.checked ? '1' : '0' })} /> Turn on sync</label>
        <label className="field full">Spreadsheet ID <span className="muted" style={{ fontWeight: 400 }}>(the long code in the sheet's URL between /d/ and /edit)</span>
          <input value={s.sheets_spreadsheet_id} onChange={(e) => set({ sheets_spreadsheet_id: e.target.value.trim() })} /></label>
        <label className="field full">Service account key file (full path on this computer)
          <input value={s.sheets_credentials_path} onChange={(e) => set({ sheets_credentials_path: e.target.value.trim() })} placeholder="C:\WaffleBros\google-key.json" /></label>
      </div>
      <div className="row" style={{ marginTop: 16 }}>
        <button className="btn primary" onClick={save}>Save</button>
        <button className="btn" onClick={sync} disabled={syncing}>{syncing ? 'Syncing…' : 'Sync now'}</button>
        <span className="small muted">{s.sheets_last_sync ? `Last synced ${s.sheets_last_sync}` : 'Not synced yet'}</span>
      </div>
      <h3 style={{ marginTop: 22 }}>One-time setup</h3>
      <ol className="steps">
        <li>Create a new Google Sheet, e.g. "Waffle Bros Sales".</li>
        <li>In Google Cloud Console, create a project, enable the <b>Google Sheets API</b>, then create a <b>service account</b> and download its JSON key.</li>
        <li>Save the key file on this computer (keep it private) and paste its path above.</li>
        <li>Share the Google Sheet with the service account's email (it ends in <code>iam.gserviceaccount.com</code>) as <b>Editor</b>.</li>
        <li>Paste the spreadsheet ID, tick "Turn on sync", and press Sync now. The tabs Orders, OrderItems, Expenses and Daily are created for you.</li>
      </ol>
    </div>
  );
}

function BackupTab() {
  return (
    <div className="card panel" style={{ maxWidth: 720 }}>
      <h3>Backup</h3>
      <p className="small muted">All your sales, menu and expenses live in one file on this computer. Download a copy every week to a pen drive or Google Drive.</p>
      <a className="btn primary" href="/api/backup" style={{ textDecoration: 'none', display: 'inline-block' }}>⬇ Download backup</a>
      <h3 style={{ marginTop: 22 }}>Coming in phase 2</h3>
      <p className="small muted" style={{ marginBottom: 0 }}>WhatsApp ordering for the apartment residents with home delivery. Orders will arrive here tagged "WhatsApp" with the flat number, and count toward your target like any other bill.</p>
    </div>
  );
}

export default function Settings({ notify, onChange }) {
  const [tab, setTab] = useState('menu');
  const [s, setS] = useState(null);
  useEffect(() => { api.get('/api/settings').then(setS); }, []);
  const set = (patch) => setS((x) => ({ ...x, ...patch }));
  const save = async () => { const r = await api.put('/api/settings', s); setS(r); notify('Settings saved'); onChange(); };
  const tabs = [['menu', 'Menu'], ['shop', 'Shop & GST'], ['sheets', 'Google Sheet'], ['backup', 'Backup']];
  return (
    <div className="page">
      <div className="page-head"><h1>Settings</h1></div>
      <div className="tabs seg">{tabs.map(([k, l]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>)}</div>
      {tab === 'menu' && <MenuTab notify={notify} />}
      {tab === 'shop' && s && <ShopTab s={s} set={set} save={save} />}
      {tab === 'sheets' && s && <SheetsTab s={s} set={set} save={save} notify={notify} />}
      {tab === 'backup' && <BackupTab />}
    </div>
  );
}
