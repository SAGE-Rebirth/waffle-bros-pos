import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api } from './api.js';

// Used until /api/config answers, and kept if it never does (older backend, offline start-up).
// They match the backend's module defaults and the POS's behaviour before modules existed.
export const DEFAULT_MODULES = {
  shop: {
    enabled: true,
    settings: {
      shop_name: 'Waffle Bros', shop_address: 'Bhopal', shop_phone: '',
      receipt_footer: 'Thank you! Come back for more waffles', logo: null, open_hour: 10, close_hour: 23,
    },
  },
  theme: { enabled: true, settings: { primary: '#F6B92B', dark: '#4A2C1A', accent: '#B97A10', background: '#FFFDF6' } },
  billing: {
    enabled: true,
    settings: {
      payment_methods: ['upi', 'cash', 'card'], default_payment: 'upi',
      order_types: ['dine-in', 'takeaway', 'delivery'], customer_capture: true, print_on_save: false,
    },
  },
  targets: {
    enabled: true,
    settings: {
      default_target: 100000, slow_mover_pct: 5, low_margin_pct: 55,
      expense_categories: ['rent', 'salary', 'ingredients', 'electricity', 'packaging', 'marketing', 'maintenance', 'other'],
    },
  },
  gst: { enabled: false, settings: { rate: 5, gstin: '' } },
  discounts: { enabled: true, settings: { max_discount_pct: 20 } },
  google_sheets: { enabled: false, settings: { interval_minutes: 5, web_app_url: '', last_sync: '' } },
  whatsapp: { enabled: false, settings: {} },
};

function merge(remote) {
  const out = {};
  const keys = new Set([...Object.keys(DEFAULT_MODULES), ...Object.keys(remote || {})]);
  for (const k of keys) {
    const d = DEFAULT_MODULES[k] || { enabled: false, settings: {} };
    const r = remote?.[k] || {};
    out[k] = { enabled: r.enabled ?? d.enabled, settings: { ...d.settings, ...(r.settings || {}) } };
  }
  return out;
}

// ---------- theme ----------
const HEX = /^#?([0-9a-f]{6})$/i;
const toRgb = (hex) => { const m = HEX.exec(hex || ''); if (!m) return null; const n = parseInt(m[1], 16); return [n >> 16, (n >> 8) & 255, n & 255]; };
const toHex = (rgb) => '#' + rgb.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
// w = share of colour a.
const mix = (a, b, w) => toHex(a.map((v, i) => v * w + b[i] * (1 - w)));
const WHITE = [255, 255, 255], BLACK = [0, 0, 0];

export function themeVars(t) {
  const d = DEFAULT_MODULES.theme.settings;
  const primary = toRgb(t?.primary) || toRgb(d.primary);
  const dark = toRgb(t?.dark) || toRgb(d.dark);
  const accent = toRgb(t?.accent) || toRgb(d.accent);
  const bg = toRgb(t?.background) || toRgb(d.background);
  return {
    '--yellow': toHex(primary),
    '--yellow-soft': mix(primary, WHITE, 0.23),
    '--yellow-tint': mix(primary, WHITE, 0.09),
    '--yellow-hover': mix(primary, WHITE, 0.85),
    '--ring': `rgba(${primary.join(', ')}, 0.25)`,
    '--choc': toHex(dark),
    '--choc-2': mix(dark, accent, 0.75),
    '--honey': toHex(accent),
    '--honey-dark': mix(accent, BLACK, 0.75),
    '--cream': toHex(bg),
  };
}

function applyTheme(t) {
  const root = document.documentElement.style;
  for (const [k, v] of Object.entries(themeVars(t))) root.setProperty(k, v);
}

// ---------- context ----------
const ConfigContext = createContext(null);

export function ConfigProvider({ children }) {
  const [state, setState] = useState({ modules: merge(null), version: null, default_pin: false, pin_length: 0, loaded: false, error: null });

  const reload = useCallback(async () => {
    try {
      const c = await api.get('/api/config');
      setState({ modules: merge(c.modules), version: c.version ?? null, default_pin: !!c.default_pin, pin_length: Number(c.pin_length) || 0, loaded: true, error: null });
    } catch (e) {
      // Keep whatever we had (defaults on first load) so billing still works.
      setState((s) => ({ ...s, loaded: true, error: e.message }));
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => { applyTheme(state.modules.theme?.settings); }, [state.modules.theme]);
  useEffect(() => {
    const name = state.modules.shop?.settings?.shop_name;
    if (name) document.title = `${name} POS`;
  }, [state.modules.shop]);

  const value = useMemo(() => {
    const m = state.modules;
    return {
      ...state,
      reload,
      enabled: (key) => !!m[key]?.enabled,
      settings: (key) => m[key]?.settings || {},
    };
  }, [state, reload]);

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig() {
  const c = useContext(ConfigContext);
  if (!c) throw new Error('useConfig must be used inside <ConfigProvider>');
  return c;
}
