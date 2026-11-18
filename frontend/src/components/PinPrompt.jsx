import { useEffect, useRef, useState } from 'react';
import { adminSession, api, PIN_NEEDED_EVENT } from '../api.js';

// Asks for the admin PIN when a counter action needs it (cancel a bill, expenses, targets).
// Any part of the app can open it with requirePin() from api.js.
export default function PinPrompt() {
  const [ask, setAsk] = useState(null); // { reason, resolve, reject }
  const [pin, setPin] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  useEffect(() => {
    const h = (e) => { setAsk(e.detail); setPin(''); setErr(''); };
    window.addEventListener(PIN_NEEDED_EVENT, h);
    return () => window.removeEventListener(PIN_NEEDED_EVENT, h);
  }, []);
  useEffect(() => { if (ask) input.current?.focus(); }, [ask]);

  if (!ask) return null;
  const close = () => { ask.reject(Object.assign(new Error('PIN not entered'), { status: 401, cancelled: true })); setAsk(null); };
  const submit = async (e) => {
    e.preventDefault();
    if (pin.length < 4 || busy) return;
    setBusy(true); setErr('');
    try {
      const r = await api.post('/api/admin/login', { pin });
      adminSession.set(r);
      ask.resolve(r);
      setAsk(null);
    } catch (e2) {
      setErr(e2.status === 401 ? 'Wrong PIN. Try again.' : e2.message);
      setPin('');
    }
    setBusy(false);
  };

  return (
    <div className="modal-bg" onClick={close}>
      <form className="modal pin-modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>🔐 Admin PIN needed</h2>
        <p className="small muted">{ask.reason || 'This needs the admin PIN.'}</p>
        <input ref={input} type="password" inputMode="numeric" autoComplete="off" maxLength={8} value={pin}
          aria-label="Admin PIN" onChange={(e) => { setPin(e.target.value.replace(/\D/g, '')); setErr(''); }} />
        <div className="err" role="alert">{err || ' '}</div>
        <div className="row">
          <button type="button" className="btn ghost" onClick={close}>Cancel</button>
          <span className="grow" />
          <button className="btn primary" disabled={pin.length < 4 || busy}>{busy ? 'Checking…' : 'Continue'}</button>
        </div>
      </form>
    </div>
  );
}
