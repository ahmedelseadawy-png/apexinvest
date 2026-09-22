/* ApexInvest mobile web app.
 *
 * PRESENTATION ONLY. Every number, signal, level and score shown here is returned by the
 * existing ApexInvest Python engine through the existing FastAPI (/v1/*). This file contains
 * no indicator, strategy, scoring, entry/stop/target or recommendation logic.
 * (The only arithmetic is the desktop app's own "position size" calculator, ported as-is.)
 * Secrets never live here: the browser only ever holds the optional access key the user types.
 */
(() => {
'use strict';

/* ------------------------------------------------------------------ helpers */
const $ = (s, r = document) => r.querySelector(s);
const enc = encodeURIComponent;
const safeLS = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'hidden') e[k] = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  add(e, kids);
  return e;
}
function add(e, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    e.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
  return e;
}
const ICONS = {
  analyze: '<svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></svg>',
  scanner: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/></svg>',
  watch: '<svg viewBox="0 0 24 24"><path d="M12 3l2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 16.9 6.6 19.8l1.1-6.1L3.2 9.4l6.1-.8z"/></svg>',
  portfolio: '<svg viewBox="0 0 24 24"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2M3 13h18"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>',
  back: '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M15 18l-6-6 6-6"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7"/></svg>',
  chev: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M6 9l6 6 6-6"/></svg>',
  right: '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M9 6l6 6-6 6"/></svg>',
  upload: '<svg viewBox="0 0 24 24" width="30" height="30"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>',
  check: '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M5 12l5 5 9-10"/></svg>',
  x: '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  journal: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M5 3h11a3 3 0 013 3v15H8a3 3 0 01-3-3z"/><path d="M9 8h6M9 12h6"/></svg>',
  valid: '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/></svg>',
};
function icon(name) { const t = document.createElement('template'); t.innerHTML = ICONS[name] || ''; return t.content.firstChild; }

/* --------------------------------------------------------------- i18n/state */
const I18N = window.APEX_I18N;
const S = {
  lang: safeLS.get('apex_m_lang', 'en') === 'ar' ? 'ar' : 'en',
  theme: safeLS.get('apex_theme', 'dark') === 'light' ? 'light' : 'dark',
  nav: 0,              // navigation token to drop stale async results
  res: null,           // last analysis {kind, symbol, objective, data}
  tab: 'details',
  names: {},           // symbol -> company name (learned from API responses)
  imp: null,           // import wizard state
  scan: {},            // remembered scan controls/results
  installEvt: null,
  auth: { required: false, ok: false },
};
const t = (k) => (I18N[S.lang] && I18N[S.lang][k]) || I18N.en[k] || k;
const OBJECTIVES = ['swing', 'long_term', 'day', 'income', 'analyze'];
const STRAT_ORDER = ['price_action', 'trend', 'momentum', 'macd', 'rsi', 'poc', 'breakout', 'accumulation', 'fundamental'];
const WATCHLIST = ['VLMR','SVCE','MCRO','BONY','ELEC','NCCW','ALUM','EFID','CIRA','UEGC','ETEL','OCDI','RAYA','ETRS','EXPA','SAUD','CIEB','TAQA','COSG','CCAP','ELKA','FWRY','COPR','HELI','JUFO','DOMT','KRDI','GBCO','MASR','MOED','MHOT','ADPC','ORWE','AMER','COMI'];
const QUICK = ['ABUK', 'CCAP', 'RAYA', 'MCRO', 'IEEC', 'UEGC'];

function applyLangTheme() {
  const r = document.documentElement;
  r.lang = S.lang; r.dir = S.lang === 'ar' ? 'rtl' : 'ltr'; r.dataset.theme = S.theme;
  const m = document.querySelector('meta[name="theme-color"]');
  if (m) m.content = S.theme === 'light' ? '#f2f6f7' : '#0d1417';
}

const fmt = (n, dp) => {
  if (n == null || n === '' || !isFinite(n)) return '—';
  const v = Number(n);
  const d = dp != null ? dp : (Math.abs(v) < 1 ? 4 : 2);
  return v.toLocaleString('en-US', { minimumFractionDigits: Math.min(2, d), maximumFractionDigits: d });
};
const pct = (n, dp = 2) => (n == null || !isFinite(n)) ? '—' : `${Number(n).toFixed(dp)}%`;
const cap = (s) => s ? String(s).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '—';
const actionClass = (a) => ({ BUY: 'buy', WAIT: 'wait', AVOID: 'avoid' }[String(a).toUpperCase()] || '');
const biasClass = (b) => ({ long: 'buy', short: 'avoid' }[b] || '');
const toast = (msg) => {
  document.querySelectorAll('.toast').forEach((x) => x.remove());
  const el = h('div', { class: 'toast', role: 'status' }, msg); document.body.append(el);
  setTimeout(() => el.remove(), 2600);
};
const debounce = (fn, ms) => { let id; return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); }; };

/* ---------------------------------------------------------------------- API */
class ApiError extends Error { constructor(code, message, status) { super(message); this.code = code; this.status = status; } }
/* API base: '' = same server that served this page (default, works on any domain). Set PUBLIC_API_BASE on the
   server only if the API lives on another host; it is delivered by /m/config.js. Never hard-code a domain here. */
const API = String((window.APEX_CONFIG && window.APEX_CONFIG.API_BASE) || '').replace(/\/+$/, '');
/* Key check goes in a header (never in the URL, so it can't end up in server/proxy logs). */
const checkKey = (k) => fetch(API + '/v1/assets/search?q=A', { headers: { 'X-Apex-Key': k } }).then((r) => r.ok);
const keyGet = () => safeLS.get('apex_access_key', '') || '';

async function api(path, { method = 'GET', body, retries } = {}) {
  const tries = (retries != null ? retries : (method === 'GET' ? 2 : 0));
  let last;
  for (let i = 0; i <= tries; i++) {
    try {
      const headers = { Accept: 'application/json' };
      const k = keyGet(); if (k) headers['X-Apex-Key'] = k;
      if (typeof body === 'string') headers['Content-Type'] = 'application/json';
      const res = await fetch(API + path, { method, headers, body });
      if (res.ok) return await res.json();
      let detail = ''; try { detail = (await res.json()).detail || ''; } catch {}
      if (typeof detail !== 'string') detail = JSON.stringify(detail);
      if (res.status === 401) { safeLS.del('apex_access_key'); S.auth.ok = false; showLogin(); throw new ApiError('auth', detail || t('err_auth'), 401); }
      if (res.status === 404) throw new ApiError('nodata', detail, 404);
      if (res.status === 422) throw new ApiError('invalid', detail, 422);
      last = new ApiError('server', detail || `HTTP ${res.status}`, res.status);
    } catch (e) {
      if (e instanceof ApiError && (e.code === 'auth' || e.code === 'nodata' || e.code === 'invalid')) throw e;
      last = e instanceof ApiError ? e : new ApiError('offline', String(e && e.message || e));
    }
    if (i < tries) await new Promise((r) => setTimeout(r, 600 * (i + 1)));
  }
  throw last;
}
const errText = (e) => e.code === 'nodata' ? t('err_nodata') : e.code === 'offline' ? t('err_offline') : e.code === 'auth' ? t('err_auth') : (e.message && e.code === 'invalid' ? e.message : `${t('err_server')}${e.message ? ' (' + e.message + ')' : ''}`);

/* ------------------------------------------------------------------- shell */
const view = () => $('#view');
function setHeader({ title, back, actions } = {}) {
  const hdr = $('#hdr'); hdr.replaceChildren();
  if (back) hdr.append(h('button', { class: 'back', 'aria-label': t('back'), onclick: () => (history.length > 1 ? history.back() : (location.hash = '#/analyze')) }, icon('back')));
  else hdr.append(h('div', { class: 'brand' }, h('span', { class: 'logo' }, 'A'), h('span', null, 'ApexInvest')));
  if (back) hdr.append(h('div', { class: 'title' }, title || ''));
  else hdr.append(h('div', { class: 'grow' }));
  (actions || []).forEach((a) => hdr.append(a));
}
const NAV = [['analyze', 'nav_analyze', '#/analyze'], ['scanner', 'nav_scanner', '#/scanner'], ['watch', 'nav_watch', '#/watchlist'], ['portfolio', 'nav_portfolio', '#/portfolio'], ['more', 'nav_more', '#/more']];
function setNav(active) {
  const nav = $('#nav'); nav.replaceChildren();
  NAV.forEach(([ic, key, href]) => nav.append(h('button', { 'aria-current': ic === active ? 'page' : null, onclick: () => { location.hash = href; } }, icon(ic), h('span', null, t(key)))));
}
function card(title, ...kids) { return h('section', { class: 'card' }, title ? h('h3', null, title) : null, kids); }
function pill(text, cls) { return h('span', { class: 'pill ' + (cls || '') }, text); }
const stat = (k, v, cls) => h('div', { class: 'stat' }, h('span', { class: 'k' }, k), h('span', { class: 'v num ' + (cls || '') }, v));
function loading(msg) { return h('div', { class: 'card row' }, h('div', { class: 'spin' }), h('div', null, msg)); }
function errorBox(e, retry) {
  return h('div', { class: 'card' }, h('div', { class: 'notice err' }, errText(e)), retry ? h('button', { class: 'btn', onclick: retry }, t('retry')) : null);
}
function backTo(hash) { location.hash = hash; }

/* ----------------------------------------------------------------- routing */
async function route() {
  if (S.auth.required && !S.auth.ok) return showLogin();
  const hash = location.hash || '#/analyze';
  const parts = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent);
  const [name, a, b] = parts;
  S.nav++;
  window.scrollTo(0, 0);
  const v = view(); v.replaceChildren();
  switch (name) {
    case 'dash': return a === 'csv' ? screenDash('csv') : screenDash('feed', (a || '').toUpperCase(), b || 'swing');
    case 'import': return screenImport();
    case 'scanner': return screenScan(false);
    case 'watchlist': return screenScan(true);
    case 'portfolio': return screenPortfolio();
    case 'more': return screenMore();
    case 'journal': return screenJournal();
    case 'validation': return screenValidation();
    case 'settings': return screenSettings();
    default: return screenAnalyze();
  }
}

/* --------------------------------------------------------------- ANALYZE */
function objSeg(current, onpick) {
  const seg = h('div', { class: 'seg', role: 'tablist', 'aria-label': t('objective') });
  OBJECTIVES.forEach((o) => seg.append(h('button', { role: 'tab', 'aria-selected': String(o === current), onclick: () => { onpick(o); [...seg.children].forEach((c, i) => c.setAttribute('aria-selected', String(OBJECTIVES[i] === o))); } }, t('obj_' + o))));
  return seg;
}
function screenAnalyze() {
  setHeader(); setNav('analyze');
  let obj = safeLS.get('apex_m_obj', 'swing'); if (!OBJECTIVES.includes(obj)) obj = 'swing';
  const results = h('div', { class: 'list' });
  const input = h('input', { class: 'input', type: 'search', inputmode: 'search', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', placeholder: t('search_ph'), 'aria-label': t('search_ph'), enterkeyhint: 'search' });
  const go = (sym) => { safeLS.set('apex_m_obj', obj); location.hash = `#/dash/${enc(sym)}/${obj}`; };
  const doSearch = debounce(async () => {
    const q = input.value.trim(); const tok = S.nav;
    if (!q) { results.replaceChildren(); return; }
    results.replaceChildren(h('div', { class: 'empty small' }, t('searching')));
    try {
      const d = await api('/v1/assets/search?q=' + enc(q), { retries: 1 });
      if (tok !== S.nav) return;
      const rows = (d.results || []).slice(0, 25);
      rows.forEach((r) => { S.names[r.symbol] = r.name; });
      results.replaceChildren(...(rows.length ? rows.map((r) => h('button', { class: 'item', onclick: () => go(r.symbol) },
        h('div', { class: 'grow' }, h('div', { class: 'sym' }, r.symbol), h('div', { class: 'small muted', style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, r.name)),
        r.asset_class === 'index' ? pill('INDEX') : null, h('span', { class: 'chev' }, icon('right')))) : [h('div', { class: 'empty small' }, t('no_results'))]));
    } catch (e) { if (tok === S.nav) results.replaceChildren(errorBox(e, doSearch)); }
  }, 220);
  input.addEventListener('input', doSearch);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && input.value.trim()) { e.preventDefault(); go(input.value.trim().toUpperCase()); } });
  const analyzeBtn = h('button', { class: 'btn primary', onclick: () => { const q = input.value.trim().toUpperCase(); if (q) go(q); else input.focus(); } }, t('analyze_btn'));
  view().append(
    h('div', { class: 'hero' }, h('h1', null, t('title_analyze')), h('p', { class: 'muted small' }, t('sub_analyze'))),
    h('div', { class: 'card' }, input,
      h('div', { class: 'lbl', style: 'margin:12px 0 6px' }, t('objective')), objSeg(obj, (o) => { obj = o; }),
      analyzeBtn,
      h('div', { class: 'lbl', style: 'margin:14px 0 8px' }, t('try_label')),
      h('div', { class: 'chips' }, QUICK.map((s) => h('button', { class: 'chip', onclick: () => go(s) }, s)))),
    results,
    h('div', { class: 'card' }, h('div', { class: 'small muted', style: 'margin-bottom:10px' }, t('or_import')),
      h('button', { class: 'btn', onclick: () => { S.imp = Object.assign(S.imp || {}, { sym: input.value.trim().toUpperCase() || (S.imp && S.imp.sym) || '', obj }); location.hash = '#/import'; } }, icon('upload'), t('import_btn'))));
}

/* ---------------------------------------------------------------- IMPORT */
function screenImport() {
  setHeader({ title: t('import_title'), back: true }); setNav('analyze');
  const st = S.imp = Object.assign({ file: null, sym: '', obj: 'swing', status: 'idle', info: '', rows: 0 }, S.imp || {});
  const box = h('div');
  const draw = () => {
    box.replaceChildren();
    const fileIn = h('input', { type: 'file', accept: '.csv,.tsv,.xlsx,.xls,text/csv', 'aria-label': t('choose_file'), onchange: (e) => pick(e.target.files[0]) });
    box.append(h('label', { class: 'upload' + (st.file ? ' has' : '') }, fileIn, icon('upload'),
      h('div', { style: 'font-weight:700;margin-top:6px;overflow-wrap:anywhere' }, st.file ? st.file.name : t('choose_file')),
      h('div', { class: 'tiny muted', style: 'margin-top:4px' }, t('import_sub'))));
    if (st.status === 'checking') box.append(h('div', { class: 'state checking', role: 'status' }, h('div', { class: 'spin' }), t('validating')));
    if (st.status === 'valid') box.append(h('div', { class: 'state valid', role: 'status' }, icon('valid'), h('div', null, t('data_valid'), h('span', { class: 'sub' }, `${st.rows.toLocaleString('en-US')} ${t('rows_loaded')}`))));
    if (st.status === 'error') box.append(h('div', { class: 'state error', role: 'alert' }, icon('x'), h('div', null, t('data_error'), h('span', { class: 'sub' }, st.info))));
    const symIn = h('input', { class: 'input', value: st.sym, autocapitalize: 'characters', autocomplete: 'off', spellcheck: 'false', placeholder: 'COMI', 'aria-label': t('ticker'), oninput: (e) => { st.sym = e.target.value.toUpperCase().replace(/[^A-Z0-9._-]/g, ''); e.target.value = st.sym; upd(); } });
    box.append(h('label', { class: 'field', style: 'margin-top:12px' }, h('span', { class: 'lbl' }, t('ticker')), symIn),
      h('div', { class: 'lbl', style: 'margin:4px 0 6px' }, t('objective')), objSeg(st.obj, (o) => { st.obj = o; }));
    const btn = h('button', { class: 'btn primary', id: 'anBtn', onclick: run }, t('analyze_btn'));
    box.append(btn); upd();
    function upd() { btn.disabled = !(st.status === 'valid' && st.sym.length > 0); }
  };
  async function pick(f) {
    if (!f) return;
    st.file = f; st.info = ''; st.rows = 0;
    if (!st.sym) { const m = f.name.match(/(?:EGX|CASE)[_:\- ]*([A-Z0-9]{2,8})/i); if (m) st.sym = m[1].toUpperCase(); }
    if (f.size > 15 * 1024 * 1024) { st.status = 'error'; st.info = 'File is larger than 15 MB.'; return draw(); }
    st.status = 'checking'; draw();
    const fd = new FormData(); fd.append('file', f);
    try {
      const d = await api('/v1/uploads', { method: 'POST', body: fd });
      if (d.kind === 'candles') { st.status = 'valid'; st.rows = d.candles_rows || 0; }
      else { st.status = 'error'; st.info = 'No Open/High/Low/Close columns found — this is not a candle export.'; }
    } catch (e) { st.status = 'error'; st.info = e.code === 'invalid' ? e.message : errText(e); }
    draw();
  }
  async function run() {
    const btn = $('#anBtn'); btn.disabled = true; btn.replaceChildren(h('div', { class: 'spin' }), t('analyzing'));
    const fd = new FormData(); fd.append('file', st.file); fd.append('symbol', st.sym); fd.append('objective', st.obj);
    try {
      const d = await api('/v1/analyses/csv', { method: 'POST', body: fd });
      S.res = { kind: 'csv', symbol: st.sym, objective: st.obj, data: d }; S.tab = 'details';
      location.hash = '#/dash/csv';
    } catch (e) { st.status = 'error'; st.info = errText(e); draw(); }
  }
  view().append(card(null, box)); draw();
}

/* ------------------------------------------------------------- DASHBOARD */
async function screenDash(kind, sym, obj) {
  setNav('analyze');
  if (kind === 'csv') {
    if (!S.res || S.res.kind !== 'csv') { location.hash = '#/import'; return; }
    setHeader({ title: S.res.symbol, back: true });
    return renderDash(S.res);
  }
  const reload = (fresh) => screenDash('feed', sym, obj, fresh);
  setHeader({ title: sym, back: true, actions: [h('button', { class: 'iconbtn', 'aria-label': t('refresh'), onclick: () => { S.res = null; S.nav++; view().replaceChildren(); screenDash('feed', sym, obj); } }, icon('refresh'))] });
  if (S.res && S.res.kind === 'feed' && S.res.symbol === sym && S.res.objective === obj) return renderDash(S.res);
  const tok = S.nav; view().replaceChildren(loading(`${t('analyzing')} ${sym}`));
  try {
    const data = await api(`/v1/analyses/auto/${enc(sym)}?objective=${enc(obj)}`);
    if (tok !== S.nav) return;
    S.res = { kind: 'feed', symbol: sym, objective: obj, data }; S.tab = 'details';
    renderDash(S.res);
  } catch (e) { if (tok === S.nav && e.code !== 'auth') { view().replaceChildren(errorBox(e, () => reload())); } }
}

function renderDash(res) {
  const d = res.data, p = d.plan || {}, ds = d.data_source || {}, v = view();
  const cur = ds.currency || 'EGP';
  const price = p.current_price != null ? p.current_price : ds.price;
  const asof = ds.price_as_of || ds.as_of;
  const name = S.names[res.symbol] || (d.fundamentals && d.fundamentals.available && d.fundamentals.name) || '';
  if (!name && res.kind === 'feed') api('/v1/assets/search?q=' + enc(res.symbol), { retries: 0 }).then((r) => { const m = (r.results || []).find((x) => x.symbol === res.symbol); if (m) { S.names[res.symbol] = m.name; const el = $('#coName'); if (el) el.textContent = m.name; } }).catch(() => {});
  const act = String(p.action || 'WAIT').toUpperCase(), ac = actionClass(act);

  const head = h('section', { class: 'card head' },
    h('div', { class: 'row between wrap' },
      h('div', { class: 'grow' }, h('div', { class: 'tk' }, res.symbol), h('div', { class: 'co small muted', id: 'coName', dir: 'auto' }, name)),
      h('div', { style: 'text-align:end' }, h('div', { class: 'px num' }, fmt(price)), h('div', { class: 'tiny faint' }, cur))),
    h('div', { class: 'ls', style: 'margin-top:10px' },
      pill(res.kind === 'csv' ? 'CSV IMPORT' : (ds.is_live ? 'LIVE' : 'END-OF-DAY'), res.kind === 'csv' ? 'teal' : ''),
      pill(cap(res.objective)),
      ds.freshness_label ? pill(ds.freshness_label) : null),
    h('div', { class: 'tiny muted', dir: 'auto', style: 'margin-top:8px;line-height:1.5' },
      `${t('last_update')}: `, h('b', { class: 'num' }, asof || '—'), ds.data_age_days != null ? ` (${ds.data_age_days}d)` : '', ` · ${t('source')}: ${ds.provider || ds.source || '—'}`));

  // "Why am I waiting? / What would change this?" (additive; see
  // trend_confirmation.compose_wait_context on the backend). Only populated
  // when the final action is WAIT; wc.applicable is false otherwise, and a
  // missing/older-API wait_context is handled the same as "not applicable".
  const wc = d.wait_context;
  const signal = h('section', { class: 'card signal ' + ac },
    h('div', { class: 'lbl' }, t('dash_final')), h('div', { class: 'big ' + ac }, act),
    h('div', { class: 'rs', dir: 'auto' }, p.reason || ''),
    (wc && wc.applicable && wc.why) ? h('div', { style: 'margin-top:10px' }, [
      h('div', { class: 'lbl', style: 'margin-bottom:3px' }, t('why_wait')),
      h('div', { class: 'small', dir: 'auto', style: 'line-height:1.5' }, wc.why),
      wc.next_trigger ? h('div', { class: 'tiny muted', style: 'margin-top:6px', dir: 'auto' },
        h('b', null, t('next_trigger') + ': '), wc.next_trigger) : null,
    ]) : null);

  // Long-Term Investment Plan (additive, presentation-only): shown only for the
  // "Grow long-term" objective, and only when the backend actually returned an
  // enabled long_term_plan. If the field is missing/null/disabled (older API
  // response, or not enough history), longTermCard() returns null and nothing
  // is rendered here -- the rest of the page is unaffected either way.
  const ltCard = res.objective === 'long_term' ? longTermCard(res) : null;

  // Trend & Confirmation + Trade Scenarios (additive, presentation-only):
  // shown for any objective whenever the backend has a usable read. Neither
  // ever appears when the underlying data is unavailable -- no empty cards.
  const tcCard = trendConfirmationCard(res);
  const scCard = tradeScenariosCard(res);

  const rg = d.regime;
  const regime = card(t('dash_regime'), rg ? [
    h('div', { class: 'kv' },
      kvBox(t('trend'), cap(rg.trend), rg.adx != null ? `ADX ${fmt(rg.adx, 1)}` : ''),
      kvBox(t('volatility'), cap(rg.volatility), rg.atr_pct != null ? `ATR ${pct(rg.atr_pct * 100)}` : ''),
      kvBox(t('liquidity'), cap(rg.liquidity), ''))] : h('div', { class: 'muted small' }, 'Not enough history to classify the regime (needs ≥ 30 bars).'));

  const zone = p.optimal_zone;
  const entryVal = p.entry != null ? fmt(p.entry) : (zone ? `${fmt(zone[0])}–${fmt(zone[1])}` : '—');
  const entrySub = [p.entry_type ? cap(p.entry_type) : null, (p.entry != null && zone) ? `${t('zone')} ${fmt(zone[0])}–${fmt(zone[1])}` : null].filter(Boolean).join(' · ');
  const tp1 = p.tp1 != null ? p.tp1 : p.target;
  const score = p.confidence && p.confidence.score != null ? p.confidence.score : null;
  const plan = card(t('dash_plan'),
    h('div', { class: 'kv' },
      kvBox(t('entry'), entryVal, entrySub),
      kvBox(t('stop'), fmt(p.stop), p.stop_basis || '', 'avoid'),
      kvBox(t('tp1'), fmt(tp1), p.expected_return_pct != null ? `+${pct(p.expected_return_pct)}` : '', 'buy'),
      kvBox(t('tp2'), fmt(p.tp2), p.expected_return_tp2_pct != null ? `+${pct(p.expected_return_tp2_pct)}` : '', 'buy'),
      kvBox(t('rr'), p.rr != null ? `${fmt(p.rr, 2)} : 1` : '—', p.est_time || ''),
      h('div', null, h('div', { class: 'lbl' }, t('confidence')),
        h('div', { class: 'v num', style: 'font-size:19px;font-weight:800;margin-top:3px' }, score != null ? `${score}/5` : '—'),
        h('div', { class: 'dots', 'aria-hidden': 'true' }, [1, 2, 3, 4, 5].map((i) => h('i', { class: score >= i ? 'on' : '' }))))),
    (act !== 'BUY' && p.entry == null && !zone) ? h('div', { class: 'small muted', style: 'margin-top:10px' }, t('no_plan') + (p.missing && p.missing.length ? ` Missing: ${p.missing.join(', ')}.` : '')) : null,
    act === 'BUY' ? h('div', { style: 'margin-top:10px' }, logButton(res, p)) : null);

  const conf = card(t('dash_conf'), h('div', { class: 'conf' }, STRAT_ORDER.map((id) => confRow(id, d))));

  const tabsDef = [['details', 'tab_details'], ['strategies', 'tab_strategies'], ['structure', 'tab_structure'], ['entry', 'tab_entry'], ['risk', 'tab_risk'], ['indicators', 'tab_indicators'], ['chart', 'tab_chart']];
  const tabBody = h('div');
  const seg = h('div', { class: 'seg tabs', role: 'tablist' });
  const showTab = (k) => {
    S.tab = k; [...seg.children].forEach((c, i) => c.setAttribute('aria-selected', String(tabsDef[i][0] === k)));
    tabBody.replaceChildren(); const body = TABS[k](res); tabBody.append(body);
    if (k === 'chart') requestAnimationFrame(() => drawChartFor(res));
  };
  tabsDef.forEach(([k, lab]) => seg.append(h('button', { role: 'tab', 'aria-selected': String(S.tab === k), onclick: () => showTab(k) }, t(lab))));

  v.replaceChildren(h('div', { class: 'dgrid' }, head, signal,
    tcCard ? h('div', { class: 'full' }, tcCard) : null,
    scCard ? h('div', { class: 'full' }, scCard) : null,
    ltCard ? h('div', { class: 'full' }, ltCard) : null, regime, plan, h('div', { class: 'full' }, conf), h('div', { class: 'full' }, seg, tabBody)),
    h('p', { class: 'disc' }, d.disclaimer || t('disclaimer')));
  showTab(S.tab in TABS ? S.tab : 'details');
}
function kvBox(label, value, sub, cls) {
  return h('div', null, h('div', { class: 'lbl' }, label), h('div', { class: 'v num ' + (cls || '') }, value), sub ? h('div', { class: 's', dir: 'auto' }, sub) : null);
}
/* ---- Long-Term Investment Plan (presentation-only; every value below comes
   straight from res.data.long_term_plan as the backend returns it) ---- */
function longTermCard(res) {
  const ltp = res.data.long_term_plan;
  if (!ltp || !ltp.enabled) return null;
  const outlookCls = { Constructive: 'buy', Neutral: 'wait', Weak: 'avoid' }[ltp.outlook] || '';
  const entryStatus = String(ltp.entry_status || 'WAIT').toUpperCase();
  const zones = ltp.accumulation_zones || [];
  const targets = ltp.targets || [];
  const inv = ltp.invalidation;

  return card(t('lt_title'),
    h('div', { class: 'kv two' },
      kvBox(t('lt_outlook'), ltp.outlook || '—', '', outlookCls),
      kvBox(t('lt_current_entry'), entryStatus, '', actionClass(entryStatus))),
    ltp.horizon ? h('div', { class: 'stat' }, h('span', { class: 'k' }, t('lt_horizon')),
      h('span', { class: 'v num' }, ltp.horizon.label || '—')) : null,
    zones.length ? [
      h('div', { class: 'lbl', style: 'margin:14px 0 6px' }, t('lt_accum')),
      h('div', null, zones.map((z) => h('div', { class: 'stat' },
        h('span', { class: 'k', dir: 'auto' }, z.basis || '—'),
        h('span', { class: 'v num' }, `${fmt(z.zone_low)} – ${fmt(z.zone_high)}`)))),
    ] : null,
    targets.length ? [
      h('div', { class: 'lbl', style: 'margin:14px 0 6px' }, t('lt_targets')),
      h('div', { class: 'conf' }, targets.map((tgt, i) => targetRow(tgt, i, targets.length))),
    ] : null,
    inv ? [
      h('div', { class: 'lbl', style: 'margin:14px 0 6px' }, t('lt_invalidation')),
      h('div', { class: 'stat' }, h('span', { class: 'k', dir: 'auto' }, inv.basis || '—'),
        h('span', { class: 'v num avoid' }, fmt(inv.price))),
      h('div', { class: 'tiny faint' }, cap(inv.confidence)),
    ] : null,
    ltp.thesis ? [
      h('div', { class: 'lbl', style: 'margin:14px 0 6px' }, t('lt_thesis')),
      h('div', { class: 'small muted', dir: 'auto', style: 'line-height:1.55' }, ltp.thesis),
    ] : null,
    (ltp.notes || []).length ? h('div', { class: 'tiny muted', style: 'margin-top:10px' }, ltp.notes.join(' ')) : null);
}
function targetRow(tgt, i, n) {
  const label = (i === 3 && n === 4) ? t('lt_major_target') : `${t('lt_target')} ${i + 1}`;
  const span = (tgt.estimated_horizon_min_months != null && tgt.estimated_horizon_max_months != null)
    ? `${tgt.estimated_horizon_min_months}–${tgt.estimated_horizon_max_months} ${t('lt_months')}` : '—';
  return h('div', { class: 'pc' },
    h('div', { class: 'row between' }, h('b', null, label), h('span', { class: 'num' }, fmt(tgt.target_price))),
    h('div', { class: 'row between tiny muted' },
      h('span', null, tgt.expected_return_pct != null ? `+${pct(tgt.expected_return_pct)}` : '—'),
      h('span', null, span)),
    h('div', { class: 'tiny faint', dir: 'auto' }, tgt.basis || ''),
    h('div', { class: 'tiny faint' }, cap(tgt.confidence)));
}
/* ---- Trend & Confirmation (presentation-only; values come straight from
   res.data.trend_confirmation) ---- */
function statusPillClass(val) {
  if (['Bullish', 'Confirming', 'Strong', 'Improving'].includes(val)) return 'buy';
  if (['Bearish', 'Not Confirming', 'Weak', 'Weakening', 'Overbought', 'Oversold'].includes(val)) return 'avoid';
  return '';
}
function trendConfirmationCard(res) {
  const tc = res.data.trend_confirmation;
  if (!tc || !tc.primary_trend || tc.primary_trend === 'Unavailable') return null;
  const trendCls = { Bullish: 'buy', Bearish: 'avoid' }[tc.primary_trend] || 'wait';
  const rows = [
    [t('tc_structure'), tc.structure_status], [t('tc_ema'), tc.ema_alignment],
    [t('tc_momentum'), tc.momentum_status], [t('tc_macd'), tc.macd_status],
    [t('tc_adx'), tc.adx_status], [t('tc_volume'), tc.volume_status],
    [t('tc_market'), tc.market_alignment],
  ].filter(([, val]) => val && val !== 'Unavailable');
  return card(t('tc_title'),
    h('div', { class: 'row between wrap', style: 'margin-bottom:8px' },
      h('div', null, h('div', { class: 'lbl' }, t('tc_trend')), h('div', { class: 'big ' + trendCls, style: 'font-size:20px;margin-top:2px' }, tc.primary_trend)),
      tc.confirmation_score != null ? h('div', { style: 'text-align:end' },
        h('div', { class: 'v num', style: 'font-size:19px;font-weight:800' }, `${tc.confirmation_score}/100`),
        h('div', { class: 'tiny faint' }, tc.confirmation_strength)) : null),
    h('div', { class: 'conf' }, rows.map(([label, val]) => h('div', { class: 'crow' },
      h('div', { class: 'nm' }, label), pill(val, statusPillClass(val))))),
    (tc.confirmed_factors || []).length ? h('div', { style: 'margin-top:10px' },
      h('div', { class: 'lbl', style: 'margin-bottom:5px' }, t('tc_confirmed')),
      h('div', { class: 'ls' }, tc.confirmed_factors.map((f) => pill('✓ ' + f, 'buy')))) : null,
    (tc.missing_factors || []).length ? h('div', { style: 'margin-top:8px' },
      h('div', { class: 'lbl', style: 'margin-bottom:5px' }, t('tc_missing')),
      h('div', { class: 'ls' }, tc.missing_factors.map((f) => pill('○ ' + f)))) : null,
    tc.summary ? h('div', { class: 'tiny muted', style: 'margin-top:10px;line-height:1.5', dir: 'auto' }, tc.summary) : null,
    h('div', { class: 'tiny faint', style: 'margin-top:8px' }, t('tc_disclaimer')));
}

/* ---- Trade Scenarios (presentation-only; values come straight from
   res.data.trade_scenarios) ---- */
function scenarioStateClass(state) {
  return { CONFIRMED: 'buy', VALIDATED: 'buy', TRIGGERED: 'teal', RETESTING: 'teal',
          FAILED: 'avoid', INVALIDATED: 'avoid' }[state] || '';
}
function scenarioBlock(title, statRows, state) {
  return h('div', { class: 'pc', style: 'padding:10px 0' },
    h('div', { class: 'row between' }, h('b', null, title), pill(cap(state || ''), scenarioStateClass(state))),
    h('div', null, statRows.filter(Boolean)));
}
function tradeScenariosCard(res) {
  const sc = res.data.trade_scenarios;
  if (!sc || !sc.available) return null;
  const blocks = [];
  if (sc.breakout) {
    const b = sc.breakout;
    blocks.push(scenarioBlock(t('sc_breakout'), [
      stat(t('sc_resistance'), fmt(b.resistance)),
      stat(t('sc_trigger'), b.trigger),
      b.entry != null ? stat(t('sc_entry'), fmt(b.entry)) : null,
      b.risk_stop != null ? stat(t('sc_stop'), fmt(b.risk_stop), 'avoid') : null,
    ], b.state));
  }
  if (sc.breakout_retest) {
    const r = sc.breakout_retest;
    blocks.push(scenarioBlock(t('sc_retest'), [
      stat(t('sc_zone'), `${fmt(r.retest_zone[0])}–${fmt(r.retest_zone[1])}`),
      stat(t('sc_status'), r.status),
    ], r.state));
  }
  if (sc.pullback) {
    const pb = sc.pullback;
    blocks.push(scenarioBlock(t('sc_pullback'), [
      stat(t('sc_zone'), `${fmt(pb.zone[0])}–${fmt(pb.zone[1])}`),
      stat(t('sc_basis'), pb.basis), stat(t('sc_status'), pb.status),
    ], pb.state));
  }
  if (sc.failed_breakout) {
    const fb = sc.failed_breakout;
    blocks.push(scenarioBlock(t('sc_failed'), [
      stat(t('sc_level'), fmt(fb.level)), stat(t('sc_status'), fb.status),
    ], fb.state));
  }
  if (sc.breakdown) {
    const bd = sc.breakdown;
    blocks.push(scenarioBlock(t('sc_breakdown'), [
      stat(t('sc_support'), fmt(bd.support)), stat(t('sc_trigger'), bd.trigger),
    ], bd.state));
  }
  if (!blocks.length) return null;
  return card(t('sc_title'), blocks);
}
function confRow(id, d) {
  const sig = (d.signals || []).find((s) => s.strategy_id === id);
  const skipped = ((d.auto && d.auto.skipped_need_more) || []).find((s) => s.strategy === id);
  const fund = d.fundamentals && d.fundamentals.available ? d.fundamentals : null;
  let right, note;
  if (sig) {
    right = [pill(t('bias_' + sig.bias), biasClass(sig.bias)), h('div', { class: 'bar', style: 'width:54px', title: `${t('quality')} ${Math.round(sig.quality * 100)}%` }, h('i', { style: `width:${Math.round(sig.quality * 100)}%` }))];
    note = sig.notes;
  } else if (skipped) { right = pill('N/A'); note = `${t('needs')} ${skipped.needs.map(cap).join(', ')} ${t('unavailable_feed')}`; }
  else { right = pill('—'); note = t('not_used'); }
  if (id === 'fundamental' && fund && fund.quality && fund.quality.score != null) {
    right = pill(`${fund.quality.score}/100`, fund.quality.score >= 60 ? 'buy' : fund.quality.score >= 40 ? 'wait' : 'avoid');
    note = `Company quality · ${fund.quality.coverage} coverage. ${fund.quality.note || ''}`;
  }
  return h('div', { class: 'crow' }, h('div', { class: 'nm' }, t('s_' + id), h('div', { class: 'nt', dir: 'auto' }, note)), h('div', { class: 'row', style: 'gap:8px;flex:none' }, right));
}
function logButton(res, p) {
  const b = h('button', { class: 'btn sm', onclick: () => {
    const zone = p.optimal_zone;
    addJournal({ symbol: res.symbol, objective: cap(res.objective), entry: (p.current_price != null && zone) ? zone[1] : p.entry, stop: p.stop, tp1: p.target != null ? p.target : p.tp1 });
    b.disabled = true; b.textContent = t('logged'); toast(t('logged'));
  } }, icon('journal'), t('log_trade'));
  return b;
}

/* ---- drill-down tabs (each value is straight from the engine response) ---- */
const TABS = {
  details(res) {
    const d = res.data, p = d.plan || {}, ds = d.data_source || {};
    const out = [];
    out.push(card(t('dash_final'), h('div', { dir: 'auto', style: 'font-weight:700;margin-bottom:6px' }, p.reason || ''), p.why ? h('div', { class: 'muted small', dir: 'auto', style: 'line-height:1.55' }, p.why) : null,
      p.chase ? h('div', { style: 'margin-top:10px' }, pill('Chase: ' + cap(p.chase), p.chase === 'ok' ? 'buy' : 'wait')) : null));
    if (p.missing && p.missing.length) out.push(card('Missing data', h('div', { class: 'notice warn' }, p.missing.map(cap).join(', '))));
    const cc = ds.price_crosscheck;
    out.push(card('Data source',
      stat(t('source'), ds.provider || ds.source || '—'), stat('Timeframe', ds.timeframe || '—'), stat('Bars', ds.n_candles != null ? ds.n_candles : ds.bars),
      stat('Data as of', ds.as_of || '—'), stat('Price as of', ds.price_as_of || '—'), stat('Freshness', ds.freshness_label || '—'),
      stat('Quality score', ds.quality_score != null ? `${ds.quality_score}/100` : '—'),
      ds.quality_note ? h('div', { class: 'tiny muted', style: 'padding:6px 0' }, ds.quality_note) : null,
      cc && cc.available ? h('div', { class: 'notice ' + (cc.agree ? 'ok' : 'warn'), style: 'margin:8px 0 0' }, cc.note) : null,
      d.csv_import ? [stat('File', d.csv_import.filename), stat('Rows', d.csv_import.rows), stat('Row order', d.csv_import.order)] : null));
    const auto = d.auto;
    if (auto) out.push(card('Engine selection', h('div', { class: 'small muted', style: 'margin-bottom:8px' }, 'Strategies the engine chose for this objective and which ran on this data.'),
      h('div', { class: 'ls' }, (auto.recommended || []).map((s) => pill(t('s_' + s), (auto.used || []).includes(s) ? 'teal' : ''))),
      (auto.skipped_need_more || []).length ? h('div', { class: 'tiny faint', style: 'margin-top:8px' }, 'Grey = skipped: needs data this feed cannot supply.') : null));
    if (res.kind === 'feed') out.push(backtestCard(res));
    const prov = p.provenance || [];
    if (prov.length) out.push(card('Provenance', prov.map((x) => h('div', { class: 'stat' }, h('span', { class: 'k' }, x.source), h('span', { class: 'v small' }, x.detail || '')))));
    return h('div', null, out);
  },
  strategies(res) {
    const d = res.data;
    return h('div', null, (d.signals || []).length ? d.signals.map((s) => card(t('s_' + s.strategy_id) || s.strategy_id,
      h('div', { class: 'row between wrap', style: 'margin:-2px 0 8px' }, pill(t('bias_' + s.bias), biasClass(s.bias)), h('span', { class: 'small muted' }, `${t('quality')} `, h('b', { class: 'num' }, `${Math.round(s.quality * 100)}%`))),
      h('div', { class: 'bar', style: 'margin-bottom:10px' }, h('i', { style: `width:${Math.round(s.quality * 100)}%` })),
      h('div', { dir: 'auto', style: 'line-height:1.5' }, s.notes || ''),
      s.entry_hint != null ? stat(t('entry_hint'), fmt(s.entry_hint)) : null,
      s.invalidation != null ? stat(t('invalidation'), fmt(s.invalidation)) : null,
      s.objective_level != null ? stat(t('level'), fmt(s.objective_level)) : null,
      (s.provenance || []).length ? h('div', { class: 'ls', style: 'margin-top:8px' }, s.provenance.map((x) => pill(x.source))) : null))
      : [h('div', { class: 'card empty' }, 'No strategy signals for this result.')]);
  },
  structure(res) {
    const el = (res.data.plan || {}).entry_levels || {};
    const lvl = (arr) => (arr && arr.length ? h('div', { class: 'ls' }, arr.map((x) => pill(fmt(x)))) : h('span', { class: 'muted small' }, '—'));
    const tt = el.trend_template;
    return h('div', null,
      card('Market structure', stat('Phase', el.phase_label || cap(el.phase)), stat('Weekly trend', cap(el.weekly_trend)), stat('Range', el.range_low != null ? `${fmt(el.range_low)} – ${fmt(el.range_high)}` : '—'),
        stat('Liquidity swept', el.swept == null ? '—' : (el.swept ? 'Yes' : 'No')), stat('Reclaimed', el.reclaimed == null ? '—' : (el.reclaimed ? 'Yes' : 'No')),
        stat('Volume ratio', el.volume_ratio != null ? `${fmt(el.volume_ratio, 2)}×` : '—'),
        el.distribution_warning ? h('div', { class: 'notice warn', style: 'margin:8px 0 0' }, 'Early-exit warning: ' + ((el.dist_reasons || []).join(' ') || 'distribution / supply near the highs.')) : null),
      card('Volume profile', stat('POC', fmt(el.poc), ''), stat('Value area high', fmt(el.vah)), stat('Value area low', fmt(el.val)), stat('POC confidence', cap(el.poc_confidence)),
        h('div', { class: 'lbl', style: 'margin:10px 0 6px' }, 'HVN'), lvl(el.hvn), h('div', { class: 'lbl', style: 'margin:10px 0 6px' }, 'LVN'), lvl(el.lvn),
        el.profile_note ? h('div', { class: 'tiny muted', style: 'margin-top:10px' }, el.profile_note) : null),
      card('Support / Resistance', h('div', { class: 'lbl', style: 'margin-bottom:6px' }, 'Support'), lvl(el.supports), h('div', { class: 'lbl', style: 'margin:10px 0 6px' }, 'Resistance'), lvl(el.resistances)),
      tt ? card('Trend template', stat('Result', tt.pass ? 'Pass' : 'Not met', tt.pass ? 'buy' : 'wait'), stat('Score', fmt(tt.score, 2)),
        Object.entries(tt.checks || {}).map(([k, val]) => stat(cap(k), val ? '✓' : '✗', val ? 'buy' : 'avoid'))) : null);
  },
  entry(res) {
    const p = res.data.plan || {}, zone = p.optimal_zone;
    return h('div', null, card('Entry plan',
      stat(t('entry'), fmt(p.entry)), stat(t('type_'), p.entry_type ? cap(p.entry_type) : '—'),
      stat(t('zone'), zone ? `${fmt(zone[0])} – ${fmt(zone[1])}` : '—'), stat('Confirmation entry', fmt(p.confirmation_entry)),
      stat('Current price', fmt(p.current_price)), stat('Chase', p.chase ? cap(p.chase) : '—', p.chase === 'ok' ? 'buy' : 'wait'),
      stat('Time to TP1', p.est_tp1 || p.est_time || '—'), stat('Time to TP2', p.est_tp2 || '—')),
      (p.entry_notes || []).length ? card('Notes', p.entry_notes.map((n) => h('div', { class: 'small', style: 'padding:6px 0;line-height:1.5' }, n))) : null);
  },
  risk(res) {
    const p = res.data.plan || {}, ds = res.data.data_source || {}, em = res.data.expected_move;
    const parts = ((p.confidence || {}).parts) || [];
    const tp1 = p.tp1 != null ? p.tp1 : p.target;
    return h('div', null,
      card('Risk & reward', stat(t('stop'), fmt(p.stop), 'avoid'), stat('Stop basis', p.stop_basis || '—'), stat(t('tp1'), fmt(tp1), 'buy'), stat(t('tp2'), fmt(p.tp2), 'buy'),
        stat(t('rr'), p.rr != null ? `${fmt(p.rr, 2)} : 1` : '—'),
        stat('Expected return TP1', p.expected_return_pct != null ? `+${pct(p.expected_return_pct)}` : '—'), stat('Expected return TP2', p.expected_return_tp2_pct != null ? `+${pct(p.expected_return_tp2_pct)}` : '—')),
      card(`${t('confidence')} · ${(p.confidence || {}).score != null ? p.confidence.score + '/5' : '—'}`, parts.length ? parts.map((c) => h('div', { class: 'pc' },
        h('div', { class: 'row between' }, h('b', null, cap(c.key)), h('span', { class: 'num small muted' }, `${Math.round(c.value * 100)}%`)),
        h('div', { class: 'bar' }, h('i', { style: `width:${Math.round(c.value * 100)}%` })), h('div', { class: 'tiny faint' }, c.note))) : h('div', { class: 'muted small' }, '—')),
      (p.entry != null && p.stop != null) ? sizeCard(p.entry, p.stop, ds.currency || 'EGP') : null,
      em ? card(res.objective === 'long_term' ? t('exp_move_short_term') : t('exp_move'),
        res.objective === 'long_term' ? h('div', { class: 'notice info', style: 'margin-bottom:8px' }, t('exp_move_info_note'))
          : h('div', { class: 'tiny muted', style: 'margin-bottom:8px' }, em.basis || ''),
        h('div', { class: 'tbl-wrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, ''), h('th', null, t('typical')), h('th', null, t('wide')))),
          h('tbody', null,
            h('tr', null, h('td', null, t('day')), h('td', { class: 'num' }, `${fmt(em.day.typical_low)} – ${fmt(em.day.typical_high)}`), h('td', { class: 'num' }, `${fmt(em.day.wide_low)} – ${fmt(em.day.wide_high)}`)),
            h('tr', null, h('td', null, t('week')), h('td', { class: 'num' }, `${fmt(em.week.typical_low)} – ${fmt(em.week.typical_high)}`), h('td', { class: 'num' }, `${fmt(em.week.wide_low)} – ${fmt(em.week.wide_high)}`)))))) : null);
  },
  indicators(res) {
    const d = res.data, p = d.plan || {}, rg = d.regime, el = p.entry_levels || {}, em = d.expected_move;
    return h('div', null,
      card('Regime engine', rg ? [stat(t('trend'), cap(rg.trend)), stat(t('volatility'), cap(rg.volatility)), stat(t('liquidity'), cap(rg.liquidity)), stat('ADX', fmt(rg.adx, 2)), stat('ATR', fmt(rg.atr, 4)), stat('ATR %', rg.atr_pct != null ? pct(rg.atr_pct * 100) : '—')] : h('div', { class: 'muted small' }, '—')),
      card('Indicator readings', h('div', { class: 'tiny muted', style: 'margin-bottom:6px' }, 'Values exactly as the engine reports them.'),
        (d.signals || []).map((s) => h('div', { class: 'stat' }, h('span', { class: 'k' }, t('s_' + s.strategy_id)), h('span', { class: 'v small', dir: 'auto', style: 'font-weight:600' }, s.notes))),
        p.why ? h('div', { class: 'tiny muted', style: 'padding-top:8px;line-height:1.5' }, p.why) : null),
      card('Volume profile', stat('POC', fmt(el.poc)), stat('VAH', fmt(el.vah)), stat('VAL', fmt(el.val)), stat('Volume ratio', el.volume_ratio != null ? `${fmt(el.volume_ratio, 2)}×` : '—')),
      em ? card('Volatility', stat('σ daily', pct(em.sigma_daily_pct)), stat('σ weekly', pct(em.sigma_weekly_pct)), stat('Observations', em.n_obs), h('div', { class: 'tiny muted', style: 'padding-top:6px' }, em.method)) : null);
  },
  chart(res) {
    const c = res.data.candles || [];
    return card(`${res.symbol} · ${Math.min(c.length, 90)} bars`, c.length ? [h('canvas', { class: 'chart', id: 'chartCv', role: 'img', 'aria-label': 'Price chart with entry, stop and targets' }),
      h('div', { class: 'tiny faint', style: 'margin-top:8px' }, 'Lines: Entry · Stop · TP1 · TP2 · POC (levels from the engine).')] : h('div', { class: 'muted small' }, 'No candles in this result.'));
  },
};

function backtestCard(res) {
  const out = h('div'); const btn = h('button', { class: 'btn', onclick: async () => {
    btn.disabled = true; btn.replaceChildren(h('div', { class: 'spin' }), t('analyzing'));
    try {
      const b = await api(`/v1/backtest/${enc(res.symbol)}?objective=${enc(res.objective)}`, { retries: 0 });
      const m = b.metrics || {};
      out.replaceChildren(h('div', { style: 'margin-top:10px' }, stat('Trades', m.trades), stat('Win rate', m.win_rate != null ? `${Math.round(m.win_rate * 100)}%` : '—'), stat('Avg R', fmt(m.avg_r, 2)), stat('Expectancy (R)', fmt(m.expectancy_r, 2)), stat('Profit factor', fmt(m.profit_factor, 2)), stat('Max drawdown (R)', fmt(m.max_drawdown_r, 2)), h('div', { class: 'tiny muted', style: 'padding-top:6px' }, b.method || '')));
      btn.remove();
    } catch (e) { btn.disabled = false; btn.textContent = t('backtest_this'); out.replaceChildren(h('div', { class: 'notice err', style: 'margin-top:10px' }, errText(e))); }
  } }, t('backtest_this'));
  return card('Backtest', btn, out);
}

function sizeCard(entry, stop, ccy) {
  // Ported unchanged from the desktop UI's position-size widget (UI arithmetic, not engine logic).
  let acct = safeLS.get('apex_acct', '100000'), risk = safeLS.get('apex_risk', '1');
  const out = h('div', { style: 'margin-top:10px' });
  const calc = () => {
    const m = parseFloat(acct) || 0, y = parseFloat(risk) || 0, f = m * y / 100, dd = entry - stop;
    let n = dd > 0 ? Math.floor(f / dd) : 0, capd = false;
    if (n * entry > m && entry > 0) { n = Math.floor(m / entry); capd = true; }
    out.replaceChildren(h('div', { class: 'ls' }, pill(`${n.toLocaleString('en-US')} ${t('shares')}`, 'teal')),
      stat(t('position'), `${fmt(n * entry)} ${ccy}`), stat(t('risk_at_stop'), `${fmt(n * dd)} ${ccy} (${y}%)`, 'avoid'), capd ? h('div', { class: 'tiny wait' }, 'Capped to your account size.') : null);
  };
  const mk = (label, val, cb) => h('label', { class: 'field grow' }, h('span', { class: 'lbl' }, label), h('input', { class: 'input num', inputmode: 'decimal', value: val, oninput: (e) => { e.target.value = e.target.value.replace(/[^0-9.]/g, ''); cb(e.target.value); safeLS.set('apex_acct', acct); safeLS.set('apex_risk', risk); calc(); } }));
  calc();
  return card(t('pos_size'), h('div', { class: 'row' }, mk(t('account'), acct, (v) => { acct = v; }), mk(t('risk_pct'), risk, (v) => { risk = v; })), out);
}

/* ----- chart (drawing only) ----- */
function drawChartFor(res) {
  const cv = $('#chartCv'); if (!cv) return;
  const p = res.data.plan || {}, el = p.entry_levels || {};
  const levels = [['ENTRY', p.entry, '--teal'], ['STOP', p.stop, '--avoid'], ['TP1', p.tp1 != null ? p.tp1 : p.target, '--buy'], ['TP2', p.tp2, '--buy'], ['POC', el.poc, '--gold']].filter((x) => x[1] != null);
  const draw = () => paintCandles(cv, (res.data.candles || []).slice(-90), levels);
  draw();
  if (window.ResizeObserver) { const ro = new ResizeObserver(() => draw()); ro.observe(cv); }
}
function paintCandles(cv, cs, levels) {
  if (!cs.length) return;
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  let lo = Math.min(...cs.map((c) => c.l)), hi = Math.max(...cs.map((c) => c.h));
  levels.forEach((l) => { lo = Math.min(lo, l[1]); hi = Math.max(hi, l[1]); });
  const padv = (hi - lo) * 0.06 || 1; lo -= padv; hi += padv;
  const L = 6, R = 46, T = 8, B = 8, pw = W - L - R, ph = H - T - B;
  const y = (v) => T + (hi - v) / (hi - lo) * ph, cw = pw / cs.length;
  g.font = '10px system-ui,sans-serif'; g.textBaseline = 'middle';
  g.strokeStyle = cssv('--line2'); g.fillStyle = cssv('--faint'); g.lineWidth = 1; g.setLineDash([]);
  for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4, yy = y(v); g.beginPath(); g.moveTo(L, yy); g.lineTo(L + pw, yy); g.stroke(); g.textAlign = 'left'; g.fillText(v.toFixed(v < 1 ? 3 : 2), L + pw + 4, yy); }
  const up = cssv('--buy'), dn = cssv('--avoid');
  cs.forEach((c, i) => {
    const x = L + i * cw + cw / 2, col = c.c >= c.o ? up : dn; g.strokeStyle = col; g.fillStyle = col;
    g.beginPath(); g.moveTo(x, y(c.h)); g.lineTo(x, y(c.l)); g.stroke();
    const yo = y(c.o), yc = y(c.c); g.fillRect(x - Math.max(cw * 0.32, 0.8), Math.min(yo, yc), Math.max(cw * 0.64, 1.6), Math.max(Math.abs(yo - yc), 1));
  });
  levels.forEach(([name, v, cv2]) => {
    const col = cssv(cv2), yy = y(v); g.strokeStyle = col; g.fillStyle = col; g.setLineDash([5, 4]); g.beginPath(); g.moveTo(L, yy); g.lineTo(L + pw, yy); g.stroke(); g.setLineDash([]);
    g.textAlign = 'right'; g.fillText(name, L + pw - 3, yy - 6);
  });
}

/* ------------------------------------------------------ SCANNER / WATCHLIST */
const HORIZONS = ['intraday', 'short_swing', 'medium_swing', 'long_term'], RISKS = ['conservative', 'balanced', 'aggressive'];
const SCAN_TABS = [['top10', 'c_top10'], ['top_fast', 'c_fast'], ['top_risk_adjusted', 'c_risk'], ['top_buy_now', 'c_buy_now'], ['top_pullbacks', 'c_pull'], ['top_breakouts', 'c_break']];
function screenScan(watch) {
  setHeader(); setNav(watch ? 'watch' : 'scanner');
  const key = watch ? 'watch' : 'scan';
  const st = S.scan[key] = Object.assign({ horizon: 'short_swing', risk: 'balanced', data: null, tab: 'top10', loading: false, err: null }, S.scan[key] || {});
  const opt = (arr, cur, pre) => arr.map((o) => h('option', { value: o, selected: o === cur }, t(pre + o)));
  const hz = h('select', { class: 'input', 'aria-label': t('horizon'), onchange: (e) => { st.horizon = e.target.value; st.data = null; paint(); } }, opt(HORIZONS, st.horizon, 'h_'));
  const rk = h('select', { class: 'input', 'aria-label': t('risk'), onchange: (e) => { st.risk = e.target.value; st.data = null; paint(); } }, opt(RISKS, st.risk, 'r_'));
  const body = h('div');
  async function run(refresh) {
    st.loading = true; st.err = null; paint(); const tok = S.nav;
    try {
      const qs = `horizon=${st.horizon}&risk=${st.risk}` + (watch ? `&symbols=${enc(WATCHLIST.join(','))}` : '') + (refresh ? '&refresh=true' : '');
      const d = await api('/v1/scan?' + qs, { retries: 1 });
      if (tok !== S.nav) return; st.data = d;
    } catch (e) { if (tok !== S.nav) return; st.err = e; }
    st.loading = false; paint();
  }
  function paint() {
    body.replaceChildren();
    if (st.loading) { body.append(loading(t('analyzing')), h('div', { class: 'tiny muted', style: 'padding:0 4px' }, t('scan_first'))); return; }
    if (st.err) { body.append(errorBox(st.err, () => run(false))); return; }
    if (!st.data) { body.append(h('button', { class: 'btn primary', onclick: () => run(false) }, t('scan_btn')), h('div', { class: 'tiny muted', style: 'padding:10px 4px' }, t('scan_first'))); return; }
    const d = st.data, m = d.market;
    body.append(card(null, h('div', { class: 'row between wrap' }, h('div', null, m ? h('div', null, pill(`${m.regime} · ${m.strength}`, m.regime === 'Bullish' ? 'buy' : m.regime === 'Bearish' ? 'avoid' : 'wait')) : null,
      h('div', { class: 'tiny muted', style: 'margin-top:6px' }, `${d.scanned}/${d.requested} scanned · ${d.valid_setups} setups · ${d.no_trade} no-trade · ${d.as_of}`)),
      h('button', { class: 'btn sm ghost', onclick: () => run(true) }, icon('refresh'), t('rescan')))));
    const seg = h('div', { class: 'seg', role: 'tablist' }, SCAN_TABS.map(([k, lab]) => h('button', { role: 'tab', 'aria-selected': String(st.tab === k), onclick: () => { st.tab = k; paint(); } }, `${t(lab)} (${(d[k] || []).length})`)));
    body.append(seg);
    const rows = d[st.tab] || [];
    body.append(rows.length ? h('div', null, rows.map((r) => scanRow(r, d.objective || 'swing'))) : h('div', { class: 'card empty' }, '—'));
    if ((d.not_in_catalog || []).length) body.append(h('div', { class: 'tiny muted' }, 'Not in EGX catalog: ' + d.not_in_catalog.join(', ')));
    if (d.data_note) body.append(h('p', { class: 'disc' }, d.data_note));
  }
  view().append(h('div', { class: 'hero' }, h('h1', null, t(watch ? 'watch_title' : 'scan_title'))),
    h('div', { class: 'card' }, h('div', { class: 'row' },
      h('label', { class: 'field grow', style: 'margin:0' }, h('span', { class: 'lbl' }, t('horizon')), hz), h('label', { class: 'field grow', style: 'margin:0' }, h('span', { class: 'lbl' }, t('risk')), rk))), body);
  paint();
}
function scanRow(r, objective) {
  S.names[r.symbol] = r.company || S.names[r.symbol];
  const ac = actionClass(r.action);
  return h('button', { class: 'card', style: 'display:block;width:100%;text-align:start', onclick: () => { location.hash = `#/dash/${enc(r.symbol)}/${objective}`; } },
    h('div', { class: 'row between' }, h('div', { class: 'grow' }, h('div', { class: 'sym' }, r.symbol), h('div', { class: 'tiny muted', style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, r.company || '')), pill(r.action, ac)),
    h('div', { class: 'kv', style: 'margin-top:10px' }, kvSmall(t('entry'), fmt(r.entry != null ? r.entry : null)), kvSmall(t('stop'), fmt(r.stop)), kvSmall(t('tp1'), fmt(r.tp1)), kvSmall(t('rr'), r.rr != null ? `${fmt(r.rr, 2)}:1` : '—'), kvSmall(t('conf_short'), r.confidence != null ? `${r.confidence}/5` : '—'), kvSmall('Score', r.opportunity_score != null ? fmt(r.opportunity_score, 1) : '—')),
    h('div', { class: 'ls', style: 'margin-top:8px' }, r.category ? pill(cap(r.category)) : null, r.phase ? pill(cap(r.phase)) : null, r.risk_level ? pill(r.risk_level) : null, r.chase ? pill('Chase: ' + cap(r.chase)) : null));
}
const kvSmall = (k, v) => h('div', null, h('div', { class: 'lbl' }, k), h('div', { class: 'v num', style: 'font-size:16px' }, v));

/* --------------------------------------------------------------- PORTFOLIO */
function loadHoldings() { try { const a = JSON.parse(safeLS.get('apex_holdings', '[]')); return Array.isArray(a) ? a : []; } catch { return []; } }
function screenPortfolio() {
  setHeader(); setNav('portfolio');
  let hold = loadHoldings(); const out = h('div'); const list = h('div'); let last = null;
  const save = () => safeLS.set('apex_holdings', JSON.stringify(hold));
  const sym = h('input', { class: 'input', placeholder: 'COMI', autocapitalize: 'characters', autocomplete: 'off', spellcheck: 'false', 'aria-label': t('ticker') });
  const qty = h('input', { class: 'input num', inputmode: 'decimal', placeholder: t('qty'), 'aria-label': t('qty') });
  const avg = h('input', { class: 'input num', inputmode: 'decimal', placeholder: t('avg_cost'), 'aria-label': t('avg_cost') });
  const paintList = () => list.replaceChildren(hold.length ? h('div', { class: 'list' }, hold.map((x) => h('div', { class: 'item' }, h('div', { class: 'grow' }, h('div', { class: 'sym' }, x.symbol), h('div', { class: 'small muted num' }, `${fmt(x.qty)} × ${fmt(x.avg_cost)}`)),
    h('button', { class: 'iconbtn', 'aria-label': t('remove'), onclick: () => { hold = hold.filter((y) => y.symbol !== x.symbol); save(); paintList(); } }, icon('x'))))) : h('div', { class: 'empty small' }, t('no_holdings')));
  async function analyze() {
    out.replaceChildren(loading(t('analyzing')));
    try {
      const d = await api('/v1/portfolio', { method: 'POST', body: JSON.stringify({ holdings: hold.map((x) => ({ symbol: x.symbol, qty: x.qty, avg_cost: x.avg_cost })), objective: 'swing' }), retries: 0 });
      last = d; paintOut();
    } catch (e) { out.replaceChildren(errorBox(e, analyze)); }
  }
  function paintOut() {
    if (!last) return; const s = last.summary || {}, acts = s.actions || {};
    out.replaceChildren(
      card(null, h('div', { class: 'kv' }, kvBox(t('positions'), s.positions), kvBox(t('total_value'), fmt(s.total_value)), kvBox(t('unrealized'), s.total_unrealized_pl_pct != null ? pct(s.total_unrealized_pl_pct) : '—', fmt(s.total_unrealized_pl), s.total_unrealized_pl >= 0 ? 'buy' : 'avoid')),
        h('div', { class: 'ls', style: 'margin-top:10px' }, ['HOLD', 'ADD', 'TRIM', 'EXIT'].map((a) => pill(`${a} ${acts[a] || 0}`, a === 'ADD' ? 'buy' : a === 'EXIT' ? 'avoid' : a === 'TRIM' ? 'wait' : '')))),
      (last.warnings || []).map((w) => h('div', { class: 'notice warn' }, w)),
      (last.positions || []).map((x) => h('button', { class: 'card', style: 'display:block;width:100%;text-align:start', onclick: () => { location.hash = `#/dash/${enc(x.symbol)}/swing`; } },
        h('div', { class: 'row between' }, h('div', { class: 'grow' }, h('div', { class: 'sym' }, x.symbol), h('div', { class: 'tiny muted' }, x.company || '')), pill(x.action, x.action === 'ADD' ? 'buy' : x.action === 'EXIT' ? 'avoid' : x.action === 'TRIM' ? 'wait' : 'teal')),
        h('div', { class: 'kv', style: 'margin-top:10px' }, kvSmall('Price', fmt(x.current_price)), kvSmall('P/L', pct(x.unrealized_pl_pct)), kvSmall('Weight', pct(x.weight_pct, 1)), kvSmall(t('stop'), fmt(x.suggested_stop)), kvSmall(t('tp1'), fmt(x.target)), kvSmall('Phase', cap(x.phase))),
        h('div', { class: 'small muted', dir: 'auto', style: 'margin-top:8px;line-height:1.5' }, x.action_reason || ''))),
      (last.errors || []).length ? h('div', { class: 'notice err' }, last.errors.map((e) => (typeof e === 'string' ? e : JSON.stringify(e))).join('; ')) : null,
      last.note ? h('p', { class: 'disc' }, last.note) : null);
  }
  view().append(h('div', { class: 'hero' }, h('h1', null, t('port_title')), h('p', { class: 'muted small' }, t('port_sub'))),
    card(t('add_holding'), h('div', { style: 'display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:10px' }, sym, qty, avg),
      h('button', { class: 'btn', onclick: () => { const s = sym.value.trim().toUpperCase(), q = parseFloat(qty.value), a = parseFloat(avg.value); if (!s || !(q > 0) || !(a > 0)) { toast('Enter ticker, quantity and cost.'); return; } hold = [...hold.filter((y) => y.symbol !== s), { symbol: s, qty: q, avg_cost: a }]; save(); sym.value = qty.value = avg.value = ''; paintList(); } }, t('add'))),
    card(null, list, h('button', { class: 'btn primary', style: 'margin-top:10px', onclick: () => { if (hold.length) analyze(); else toast(t('no_holdings')); } }, t('analyze_port'))), out);
  paintList();
}

/* ------------------------------------------------------------ MORE / JOURNAL */
function screenMore() {
  setHeader(); setNav('more');
  const link = (ic, label, href) => h('button', { class: 'item', onclick: () => { location.hash = href; } }, icon(ic), h('div', { class: 'grow', style: 'font-weight:700' }, label), h('span', { class: 'chev' }, icon('right')));
  view().append(h('div', { class: 'hero' }, h('h1', null, t('more_title'))),
    h('div', { class: 'card list' }, link('journal', t('journal'), '#/journal'), link('valid', t('validation'), '#/validation'), link('gear', t('settings'), '#/settings')));
}
function loadJournal() { try { const a = JSON.parse(safeLS.get('apex_journal_v1', '[]')); return Array.isArray(a) ? a : []; } catch { return []; } }
function saveJournal(a) { safeLS.set('apex_journal_v1', JSON.stringify(a)); }
function addJournal(rec) { const a = loadJournal(); a.unshift(Object.assign({ id: Date.now() + '-' + Math.random().toString(36).slice(2, 7), opened: new Date().toISOString().slice(0, 10), status: 'open' }, rec)); saveJournal(a); }
function screenJournal() {
  setHeader({ title: t('journal'), back: true }); setNav('more');
  const box = h('div');
  const paint = () => {
    const a = loadJournal(), open = a.filter((x) => x.status === 'open'), done = a.filter((x) => x.status !== 'open');
    const w = done.filter((x) => x.status === 'target').length, l = done.filter((x) => x.status === 'stopped').length, tot = w + l;
    const row = (x) => h('div', { class: 'card' },
      h('div', { class: 'row between' }, h('div', null, h('div', { class: 'sym' }, x.symbol), h('div', { class: 'tiny muted' }, `${x.opened} · ${x.objective || ''}`)), pill(t((x.status || 'open') + '_'), x.status === 'target' ? 'buy' : x.status === 'stopped' ? 'avoid' : '')),
      h('div', { class: 'kv', style: 'margin-top:10px' }, kvSmall(t('entry'), fmt(x.entry)), kvSmall(t('stop'), fmt(x.stop)), kvSmall(t('tp1'), fmt(x.tp1))),
      h('div', { class: 'ls', style: 'margin-top:10px' },
        x.status === 'open' ? [h('button', { class: 'btn sm', onclick: () => set(x.id, 'target') }, t('mark_target')), h('button', { class: 'btn sm', onclick: () => set(x.id, 'stopped') }, t('mark_stop')), h('button', { class: 'btn sm', onclick: () => set(x.id, 'closed') }, t('mark_closed'))] : null,
        h('button', { class: 'btn sm ghost', onclick: () => { saveJournal(loadJournal().filter((y) => y.id !== x.id)); paint(); } }, t('del'))));
    const set = (id, s) => { saveJournal(loadJournal().map((y) => y.id === id ? Object.assign({}, y, { status: s }) : y)); paint(); };
    box.replaceChildren(a.length ? [tot ? card(null, h('div', { class: 'row between' }, h('span', { class: 'muted' }, t('hit_rate')), h('b', { class: 'num' }, `${Math.round(w / tot * 100)}% (${w}/${tot})`))) : null, open.map(row), done.map(row)] : h('div', { class: 'card empty' }, t('no_journal')));
  };
  view().append(box); paint();
}

/* --------------------------------------------------------------- VALIDATION */
function screenValidation() {
  setHeader({ title: t('validation'), back: true }); setNav('more');
  let obj = 'swing'; const out = h('div');
  const run = async () => {
    out.replaceChildren(loading(t('bt_wait'))); const tok = S.nav;
    try {
      const d = await api(`/v1/backtest/universe?objective=${enc(obj)}&limit=40`, { retries: 0 }); if (tok !== S.nav) return;
      const o = d.overall || {};
      out.replaceChildren(card('Overall', stat('Symbols tested', d.symbols_tested), stat('Trades', o.trades), stat('Win rate', o.win_rate != null ? `${Math.round(o.win_rate * 100)}%` : '—'), stat('TP1 hit rate', o.tp1_hit_rate != null ? `${Math.round(o.tp1_hit_rate * 100)}%` : '—'), stat('Expectancy (R)', fmt(o.expectancy_r, 2)), stat('Profit factor', fmt(o.profit_factor, 2)), stat('Max drawdown (R)', fmt(o.max_drawdown_r, 2))),
        (d.calibration || []).length ? card('Calibration', h('div', { class: 'tbl-wrap' }, h('table', null, h('thead', null, h('tr', null, ['Confidence', 'Trades', 'Win rate', 'Avg R'].map((x) => h('th', null, x)))), h('tbody', null, d.calibration.map((c) => h('tr', null, h('td', { class: 'num' }, `${c.confidence}/5`), h('td', { class: 'num' }, c.trades), h('td', { class: 'num' }, `${Math.round(c.win_rate * 100)}%`), h('td', { class: 'num' }, fmt(c.avg_r, 2)))))))) : null,
        h('p', { class: 'disc' }, `${d.method || ''} ${d.reading_it || ''}`));
    } catch (e) { if (tok === S.nav) out.replaceChildren(errorBox(e, run)); }
  };
  view().append(card(null, h('div', { class: 'small muted', style: 'margin-bottom:10px' }, t('bt_sub')), objSeg(obj, (o) => { obj = o; }), h('button', { class: 'btn primary', onclick: run }, t('run_bt'))), out);
}

/* ------------------------------------------------------------------ SETTINGS */
function screenSettings() {
  setHeader({ title: t('settings'), back: true }); setNav('more');
  const rerender = () => { applyLangTheme(); route(); };
  const segBtn = (cur, val, label, on) => h('button', { 'aria-selected': String(cur === val), role: 'tab', onclick: on }, label);
  const acct = h('input', { class: 'input num', inputmode: 'decimal', value: safeLS.get('apex_acct', '100000'), oninput: (e) => { e.target.value = e.target.value.replace(/[^0-9.]/g, ''); safeLS.set('apex_acct', e.target.value); } });
  const risk = h('input', { class: 'input num', inputmode: 'decimal', value: safeLS.get('apex_risk', '1'), oninput: (e) => { e.target.value = e.target.value.replace(/[^0-9.]/g, ''); safeLS.set('apex_risk', e.target.value); } });
  const ver = h('span', null, '…');
  api('/v1/health', { retries: 0 }).then((d) => { ver.textContent = `${d.service} ${d.version}`; }).catch(() => { ver.textContent = '—'; });
  const installCard = card(t('install'), h('div', { class: 'small muted', style: 'margin-bottom:10px' }, t('install_hint')),
    S.installEvt ? h('button', { class: 'btn', onclick: async () => { S.installEvt.prompt(); try { await S.installEvt.userChoice; } catch {} S.installEvt = null; route(); } }, t('install')) : null);
  view().append(
    card(t('language'), h('div', { class: 'seg' }, segBtn(S.lang, 'en', 'English', () => { S.lang = 'en'; safeLS.set('apex_m_lang', 'en'); rerender(); }), segBtn(S.lang, 'ar', 'العربية', () => { S.lang = 'ar'; safeLS.set('apex_m_lang', 'ar'); rerender(); }))),
    card(t('theme'), h('div', { class: 'seg' }, segBtn(S.theme, 'dark', t('dark'), () => { S.theme = 'dark'; safeLS.set('apex_theme', 'dark'); rerender(); }), segBtn(S.theme, 'light', t('light'), () => { S.theme = 'light'; safeLS.set('apex_theme', 'light'); rerender(); }))),
    card(t('pos_size'), h('div', { class: 'row' }, h('label', { class: 'field grow' }, h('span', { class: 'lbl' }, t('account')), acct), h('label', { class: 'field grow' }, h('span', { class: 'lbl' }, t('risk_pct')), risk))),
    installCard,
    S.auth.required ? card(t('access_key'), h('button', { class: 'btn', onclick: () => { safeLS.del('apex_access_key'); S.auth.ok = false; showLogin(); } }, t('sign_out'))) : null,
    card(t('about'), stat('Engine', ver), stat('Mode', 'Same engine & API as desktop'), h('p', { class: 'disc' }, t('disclaimer'))));
}

/* --------------------------------------------------------------------- LOGIN */
function showLogin() {
  setHeader(); $('#nav').replaceChildren();
  const err = h('div'); const inp = h('input', { class: 'input', type: 'password', autocomplete: 'off', placeholder: t('access_key'), 'aria-label': t('access_key') });
  const go = async () => {
    const k = inp.value.trim(); if (!k) return;
    try { if (!(await checkKey(k))) throw new Error('bad'); safeLS.set('apex_access_key', k); S.auth.ok = true; boot(); }
    catch { err.replaceChildren(h('div', { class: 'notice err' }, t('bad_key'))); }
  };
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  view().replaceChildren(h('div', { class: 'login' }, h('h1', { style: 'font-size:22px;margin-bottom:6px' }, t('login_title')), h('p', { class: 'muted small', style: 'margin-bottom:14px' }, t('login_sub')), inp, err, h('button', { class: 'btn primary', style: 'margin-top:12px', onclick: go }, t('login_btn'))));
}

/* ---------------------------------------------------------------------- BOOT */
async function boot() {
  applyLangTheme();
  try {
    const st = await fetch(API + '/v1/auth/status').then((r) => r.json());
    S.auth.required = !!st.auth_required;
    if (S.auth.required) {
      const k = keyGet();
      if (k) { const ok = await checkKey(k).catch(() => false); S.auth.ok = ok; if (!ok) safeLS.del('apex_access_key'); }
    } else S.auth.ok = true;
  } catch { S.auth.ok = true; }
  route();
}
window.addEventListener('hashchange', route);
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); S.installEvt = e; });
window.addEventListener('online', () => document.querySelectorAll('.toast').forEach((x) => x.remove()));
window.addEventListener('offline', () => toast(t('offline')));
if ('serviceWorker' in navigator) {                      // browsers expose the API only on secure origins, so no host check is needed
  window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
}
boot();
})();
