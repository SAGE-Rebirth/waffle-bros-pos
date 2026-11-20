import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { adminApi, adminDownload, adminSession, adminText, api, inr, today, EMOJI, SIGNED_OUT_EVENT } from '../api.js';
import { useConfig } from '../config.jsx';

// ---------- images ----------
// Shrinks an uploaded menu photo to a small 4:3 JPEG so the database stays light.
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
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL('image/jpeg', 0.82));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

// Fits an image (logo etc.) inside max x max, keeping its shape. PNG keeps transparency.
function toImage(file, max = 256) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(img.width * s)); c.height = Math.max(1, Math.round(img.height * s));
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      const png = /png|svg|webp|gif/i.test(file.type);
      resolve(png ? c.toDataURL('image/png') : c.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

// ---------- PIN sign-in ----------
// How many digits the PIN has, remembered on this device after a successful sign-in or PIN change,
// so the pad shows the right number of dots (4 to 8). Never the PIN itself.
const PIN_LEN_KEY = 'wb-pin-length';
const knownPinLength = () => {
  try { const n = Number(localStorage.getItem(PIN_LEN_KEY)); return n >= 4 && n <= 8 ? n : null; } catch { return null; }
};
const rememberPinLength = (n) => {
  try { if (n) localStorage.setItem(PIN_LEN_KEY, String(n)); else localStorage.removeItem(PIN_LEN_KEY); } catch { /* private mode */ }
};

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'];

function PinScreen({ onSignedIn }) {
  const [pin, setPin] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);
  const [known, setKnown] = useState(knownPinLength);
  const slots = Math.max(known || 4, pin.length);

  const submit = useCallback(async (p) => {
    if (p.length < 4 || busy) return;
    setBusy(true); setErr('');
    try {
      const r = await api.post('/api/admin/login', { pin: p });
      rememberPinLength(p.length);
      onSignedIn(r);
    } catch (e) {
      setErr(e.status === 401 ? 'Wrong PIN. Try again.' : e.message);
      // The PIN may have been changed on another device to a different length: stop auto sign-in.
      if (e.status === 401 && known) { rememberPinLength(null); setKnown(null); }
      setPin(''); setShake(true); setTimeout(() => setShake(false), 400);
    }
    setBusy(false);
  }, [busy, onSignedIn, known]);

  const press = useCallback((k) => {
    setErr('');
    if (k === 'back') setPin((p) => p.slice(0, -1));
    else if (k === 'clear') setPin('');
    else setPin((p) => (p.length < 8 ? p + k : p));
  }, []);

  // Once the PIN length is known on this device, sign in as soon as the last digit is entered.
  useEffect(() => { if (known && pin.length === known) submit(pin); }, [pin, known]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const h = (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (/^\d$/.test(e.key)) press(e.key);
      else if (e.key === 'Backspace') press('back');
      else if (e.key === 'Escape') press('clear');
      else if (e.key === 'Enter') submit(pin);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [press, submit, pin]);

  return (
    <div className="page pin-page">
      <div className={`card pin-card${shake ? ' shake' : ''}`}>
        <div className="pin-lock" aria-hidden="true">🔐</div>
        <h1>Admin sign-in</h1>
        <p className="small muted">Enter the admin PIN to change the menu, modules and settings.</p>
        <div className="pin-dots" aria-label={`${pin.length} of ${slots} digits entered`}>
          {Array.from({ length: slots }, (_, i) => <span key={i} className={i < pin.length ? 'on' : ''} />)}
        </div>
        <div className="err pin-err" role="alert">{err || ' '}</div>
        <div className="keypad">
          {KEYS.map((k) => (
            <button key={k} type="button" className={k.length > 1 ? 'fn' : ''} onClick={() => press(k)} disabled={busy}
              aria-label={k === 'back' ? 'Delete last digit' : k === 'clear' ? 'Clear' : k}>
              {k === 'back' ? '⌫' : k === 'clear' ? 'C' : k}
            </button>
          ))}
        </div>
        <button className="btn primary pin-go" disabled={pin.length < 4 || busy} onClick={() => submit(pin)}>
          {busy ? 'Checking…' : 'Sign in'}
        </button>
        <p className="small muted" style={{ marginBottom: 0 }}>
          {known ? 'Signs in when the last digit is entered. You can also type the PIN.' : 'PINs are 4 to 8 digits. Type or tap, then press Enter.'}
        </p>
      </div>
    </div>
  );
}

// ---------- change PIN ----------
function ChangePin({ onChanged, compact }) {
  const [p1, setP1] = useState('');
  const [p2, setP2] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const digits = (v) => v.replace(/\D/g, '').slice(0, 8);
  const valid = /^\d{4,8}$/.test(p1);
  const save = async (e) => {
    e.preventDefault();
    if (!valid) { setErr('The PIN must be 4 to 8 digits.'); return; }
    if (p1 !== p2) { setErr('The two PINs do not match.'); return; }
    if (p1 === '1234') { setErr('Pick a PIN other than 1234.'); return; }
    setBusy(true); setErr('');
    try {
      const r = await adminApi.post('/api/admin/pin', { new_pin: p1 });
      rememberPinLength(p1.length);
      setP1(''); setP2('');
      onChanged(r);
    } catch (ex) { if (ex.status !== 401) setErr(ex.message); }
    setBusy(false);
  };
  return (
    <form className={compact ? 'pin-form compact' : 'pin-form'} onSubmit={save}>
      <label className="field">New PIN
        <input type="password" inputMode="numeric" autoComplete="new-password" value={p1} onChange={(e) => { setP1(digits(e.target.value)); setErr(''); }} placeholder="4–8 digits" />
      </label>
      <label className="field">Confirm new PIN
        <input type="password" inputMode="numeric" autoComplete="new-password" value={p2} onChange={(e) => { setP2(digits(e.target.value)); setErr(''); }} />
      </label>
      <button className="btn primary" disabled={busy || !p1 || !p2}>{busy ? 'Saving…' : 'Change PIN'}</button>
      {err && <p className="err full" style={{ margin: 0 }}>{err}</p>}
    </form>
  );
}

// ---------- Menu ----------
function ItemModal({ item, categories, onClose, onSaved }) {
  const [f, setF] = useState(item);
  const [err, setErr] = useState('');
  const save = async () => {
    try {
      const body = {
        code: f.code, name: f.name, category_id: f.category_id, price: Number(f.price), cost: Number(f.cost || 0),
        image: f.image || null, veg: !!f.veg, active: !!f.active,
      };
      if (f.id) await adminApi.put(`/api/items/${f.id}`, body); else await adminApi.post('/api/items', body);
      onSaved();
    } catch (e) { if (e.status !== 401) setErr(e.message); }
  };
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>{f.id ? 'Edit item' : 'New item'}</h2>
        <div className="form-grid">
          <label className="field">Item ID<input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} placeholder="W10" /></label>
          <label className="field">Category
            <select value={f.category_id ?? ''} onChange={(e) => setF({ ...f, category_id: Number(e.target.value) })}>
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
          <label className="row small"><input type="checkbox" style={{ width: 'auto' }} checked={!!f.veg} onChange={(e) => setF({ ...f, veg: e.target.checked })} /> Veg</label>
          <label className="row small"><input type="checkbox" style={{ width: 'auto' }} checked={!!f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} /> Show on billing screen</label>
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

const move = (arr, i, d) => {
  const j = i + d;
  if (j < 0 || j >= arr.length) return arr;
  const a = [...arr];
  [a[i], a[j]] = [a[j], a[i]];
  return a;
};

function UpDown({ first, last, onMove, label }) {
  return (
    <span className="updown">
      <button className="btn ghost sm" disabled={first} onClick={() => onMove(-1)} aria-label={`Move ${label} up`} title="Move up">▲</button>
      <button className="btn ghost sm" disabled={last} onClick={() => onMove(1)} aria-label={`Move ${label} down`} title="Move down">▼</button>
    </span>
  );
}

function CategoryRow({ c, idx, total, count, onMove, onRename, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  useEffect(() => setName(c.name), [c.name]);
  const done = async () => {
    const n = name.trim();
    if (n && n !== c.name && !(await onRename(c, n))) return;
    if (!n) setName(c.name);
    setEditing(false);
  };
  return (
    <li className="cat-row">
      <UpDown first={idx === 0} last={idx === total - 1} onMove={(d) => onMove(idx, d)} label={c.name} />
      <span className="cat-emoji" aria-hidden="true">{EMOJI[c.name] || '🍽️'}</span>
      {editing ? (
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={60}
          onKeyDown={(e) => { if (e.key === 'Enter') done(); if (e.key === 'Escape') { setName(c.name); setEditing(false); } }} />
      ) : <b className="cat-name">{c.name}</b>}
      <span className="muted small">{count} item{count === 1 ? '' : 's'}</span>
      <span className="grow" />
      {editing ? (
        <>
          <button className="btn primary sm" onClick={done}>Save</button>
          <button className="btn ghost sm" onClick={() => { setName(c.name); setEditing(false); }}>Cancel</button>
        </>
      ) : (
        <>
          <button className="btn sm" onClick={() => setEditing(true)}>Rename</button>
          <button className="btn ghost sm danger" onClick={() => onDelete(c, count)}
            title={count ? 'Move or delete its items first' : 'Delete category'}>Delete</button>
        </>
      )}
    </li>
  );
}

function MenuTab({ notify }) {
  const [menu, setMenu] = useState({ categories: [], items: [] });
  const [editing, setEditing] = useState(null);
  const [newCat, setNewCat] = useState('');
  const [err, setErr] = useState('');
  const load = useCallback(() => api.get('/api/menu').then(setMenu).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);

  // Every write: report errors (401 already sends us back to the PIN screen), then reload.
  const run = async (fn, ok) => {
    setErr('');
    try { const r = await fn(); if (ok) notify(typeof ok === 'function' ? ok(r) : ok); return true; }
    catch (e) { if (e.status !== 401) { setErr(e.message); notify(e.message); } return false; }
    finally { load(); }
  };

  const byCat = useMemo(() => {
    const m = new Map(menu.categories.map((c) => [c.id, []]));
    for (const i of menu.items) { if (!m.has(i.category_id)) m.set(i.category_id, []); m.get(i.category_id).push(i); }
    return m;
  }, [menu]);

  const remove = (i) => window.confirm(`Remove ${i.name}?`) &&
    run(() => adminApi.del(`/api/items/${i.id}`), (r) => (r.hidden ? `${i.name} hidden (it has past sales)` : `${i.name} deleted`));
  const addCat = async () => { if (await run(() => adminApi.post('/api/categories', { name: newCat.trim() }), `Category "${newCat.trim()}" added`)) setNewCat(''); };
  const renameCat = (c, name) => run(() => adminApi.put(`/api/categories/${c.id}`, { name }), `Renamed to ${name}`);
  const deleteCat = (c, count) => {
    if (count) { setErr(`"${c.name}" still has ${count} item${count === 1 ? '' : 's'}. Move them to another category or delete them first.`); return; }
    if (window.confirm(`Delete the category "${c.name}"?`)) run(() => adminApi.del(`/api/categories/${c.id}`), `${c.name} deleted`);
  };
  const moveCat = (idx, d) => {
    const cats = move(menu.categories, idx, d);
    setMenu((m) => ({ ...m, categories: cats }));
    run(() => adminApi.post('/api/categories/reorder', { ids: cats.map((c) => c.id) }));
  };
  const moveItem = (catId, idx, d) => {
    const list = move(byCat.get(catId) || [], idx, d);
    setMenu((m) => {
      const others = m.items.filter((i) => i.category_id !== catId);
      return { ...m, items: [...others, ...list] };
    });
    run(() => adminApi.post('/api/items/reorder', { ids: list.map((i) => i.id) }));
  };

  const blank = { code: '', name: '', category_id: menu.categories[0]?.id, price: '', cost: '', image: null, veg: true, active: true };
  return (
    <div className="admin-menu">
      {err && <div className="banner bad" role="alert"><span>⚠️</span><span>{err}</span><button className="btn ghost sm" onClick={() => setErr('')}>Dismiss</button></div>}
      <div className="card panel">
        <div className="panel-head">
          <h3>Categories ({menu.categories.length})</h3>
          <form className="row" onSubmit={(e) => { e.preventDefault(); if (newCat.trim()) addCat(); }}>
            <input placeholder="New category" value={newCat} onChange={(e) => setNewCat(e.target.value)} style={{ width: 180 }} maxLength={60} />
            <button className="btn sm" disabled={!newCat.trim()}>Add category</button>
          </form>
        </div>
        <ul className="cat-list">
          {menu.categories.map((c, idx) => (
            <CategoryRow key={c.id} c={c} idx={idx} total={menu.categories.length} count={(byCat.get(c.id) || []).length}
              onMove={moveCat} onRename={renameCat} onDelete={deleteCat} />
          ))}
          {!menu.categories.length && <li className="muted small">No categories yet. Add one to start your menu.</li>}
        </ul>
      </div>

      <div className="card panel">
        <div className="panel-head">
          <h3>Menu items ({menu.items.length})</h3>
          <button className="btn primary sm" disabled={!menu.categories.length} onClick={() => setEditing(blank)}>+ New item</button>
        </div>
        <table className="tbl num">
          <thead><tr><th style={{ width: 70 }}>Order</th><th /><th>ID</th><th>Name</th><th className="r">Price</th><th className="r">Cost</th><th className="r">Margin</th><th>Status</th><th /></tr></thead>
          {menu.categories.map((c) => {
            const list = byCat.get(c.id) || [];
            return (
              <tbody key={c.id}>
                <tr className="group-row"><td colSpan={9}>{EMOJI[c.name] || '🍽️'} {c.name} <span className="muted">· {list.length}</span></td></tr>
                {list.map((i, idx) => (
                  <tr key={i.id}>
                    <td><UpDown first={idx === 0} last={idx === list.length - 1} onMove={(d) => moveItem(c.id, idx, d)} label={i.name} /></td>
                    <td><div className="thumb">{i.image ? <img src={i.image} alt="" /> : EMOJI[i.category] || '🧇'}</div></td>
                    <td><b>{i.code}</b></td><td>{i.name}</td>
                    <td className="r">{inr(i.price)}</td><td className="r muted">{i.cost ? inr(i.cost) : '—'}</td>
                    <td className="r">{i.cost && i.price ? `${Math.round(((i.price - i.cost) / i.price) * 100)}%` : '—'}</td>
                    <td>{i.active ? <span className="pill good">On menu</span> : <span className="pill">Hidden</span>}</td>
                    <td className="r" style={{ whiteSpace: 'nowrap' }}>
                      <button className="btn sm" onClick={() => setEditing(i)}>Edit</button>{' '}
                      <button className="btn ghost sm danger" onClick={() => remove(i)}>Remove</button>
                    </td>
                  </tr>
                ))}
                {!list.length && <tr><td colSpan={9} className="muted small">No items in this category.</td></tr>}
              </tbody>
            );
          })}
        </table>
      </div>
      {editing && <ItemModal item={editing} categories={menu.categories} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); notify('Menu saved'); }} />}
    </div>
  );
}

// ---------- Schema-driven settings form ----------
function deref(spec, root, seen = 0) {
  if (!spec || seen > 10) return spec || {};
  if (spec.$ref) {
    const m = /^#\/(\$defs|definitions)\/(.+)$/.exec(spec.$ref);
    const target = m ? root?.[m[1]]?.[decodeURIComponent(m[2])] : null;
    const { $ref, ...rest } = spec;
    return deref({ ...(target || {}), ...rest }, root, seen + 1);
  }
  if (Array.isArray(spec.allOf) && spec.allOf.length === 1) {
    const { allOf, ...rest } = spec;
    return deref({ ...deref(allOf[0], root, seen + 1), ...rest }, root, seen + 1);
  }
  const alts = spec.anyOf || spec.oneOf;
  if (Array.isArray(alts)) {
    const nonNull = alts.filter((a) => a.type !== 'null');
    const nullable = nonNull.length < alts.length;
    if (nonNull.length === 1) {
      const { anyOf, oneOf, ...rest } = spec;
      return { ...deref(nonNull[0], root, seen + 1), ...rest, nullable: nullable || undefined };
    }
  }
  if (Array.isArray(spec.type)) {
    const t = spec.type.filter((x) => x !== 'null');
    return { ...spec, type: t[0], nullable: t.length < spec.type.length || undefined };
  }
  return spec;
}

function kindOf(s, root) {
  if (s.format === 'color') return 'color';
  if (s.format === 'image') return 'image';
  if (Array.isArray(s.enum)) return 'enum';
  if (s.const !== undefined) return 'const';
  if (s.type === 'array') {
    const it = deref(s.items, root);
    if (Array.isArray(it?.enum)) return 'multi';
    return 'tags';
  }
  if (s.type === 'boolean') return 'bool';
  if (s.type === 'integer' || s.type === 'number') return 'number';
  return 'text';
}

const LABELS = { upi: 'UPI', 'dine-in': 'Dine-in' };
const optLabel = (v) => LABELS[v] ?? (typeof v === 'string' && v ? v[0].toUpperCase() + v.slice(1) : String(v));

function Toggle({ checked, onChange, disabled, label }) {
  return (
    <button type="button" role="switch" aria-checked={!!checked} aria-label={label} disabled={disabled}
      className={`switch${checked ? ' on' : ''}`} onClick={() => onChange(!checked)}>
      <span />
    </button>
  );
}

function TagEditor({ value, onChange, disabled, id }) {
  const [txt, setTxt] = useState('');
  const list = Array.isArray(value) ? value : [];
  const add = () => {
    const parts = txt.split(',').map((x) => x.trim()).filter(Boolean).filter((x) => !list.includes(x));
    if (parts.length) onChange([...list, ...parts]);
    setTxt('');
  };
  return (
    <div className={`tags${disabled ? ' disabled' : ''}`}>
      {list.map((t) => (
        <span className="tag" key={t}>{t}
          {!disabled && <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(list.filter((x) => x !== t))}>×</button>}
        </span>
      ))}
      {!disabled && (
        <span className="tag-add">
          <input id={id} value={txt} placeholder="Add…" onChange={(e) => setTxt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); }
              else if (e.key === 'Backspace' && !txt && list.length) onChange(list.slice(0, -1));
            }}
            onBlur={() => txt.trim() && add()} />
          <button type="button" className="btn sm" disabled={!txt.trim()} onClick={add}>Add</button>
        </span>
      )}
    </div>
  );
}

function ColorField({ value, onChange, disabled, id }) {
  const [txt, setTxt] = useState(value || '');
  useEffect(() => setTxt(value || ''), [value]);
  const valid = /^#[0-9a-f]{6}$/i.test(value || '');
  return (
    <div className="row color-field">
      <input type="color" aria-label="Pick colour" disabled={disabled} value={valid ? value.toLowerCase() : '#000000'}
        onChange={(e) => onChange(e.target.value.toUpperCase())} />
      <input id={id} className="hex num" disabled={disabled} value={txt} maxLength={7} spellCheck={false}
        onChange={(e) => {
          let v = e.target.value.trim();
          if (v && v[0] !== '#') v = '#' + v;
          setTxt(v);
          if (/^#[0-9a-f]{6}$/i.test(v)) onChange(v.toUpperCase());
        }}
        onBlur={() => setTxt(value || '')} />
    </div>
  );
}

function ImageField({ value, onChange, disabled, id }) {
  const ref = useRef(null);
  const [err, setErr] = useState('');
  return (
    <div className="row image-field">
      <div className="thumb logo-preview">{value ? <img src={value} alt="" /> : <span className="muted small">None</span>}</div>
      {!disabled && (
        <>
          <input id={id} ref={ref} type="file" accept="image/*" hidden
            onChange={async (e) => {
              const f = e.target.files[0];
              e.target.value = '';
              if (!f) return;
              try { setErr(''); onChange(await toImage(f, 256)); } catch { setErr('That file is not an image we can read.'); }
            }} />
          <button type="button" className="btn sm" onClick={() => ref.current?.click()}>{value ? 'Replace…' : 'Upload…'}</button>
          {value && <button type="button" className="btn ghost sm danger" onClick={() => onChange(null)}>Remove</button>}
        </>
      )}
      {err && <span className="err">{err}</span>}
    </div>
  );
}

function SchemaField({ name, spec, root, value, onChange, readOnly, error }) {
  const s = deref(spec, root);
  const kind = kindOf(s, root);
  const idRef = useRef(`f-${name}-${Math.random().toString(36).slice(2, 7)}`).current;
  const label = s.title || optLabel(name.replace(/_/g, ' '));
  let control;
  switch (kind) {
    case 'bool':
      control = <Toggle checked={!!value} onChange={onChange} disabled={readOnly} label={label} />;
      break;
    case 'number': {
      const min = s.minimum ?? (s.exclusiveMinimum !== undefined ? s.exclusiveMinimum : undefined);
      const max = s.maximum ?? s.exclusiveMaximum;
      control = (
        <input id={idRef} type="number" className="num" disabled={readOnly} value={value ?? ''} min={min} max={max}
          step={s.type === 'integer' ? 1 : 'any'} onChange={(e) => onChange(e.target.value)} />
      );
      break;
    }
    case 'enum':
      control = (
        <select id={idRef} disabled={readOnly} value={value ?? ''} onChange={(e) => onChange(e.target.value === '' && s.nullable ? null : e.target.value)}>
          {(s.nullable || value == null) && <option value="">—</option>}
          {s.enum.map((o) => <option key={String(o)} value={o}>{optLabel(o)}</option>)}
        </select>
      );
      break;
    case 'const':
      control = <input id={idRef} disabled value={String(s.const)} />;
      break;
    case 'multi': {
      const opts = deref(s.items, root).enum;
      const list = Array.isArray(value) ? value : [];
      control = (
        <div className="checks">
          {opts.map((o) => (
            <label key={String(o)} className={`check${list.includes(o) ? ' on' : ''}`}>
              <input type="checkbox" disabled={readOnly} checked={list.includes(o)}
                onChange={(e) => onChange(e.target.checked ? opts.filter((x) => x === o || list.includes(x)) : list.filter((x) => x !== o))} />
              {optLabel(o)}
            </label>
          ))}
        </div>
      );
      break;
    }
    case 'tags':
      control = <TagEditor id={idRef} value={value} onChange={onChange} disabled={readOnly} />;
      break;
    case 'color':
      control = <ColorField id={idRef} value={value} onChange={onChange} disabled={readOnly} />;
      break;
    case 'image':
      control = <ImageField id={idRef} value={value} onChange={onChange} disabled={readOnly} />;
      break;
    default:
      control = (
        <input id={idRef} disabled={readOnly} value={value ?? ''} maxLength={s.maxLength}
          placeholder={readOnly && !value ? '—' : undefined}
          onChange={(e) => onChange(e.target.value === '' && s.nullable ? null : e.target.value)} />
      );
  }
  const inline = kind === 'bool';
  // Long text (URLs, addresses) gets the full width of the card.
  const wide = kind === 'text' && (s.maxLength ?? 0) > 100;
  return (
    <div className={`sfield sf-${kind}${inline ? ' inline' : ''}${wide ? ' wide' : ''}${error ? ' has-err' : ''}${readOnly ? ' ro' : ''}`}>
      <label htmlFor={kind === 'bool' || kind === 'multi' ? undefined : idRef} className="sf-label">
        {label}{readOnly && <span className="pill" style={{ marginLeft: 6 }}>read-only</span>}
      </label>
      {control}
      {s.description && <div className="sf-help">{s.description}</div>}
      {error && <div className="err">{error}</div>}
    </div>
  );
}

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// Turns the form's text values back into the types the schema wants.
function coerce(spec, root, v) {
  const s = deref(spec, root);
  if ((s.type === 'integer' || s.type === 'number') && typeof v === 'string') {
    if (v.trim() === '') return s.nullable ? null : v;
    const n = Number(v);
    return Number.isFinite(n) ? n : v;
  }
  return v;
}

function ModuleCard({ mod, onSaved, notify }) {
  const { reload } = useConfig();
  const schema = mod.settings_schema || {};
  const props = schema.properties || {};
  const ro = new Set(mod.readonly_fields || []);
  const isRo = (k) => ro.has(k) || deref(props[k], schema).readOnly;
  const [draft, setDraft] = useState(mod.values || {});
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [script, setScript] = useState('');
  useEffect(() => { setDraft(mod.values || {}); }, [mod.values]);

  const changed = useMemo(() => {
    const out = {};
    for (const k of Object.keys(props)) {
      if (isRo(k)) continue;
      const v = coerce(props[k], schema, draft[k]);
      if (!same(v, mod.values?.[k])) out[k] = v;
    }
    return out;
  }, [draft, mod]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = Object.keys(changed).length > 0;

  const put = async (body, msg) => {
    setBusy(true); setErr('');
    try {
      const r = await adminApi.put(`/api/admin/modules/${mod.key}`, body);
      onSaved(r);
      await reload();
      notify(msg);
      return true;
    } catch (e) {
      if (e.status !== 401) setErr(e.message);
      return false;
    } finally { setBusy(false); }
  };

  const save = () => put({ settings: changed }, `${mod.name} saved`);
  const toggle = (on) => put({ enabled: on }, `${mod.name} ${on ? 'switched on' : 'switched off'}`);
  const sync = async () => {
    if (dirty && !(await put({ settings: changed }, `${mod.name} saved`))) return;
    setSyncing(true);
    try {
      const r = await adminApi.post('/api/sync');
      notify(r.message || (r.ok ? 'Synced' : 'Sync did not run'));
      const list = await adminApi.get('/api/admin/modules');
      const fresh = list.find((m) => m.key === mod.key);
      if (fresh) onSaved(fresh);
      reload();
    } catch (e) { if (e.status !== 401) setErr(e.message); }
    setSyncing(false);
  };

  const showScript = async () => {
    try { setScript(await adminText('/api/admin/google-sheet/script')); } catch (e) { if (e.status !== 401) setErr(e.message); }
  };
  const newSecret = () => {
    const bytes = crypto.getRandomValues(new Uint8Array(18));
    const secret = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    setDraft((d) => ({ ...d, secret }));
    setErr('');
  };

  // A server error like "rate: Input should be less than or equal to 28" points at a field.
  const errField = /^([a-z_][\w]*)(?:\.\d+)?:\s/i.exec(err)?.[1];
  const fieldErr = errField && props[errField] ? err.slice(err.indexOf(':') + 1).trim() : '';

  return (
    <section className={`card module-card${mod.enabled ? '' : ' off'}`}>
      <header className="module-head">
        <div className="module-icon" aria-hidden="true">{mod.icon || '🧩'}</div>
        <div className="module-title">
          <h3>{mod.name}</h3>
          <p>{mod.description}</p>
        </div>
        {mod.core ? <span className="pill core-pill" title="Always on">Core</span>
          : <Toggle checked={mod.enabled} onChange={toggle} disabled={busy} label={`${mod.name} on or off`} />}
      </header>
      {Object.keys(props).length > 0 && (
        <div className="module-body">
          {!mod.enabled && <p className="module-note">Switched off. You can still prepare its settings.</p>}
          <div className="sform">
            {Object.entries(props).map(([k, spec]) => (
              <SchemaField key={k} name={k} spec={spec} root={schema} value={draft[k]} readOnly={isRo(k)}
                error={errField === k ? fieldErr : ''} onChange={(v) => { setDraft((d) => ({ ...d, [k]: v })); setErr(''); }} />
            ))}
          </div>
          {err && !fieldErr && <p className="err" role="alert">{err}</p>}
          {err && fieldErr && <p className="err" role="alert">Fix the highlighted field and save again.</p>}
          <div className="module-actions">
            <button className="btn primary" disabled={!dirty || busy} onClick={save}>{busy ? 'Saving…' : 'Save'}</button>
            {dirty && <button className="btn ghost" disabled={busy} onClick={() => { setDraft(mod.values || {}); setErr(''); }}>Undo changes</button>}
            {mod.key === 'google_sheets' && (
              <>
                <span className="grow" />
                <button className="btn" disabled={busy} onClick={newSecret} title="Fill in a new random secret">New secret</button>
                <button className="btn" onClick={showScript}>Setup script</button>
                <button className="btn dark" disabled={syncing || busy || !mod.enabled} onClick={sync}
                  title={mod.enabled ? 'Push new bills and expenses now' : 'Switch the module on first'}>
                  {syncing ? 'Syncing…' : 'Sync now'}
                </button>
              </>
            )}
          </div>
          {mod.key === 'google_sheets' && (
            <p className="module-status small muted">
              {mod.values?.last_sync ? `Last synced ${mod.values.last_sync}` : 'Not synced yet.'}
              {!mod.enabled && ' Switch the module on to sync.'}
            </p>
          )}
          {mod.key === 'google_sheets' && script && (
            <div className="script-box">
              <p className="small">
                In the Google Sheet: <b>Extensions → Apps Script</b>, replace everything with this script, put the
                secret above into <code>SECRET</code>, then <b>Deploy → New deployment → Web app</b> (Execute as: Me,
                Who has access: Anyone). Paste the web app URL above, save, switch on and press Sync now.
              </p>
              <textarea readOnly rows={10} value={script} onFocus={(e) => e.target.select()} aria-label="Apps Script code" />
              <button className="btn ghost" onClick={() => setScript('')}>Hide script</button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function ModulesTab({ notify, onChange }) {
  const [mods, setMods] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    adminApi.get('/api/admin/modules').then(setMods).catch((e) => { if (e.status !== 401) setErr(e.message); });
  }, []);
  const onSaved = (m) => { setMods((list) => list.map((x) => (x.key === m.key ? m : x))); onChange?.(); };
  if (err) return <div className="banner bad"><span>⚠️</span><span>Could not load modules: {err}</span></div>;
  if (!mods) return <p className="muted">Loading modules…</p>;
  return (
    <div className="module-grid">
      {mods.map((m) => <ModuleCard key={m.key} mod={m} onSaved={onSaved} notify={notify} />)}
    </div>
  );
}

// ---------- Security & backup ----------
function SecurityTab({ onPinChanged }) {
  return (
    <div className="card panel" style={{ maxWidth: 560 }}>
      <h3>Change admin PIN</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Use 4 to 8 digits. Changing the PIN signs out the admin dashboard everywhere else.</p>
      <ChangePin onChanged={onPinChanged} />
    </div>
  );
}

function BackupTab({ notify }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const download = async () => {
    setBusy(true); setErr('');
    try { await adminDownload('/api/backup', `waffle-bros-backup-${today()}.db`); notify('Backup downloaded'); }
    catch (e) { if (e.status !== 401) setErr(e.message); }
    setBusy(false);
  };
  return (
    <div className="card panel" style={{ maxWidth: 720 }}>
      <h3>Backup</h3>
      <p className="small muted">All your sales, menu and expenses live in one file on this computer. Download a copy every week to a pen drive or Google Drive.</p>
      <button className="btn primary" onClick={download} disabled={busy}>{busy ? 'Preparing…' : '⬇ Download backup'}</button>
      {err && <p className="err">{err}</p>}
    </div>
  );
}

// ---------- page ----------
const TABS = [['menu', 'Menu'], ['modules', 'Modules'], ['security', 'Security'], ['backup', 'Backup']];

export default function Admin({ notify, onChange }) {
  const { default_pin: defaultPin, reload } = useConfig();
  const [session, setSession] = useState(() => adminSession.get());
  const [tab, setTab] = useState('menu');

  useEffect(() => {
    const h = () => { setSession(null); notify('Signed out. Enter the PIN again.'); };
    window.addEventListener(SIGNED_OUT_EVENT, h);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, h);
  }, [notify]);

  // Sign out when the token expires.
  useEffect(() => {
    if (!session) return;
    const ms = Number(session.expires_at) * 1000 - Date.now();
    if (ms <= 0) { adminSession.clear(); setSession(null); return; }
    const t = setTimeout(() => { adminSession.clear(); setSession(null); }, Math.min(ms, 2 ** 31 - 1));
    return () => clearTimeout(t);
  }, [session]);

  const signIn = (s) => { adminSession.set(s); setSession(s); };
  const signOut = () => { adminSession.clear(); setSession(null); };
  const pinChanged = (r) => { signIn({ ...r, must_change_pin: false }); reload(); notify('PIN changed'); };

  if (!session) return <PinScreen onSignedIn={signIn} />;

  const needPin = session.must_change_pin || defaultPin;
  if (needPin) {
    // The server refuses other admin actions until the default PIN is changed.
    return (
      <div className="page">
        <div className="page-head"><h1>Admin</h1><span className="grow" /><button className="btn ghost sm" onClick={signOut}>🔒 Sign out</button></div>
        <div className="banner warn">
          <span aria-hidden="true">⚠️</span>
          <div style={{ flex: 1 }}>
            <b>Choose your own PIN first.</b> The default PIN (1234) is the same in every copy of this POS, so
            the admin dashboard stays locked until you change it.
            <ChangePin compact onChanged={pinChanged} />
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="page">
      <div className="page-head">
        <h1>Admin</h1>
        <div className="tabs seg" style={{ marginBottom: 0 }}>
          {TABS.map(([k, l]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        <span className="grow" />
        <button className="btn ghost sm" onClick={signOut}>🔒 Sign out</button>
      </div>
      {tab === 'menu' && <MenuTab notify={notify} />}
      {tab === 'modules' && <ModulesTab notify={notify} onChange={onChange} />}
      {tab === 'security' && <SecurityTab onPinChanged={pinChanged} />}
      {tab === 'backup' && <BackupTab notify={notify} />}
    </div>
  );
}
