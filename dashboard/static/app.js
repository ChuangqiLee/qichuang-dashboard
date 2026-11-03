/* AN Research Monitor -- vanilla JS single-page app (no build step).
 * Data comes from the read-only JSON API under /api/* (see ../README.md).
 * Every UI string lives in i18n.js (zh + en); press L or the header button to switch. */
(function () {
  'use strict';

  var POLL_MS = 4000;
  var PALETTE = ['#22d3ee', '#fbbf24', '#34d399', '#a78bfa', '#f472b6', '#60a5fa', '#fb923c', '#2dd4bf', '#f87171', '#a3e635', '#e879f9', '#38bdf8'];
  var FAM_COLOR = { baseline: '#60a5fa', novel: '#fbbf24', ours: '#fbbf24', ablation: '#a78bfa' };
  var ST_COLOR = { pending: '#50627e', queued: '#fbbf24', running: '#22d3ee', done: '#34d399', failed: '#f87171', skipped: '#3b4a63', pruned: '#3b4a63' };
  var CC = { text: '#d7e3f4', muted: '#8296b3', grid: 'rgba(130,150,179,0.12)', axis: '#24466e', amber: '#fbbf24', cyan: '#22d3ee' };
  var TT = { backgroundColor: 'rgba(7,13,25,0.96)', borderColor: '#24466e', textStyle: { color: '#d7e3f4', fontSize: 12 }, confine: true };
  var LEG = { textStyle: { color: '#8296b3' }, inactiveColor: '#2a3a55', type: 'scroll', pageTextStyle: { color: '#8296b3' }, pageIconColor: '#22d3ee', pageIconInactiveColor: '#24466e', top: 0 };

  // ------------------------------------------------------------------ storage
  var LS = {
    get: function (k, d) { try { var v = window.localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { window.localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } }
  };

  // ------------------------------------------------------------------ i18n
  var lang = LS.get('an_lang', 'zh');
  if (lang !== 'zh' && lang !== 'en') lang = 'zh';
  function dict(l) { return (window.I18N && window.I18N[l || lang]) || {}; }
  function has(k) { return Object.prototype.hasOwnProperty.call(dict(), k); }
  function t(k, vars) {
    var s = has(k) ? dict()[k] : (Object.prototype.hasOwnProperty.call(dict('en'), k) ? dict('en')[k] : k);
    if (vars) s = String(s).replace(/\{(\w+)\}/g, function (m, n) { return vars[n] !== undefined && vars[n] !== null ? vars[n] : m; });
    return s;
  }
  function tk(prefix, v) { var k = prefix + String(v); return has(k) ? t(k) : (v === undefined || v === null || v === '' ? '—' : String(v)); }
  function bi(o, base) {
    if (!o) return '';
    var zh = o[base + '_zh'], en = o[base + '_en'];
    return (lang === 'zh' ? (zh || en) : (en || zh)) || o[base] || '';
  }
  function biObj(o) { if (!o) return ''; if (typeof o === 'string') return o; return (lang === 'zh' ? (o.zh || o.en) : (o.en || o.zh)) || ''; }

  // ------------------------------------------------------------------ utils
  function $(s, el) { return (el || document).querySelector(s); }
  function $$(s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); }
  function esc(s) {
    return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function enc(s) { return encodeURIComponent(String(s)); }
  function encPath(p) { return String(p).split('/').map(encodeURIComponent).join('/'); }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function fmt(v, d) {
    if (!isNum(v)) return '—';
    var a = Math.abs(v);
    if (d === undefined) d = a >= 1000 ? 0 : a >= 100 ? 1 : a >= 10 ? 2 : 3;
    return v.toFixed(d);
  }
  function fmtSigned(v, d) { return isNum(v) ? (v > 0 ? '+' : '') + fmt(v, d) : '—'; }
  function fmtPct(v, d) { return isNum(v) ? (v * 100).toFixed(d === undefined ? 0 : d) + '%' : '—'; }
  function fmtBytes(b) {
    if (!isNum(b)) return '—';
    var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return b.toFixed(b >= 100 || i === 0 ? 0 : 1) + ' ' + u[i];
  }
  function fmtDur(s) {
    if (!isNum(s) || s < 0) return '—';
    s = Math.round(s);
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    function U(k, n) { return n + t(k); }
    if (d) return U('u_d', d) + ' ' + U('u_h', h);
    if (h) return U('u_h', h) + ' ' + U('u_m', m);
    if (m) return U('u_m', m) + ' ' + U('u_s', sec);
    return U('u_s', sec);
  }
  function toDate(x) {
    if (x === null || x === undefined || x === '') return null;
    var d = typeof x === 'number' ? new Date(x < 1e12 ? x * 1000 : x) : new Date(x);
    return isNaN(d.getTime()) ? null : d;
  }
  function pad(n) { return String(n).padStart(2, '0'); }
  function fmtTime(x, withDate) {
    var d = toDate(x);
    if (!d) return '—';
    var s = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    return withDate === false ? s : pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + s;
  }
  function ago(x) {
    var d = toDate(x);
    if (!d) return '—';
    var s = (Date.now() - d.getTime()) / 1000;
    if (s < 5) return t('just_now');
    return t('ago', { d: fmtDur(s) });
  }
  function clamp01(v) { return isNum(v) ? Math.max(0, Math.min(1, v)) : 0; }
  function bar(frac, cls) { return '<div class="bar ' + (cls || '') + '"><i style="width:' + (clamp01(frac) * 100).toFixed(1) + '%"></i></div>'; }
  function safeUrl(u) { return typeof u === 'string' && /^https?:\/\//i.test(u.trim()) ? u.trim() : null; }
  function clip(s, n) { s = String(s === undefined || s === null ? '' : s); return s.length > n ? s.slice(0, n) + '…' : s; }
  function stChip(s) { return '<span class="chip st-' + esc(s) + '">' + esc(tk('st_', s)) + '</span>'; }
  function famChip(f) { return '<span class="chip fam-' + esc(f) + '">' + esc(tk('fam_', f)) + '</span>'; }
  /** our own model family (experiments.json says novel, results/summary.json says ours) */
  function isOursFam(f) { return f === 'ours' || f === 'novel'; }
  /** chart series / legend name: our models get a leading star */
  function starName(name, f) { return (isOursFam(f) ? '★ ' : '') + name; }
  var ICON = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="#22d3ee" stroke-width="1.4" aria-hidden="true"><circle cx="12" cy="12" r="9" opacity=".45"/><circle cx="12" cy="12" r="5" opacity=".25"/><path d="M12 7v5l3.2 2"/></svg>';
  function emptyBox(titleKey, hintKey, vars) {
    return '<div class="empty">' + ICON + '<div class="ttl">' + esc(t(titleKey, vars)) + '</div><div class="scanline"></div>' +
      (hintKey ? '<div class="hint">' + t(hintKey, vars) + '</div>' : '') + '</div>';
  }
  function lowerIsBetter(name) { return /loss|hd95|hd|asd|assd|error|err|nll|ece|mae|mse|rmse|fpr|fnr|time|latency/i.test(String(name)); }

  var colorMap = LS.get('an_colors', {});
  if (!colorMap || typeof colorMap !== 'object') colorMap = {};
  function colorFor(key) {
    if (colorMap[key] === undefined) {
      var used = {}, i = 0;
      Object.keys(colorMap).forEach(function (k) { used[colorMap[k]] = 1; });
      while (used[i] && i < PALETTE.length) i++;
      colorMap[key] = i < PALETTE.length ? i : Object.keys(colorMap).length % PALETTE.length;
      LS.set('an_colors', colorMap);
    }
    return PALETTE[colorMap[key] % PALETTE.length];
  }
  /** method colour in Results charts: our own models are always gold (shades when several), nobody else may be gold */
  var OURS_SHADES = ['#fbbf24', '#fde68a', '#f59e0b', '#facc15'], oursShade = {};
  function methodColor(id, ours) {
    if (ours) { if (oursShade[id] === undefined) oursShade[id] = Object.keys(oursShade).length; return OURS_SHADES[oursShade[id] % OURS_SHADES.length]; }
    var c = colorFor('method:' + id);
    return c === '#fbbf24' ? '#e2e8f0' : c;
  }

  // ------------------------------------------------------------------ markdown (marked + DOMPurify)
  var mdReady = false;
  function setupMd() {
    if (mdReady || !window.DOMPurify || !window.marked) return;
    try {
      window.DOMPurify.addHook('afterSanitizeAttributes', function (n) {
        if (n.tagName === 'A') { n.setAttribute('target', '_blank'); n.setAttribute('rel', 'noopener noreferrer'); }
      });
      mdReady = true;
    } catch (e) { mdReady = false; }
  }
  function md(text) {
    if (mdReady) {
      try {
        var html = window.marked.parse(String(text), { gfm: true, breaks: true, async: false });
        return '<div class="md">' + window.DOMPurify.sanitize(html, { FORBID_TAGS: ['style', 'form', 'input', 'img', 'iframe', 'video', 'audio'], FORBID_ATTR: ['style'] }) + '</div>';
      } catch (e) { /* fall through */ }
    }
    return '<div class="plain">' + esc(text) + '</div>';
  }

  // ------------------------------------------------------------------ API
  function api(path) {
    var ctl = window.AbortController ? new AbortController() : null;
    var to = setTimeout(function () { if (ctl) ctl.abort(); }, 12000);
    return fetch(path, { signal: ctl ? ctl.signal : undefined, cache: 'no-store', credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok && r.status !== 404) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .finally(function () { clearTimeout(to); });
  }

  // ------------------------------------------------------------------ charts
  var charts = {};
  function chart(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    if (!window.echarts) {
      if (!el.querySelector('.empty')) el.innerHTML = emptyBox('charts_unavailable', 'charts_unavailable_hint');
      return null;
    }
    var c = charts[id];
    if (c && (c.isDisposed() || c.getDom() !== el)) { try { c.dispose(); } catch (e) { /* ignore */ } c = null; }
    if (!c) { c = window.echarts.init(el, null, { renderer: 'canvas' }); charts[id] = c; }
    return c;
  }
  function gcCharts() {
    Object.keys(charts).forEach(function (id) {
      var c = charts[id];
      if (c.isDisposed() || !c.getDom().isConnected) { try { c.dispose(); } catch (e) { /* ignore */ } delete charts[id]; }
    });
  }
  function resizeCharts() {
    Object.keys(charts).forEach(function (id) {
      var c = charts[id];
      if (!c.isDisposed() && c.getDom().offsetParent !== null) c.resize();
    });
  }
  /** show chart `id` (returns instance) or its sibling `${id}-empty` box (returns null). */
  function chartOrEmpty(id, show, emptyHtml, height) {
    var el = document.getElementById(id), em = document.getElementById(id + '-empty');
    if (!el) return null;
    if (!show) {
      el.style.display = 'none';
      if (em) { em.style.display = ''; if (emptyHtml !== undefined && em.getAttribute('data-h') !== emptyHtml) { em.innerHTML = emptyHtml; em.setAttribute('data-h', emptyHtml); } }
      return null;
    }
    var wasHidden = el.style.display === 'none';
    el.style.display = '';
    if (height && el.style.height !== height + 'px') { el.style.height = height + 'px'; wasHidden = true; }
    if (em) em.style.display = 'none';
    var c = chart(id);
    if (c && wasHidden) c.resize();
    return c;
  }
  function ax(o) {
    var base = { axisLine: { lineStyle: { color: CC.axis } }, axisTick: { lineStyle: { color: CC.axis } }, axisLabel: { color: CC.muted }, splitLine: { lineStyle: { color: CC.grid } }, nameTextStyle: { color: CC.muted } };
    return Object.assign(base, o || {});
  }

  // ------------------------------------------------------------------ lightbox
  function lightbox(src, cap) {
    var d = document.createElement('div');
    d.className = 'lightbox';
    d.innerHTML = '<img alt="" src="' + esc(src) + '"><div class="cap">' + esc(cap || '') + '</div><div class="muted small">' + esc(t('click_to_close')) + '</div>';
    function close() { d.remove(); document.removeEventListener('keydown', onKey); }
    function onKey(e) { if (e.key === 'Escape') close(); }
    d.addEventListener('click', close);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(d);
  }
  document.addEventListener('click', function (e) {
    var f = e.target.closest && e.target.closest('figure[data-src]');
    if (f) lightbox(f.getAttribute('data-src'), f.getAttribute('data-cap'));
  });

  function evRow(e) {
    return '<div class="ev lv-' + esc(e.level) + '"><div class="tm">' + esc(fmtTime(e.ts)) + '</div>' +
      '<div><span class="chip lv-' + esc(e.level) + ' t-' + esc(e.type) + '">' + esc(tk('type_', e.type)) + '</span></div>' +
      '<div class="ev-msg"><span class="act">' + esc(e.actor) + '</span>' + esc(lang === 'zh' ? e.msg_zh : e.msg_en) + '</div></div>';
  }

  // ------------------------------------------------------------------ data freshness (README §19)
  /* Client registry of the data sources behind the cards: cadence class, a fallback max age (s) used only when
   * /api/freshness is absent, and how to find the source in /api/freshness (ids, then path suffixes). Every card
   * header gets an asOf() badge from paintAsOf(); the server's `stale` flag always wins over the fallback rule. */
  var FR_CADS = ['live', 'periodic', 'event', 'manual'];
  var FR_DEF = {
    workflow: { cad: 'manual', ids: ['workflow'], paths: ['state/workflow.json'] },
    experiments: { cad: 'event', ids: ['experiments', 'registry'], paths: ['state/experiments.json'] },
    results: { cad: 'event', ids: ['results_summary', 'results', 'summary'], paths: ['results/summary.json'] },
    cases: { cad: 'event', ids: ['cases', 'case_gallery', 'results_cases'], paths: ['results/cases/index.json'] },
    runs: { cad: 'live', max: 600, ids: ['runs', 'run_metrics', 'metrics', 'run_status'], paths: ['metrics.jsonl', '/status.json'] },
    events: { cad: 'live', ids: ['events'], paths: ['state/events.jsonl'] },
    system: { cad: 'live', max: 60, ids: ['system', 'system_metrics', 'gpu'] },
    briefing: { cad: 'periodic', max: 7200, ids: ['briefing'], paths: ['state/briefing.json'] },
    session_status: { cad: 'periodic', max: 7200, ids: ['session_status'], paths: ['state/session_status.json'] },
    session: { cad: 'live', ids: ['session', 'transcript', 'session_transcript'] },
    routing: { cad: 'manual', ids: ['routing'], paths: ['state/routing.json'] },
    literature: { cad: 'manual', ids: ['literature'], paths: ['state/literature.json'] },
    paper: { cad: 'manual', ids: ['paper'], paths: ['state/paper.json'] },
    agents: { cad: 'live', ids: ['agents', 'transcripts'] },
    leaderboard: { cad: 'event', ids: ['leaderboard', 'leaderboard_events'], paths: ['state/leaderboard_events.jsonl'] },
    freshness: { cad: 'live' }
  };
  var FR = { sources: null, ok: null, at: 0, now: null, note: {}, idFor: {}, ovStale: {}, ovById: null };
  /** remember a payload timestamp for a source (fallback when /api/freshness has no entry) */
  function frNote(key, ts) { if (key && toDate(ts)) FR.note[key] = ts; }
  /** the Overview's stale_ids count only while /api/freshness has given no rows (FR-1: a fresh server `stale:false` always wins) */
  function frOv(id) { return !FR.sources && !!FR.ovStale[String(id)]; }
  function frIds(key) { var d = FR_DEF[key] || {}; return [key].concat(d.ids || [], FR.idFor[key] ? [FR.idFor[key]] : []); }
  function frPathHit(p, x) { return p === x || (x.charAt(0) === '/' ? p.slice(-x.length) === x : p.slice(-x.length - 1) === '/' + x); }
  /** the /api/freshness entry for a key: id match first, then path suffix; several hits -> the newest one */
  function frMatch(key) {
    var list = FR.sources;
    if (!list && FR.ovById) list = Object.keys(FR.ovById).map(function (id) { return Object.assign({ id: id }, FR.ovById[id]); });  // /api/overview freshness.by_id
    if (!list) return null;
    var ids = frIds(key), paths = (FR_DEF[key] || {}).paths || [], byId = [], byPath = [];
    list.forEach(function (s) {
      if (!s || typeof s !== 'object') return;
      var p = String(s.path || '').replace(/\\/g, '/');
      if (ids.indexOf(String(s.id)) >= 0) byId.push(s);
      else if (p && paths.some(function (x) { return frPathHit(p, x); })) byPath.push(s);
    });
    var hits = byId.length ? byId : byPath;
    if (!hits.length) return null;
    return hits.reduce(function (a, b) { var ta = toDate(a.updated), tb = toDate(b.updated); return !ta || (tb && tb > ta) ? b : a; });
  }
  function frLabel(key, s) { return (s && bi(s, 'label')) || tk('fr_src_', key); }
  function frInfo(key) {
    var def = FR_DEF[key] || {}, s = frMatch(key);
    var ts = (s && toDate(s.updated) ? s.updated : null) || FR.note[key] || null;
    var cad = s && FR_CADS.indexOf(s.cadence) >= 0 ? s.cadence : (def.cad || 'event');
    var max = s ? frMax(s) : (def.max || null);
    var d = toDate(ts), age = d ? Math.max(0, (Date.now() - d.getTime()) / 1000) : null, stale;
    if (s && typeof s.stale === 'boolean') stale = s.stale || frOv(s.id);
    else if (frIds(key).some(frOv)) stale = true;
    else stale = !!(max && isNum(age) && age > max);
    return { key: key, ts: ts, cad: cad, max: max, age: age, stale: stale, src: s, hint: s ? bi(s, 'hint') : '', reason: s ? bi(s, 'reason') : '' };
  }
  /** expected max age of a server source; `stale_rule: sporadic` sources (events) are never judged by age */
  function frMax(s) { return s && s.stale_rule !== 'sporadic' && isNum(s.expected_max_age_s) && s.expected_max_age_s > 0 ? s.expected_max_age_s : null; }
  function frHM(x) {
    var d = toDate(x);
    if (!d) return '—';
    var hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
    return d.toDateString() === new Date().toDateString() ? hm : pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + hm;
  }
  /** coarse relative time for badges: 刚刚 / 11 分钟前 / 2小时 5分前 */
  function agoCoarse(x) {
    var d = toDate(x);
    if (!d) return '—';
    var s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 45) return t('just_now');
    if (s < 3600) return t('fr_ago_min', { n: Math.max(1, Math.round(s / 60)) });
    return t('ago', { d: fmtDur(Math.floor(s / 60) * 60) });
  }
  /** compact duration for expected max ages: 60 -> 1分, 7200 -> 2小时 */
  function frDur(s) {
    if (!isNum(s)) return '—';
    if (s >= 3600 && s % 3600 === 0) return (s / 3600) + t('u_h');
    if (s >= 60 && s < 3600 && s % 60 === 0) return (s / 60) + t('u_m');
    return fmtDur(s);
  }
  function frCadTip(cad, max) {
    var k = 'fr_cad_tip_' + cad;  // fr_cad_tip_live / fr_cad_tip_periodic
    if ((cad === 'live' || cad === 'periodic') && isNum(max)) return t(k, { max: frDur(max) });
    return tk('fr_cad_tipx_', cad);
  }
  /** card-header badge: 更新于 16:22 · 11 分钟前; amber 可能过期 when stale (tooltip explains the cadence) */
  function asOf(ts, cadence, o) {
    o = o || {};
    if (!toDate(ts)) return o.stale ? '<span class="asof stale" title="' + esc([o.label, o.reason, t('fr_tip_stale_nots')].filter(Boolean).join('\n')) + '"><span class="asof-ic">⚠</span>' + esc(t('fr_stale')) + '</span>' : '';
    var cad = FR_CADS.indexOf(cadence) >= 0 ? cadence : 'event', v = { t: frHM(ts), ago: agoCoarse(ts) };
    var txt = o.stale ? t('fr_badge_stale', v) : t(cad === 'manual' ? 'fr_badge_manual' : 'fr_badge', v);
    var tip = [o.label, o.hint || (o.key ? tk('fr_tip_', o.key) : ''), frCadTip(cad, o.max), t('fr_tip_at', { t: fmtTime(ts) })];
    if (o.stale) tip.push(o.reason || (isNum(o.max) ? t('fr_tip_stale', { max: frDur(o.max) }) : t('fr_tip_stale_srv')));
    return '<span class="asof cad-' + cad + (o.stale ? ' stale' : '') + '" title="' + esc(tip.filter(function (x) { return x && x !== '—'; }).join('\n')) + '">' +
      (o.stale ? '<span class="asof-ic">⚠</span>' : '') + esc(txt) + '</span>';
  }
  function asOfKey(key, o) {
    var f = frInfo(key);
    if (o && o.staleOnly && !f.stale) return '';
    return asOf(f.ts, f.cad, { stale: f.stale, max: f.max, key: key, label: frLabel(key, f.src), reason: f.reason, hint: f.hint });
  }
  /** fill the badge slot of every `.card > h2` of a view (card `data-src`, else the view's `src`; `none` = no badge),
   *  the shared per-source strips (`data-srcs`) and the stale outline of KPI tiles (`.kpi[data-src]`) */
  function paintAsOf(V) {
    if (!V || !V.el || !V.mounted) return;
    $$('.card', V.el).forEach(function (card) {
      var h2 = null;
      for (var c = card.firstElementChild; c; c = c.nextElementSibling) if (c.tagName === 'H2') { h2 = c; break; }
      if (!h2) return;
      var key = card.getAttribute('data-src') || V.src || 'none', slot = h2.querySelector('.asof-slot');
      var h = key === 'none' ? '' : asOfKey(key, { staleOnly: card.getAttribute('data-asof') === 'stale' });
      if (!slot) { if (!h) return; slot = document.createElement('span'); slot.className = 'asof-slot'; h2.appendChild(slot); }
      if (slot.getAttribute('data-h') !== h) { slot.innerHTML = h; slot.setAttribute('data-h', h); }
    });
    $$('[data-srcs]', V.el).forEach(function (el) {
      var h = el.getAttribute('data-srcs').split(',').filter(Boolean).map(function (k) {
        var b = asOfKey(k);
        return b ? '<span class="asof-item"><span class="asof-src">' + esc(tk('fr_src_', k)) + '</span>' + b + '</span>' : '';
      }).join('');
      if (el.getAttribute('data-h') !== h) { el.innerHTML = h ? '<span class="asof-lead">' + esc(t('fr_strip')) + '</span>' + h : ''; el.setAttribute('data-h', h); }
      el.hidden = !h;
    });
    $$('.kpi[data-src]', V.el).forEach(function (el) { el.classList.toggle('fr-stale', frInfo(el.getAttribute('data-src')).stale); });
  }
  /** /api/freshness: every poll on the System view, otherwise every 15 s (60 s while the server lacks it) */
  function frFetch() {
    var now = Date.now(), wait = FR.ok === false ? 60000 : (current === 'system' ? 0 : 15000);
    if (now - FR.at < wait) return Promise.resolve(null);
    FR.at = now;
    return api('/api/freshness').then(function (r) {
      if (r && r.ok !== false && Array.isArray(r.sources)) {
        FR.sources = r.sources.filter(function (s) { return s && typeof s === 'object'; });
        FR.ok = true; FR.now = r.now || new Date().toISOString(); FR.ovStale = {};
        frNote('freshness', FR.now);
      } else if (!FR.sources) FR.ok = false;
    }).catch(function () { if (!FR.sources) FR.ok = false; });
  }
  /** `freshness: {stale_ids}` of /api/overview */
  function frOverview(f) {
    if (!f || typeof f !== 'object' || !Array.isArray(f.stale_ids)) return;
    if (f.by_id && typeof f.by_id === 'object') FR.ovById = f.by_id;
    FR.ovStale = {};
    f.stale_ids.forEach(function (id) { FR.ovStale[String(id)] = 1; });
  }
  /** System view table: stale rows first, then rows without a timestamp, then by cadence and age */
  function frTableHtml() {
    if (!FR.sources) return FR.ok === false ? emptyBox('fr_unavailable', 'fr_unavailable_hint') : emptyBox('lb_loading', null);
    if (!FR.sources.length) return emptyBox('fr_none', null);
    var co = { live: 0, periodic: 1, event: 2, manual: 3 };
    var rows = FR.sources.map(function (s) {
      var d = toDate(s.updated), age = d ? Math.max(0, (Date.now() - d.getTime()) / 1000) : (isNum(s.age_s) ? s.age_s : null);
      return { s: s, age: age, stale: s.stale === true, missing: !d };
    });
    rows.sort(function (a, b) {
      return (b.stale - a.stale) || (b.missing - a.missing) || ((co[a.s.cadence] === undefined ? 4 : co[a.s.cadence]) - (co[b.s.cadence] === undefined ? 4 : co[b.s.cadence])) || ((b.age || 0) - (a.age || 0));
    });
    function useName(u) {
      // tab_<view> / fr_use_<part> when defined (keys listed in the check_i18n dyn map), else the raw id
      function nm(pfx, x) { var k = pfx + x; return has(k) ? t(k) : null; }
      var p = String(u).split('.'), v = p[0], rest = p.slice(1).join('.');
      return (nm('tab_', v) || nm('fr_use_', v) || v) + (rest ? ' · ' + (nm('fr_use_', rest) || rest) : '');
    }
    return '<table class="tbl fr-tbl"><thead><tr><th>' + esc(t('fr_col_source')) + '</th><th>' + esc(t('fr_col_cadence')) + '</th><th>' + esc(t('fr_col_updated')) + '</th><th>' + esc(t('fr_col_age')) + '</th><th>' + esc(t('fr_col_state')) + '</th><th>' + esc(t('fr_col_used')) + '</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var s = r.s, cad = FR_CADS.indexOf(s.cadence) >= 0 ? s.cadence : 'event', max = frMax(s);
        var reason = bi(s, 'reason'), hint = bi(s, 'hint');
        var st = r.stale ? '<span class="chip lv-warn" title="' + esc(reason || (isNum(max) ? t('fr_tip_stale', { max: frDur(max) }) : t('fr_tip_stale_srv'))) + '">⚠ ' + esc(t('fr_stale')) + '</span>' :
          r.missing ? '<span class="chip st-pruned">' + esc(t('fr_no_data')) + '</span>' : '<span class="chip st-done">' + esc(t('fr_ok')) + '</span>';
        var used = Array.isArray(s.used_by) ? s.used_by : [];
        return '<tr class="' + (r.stale ? 'fr-row-stale' : '') + '"><td' + (hint ? ' title="' + esc(hint) + '"' : '') + '><div>' + esc(bi(s, 'label') || tk('fr_src_', s.id)) + '</div>' + (hint ? '<div class="tiny muted fr-hint">' + esc(hint) + '</div>' : '') + (s.path ? '<div class="mono tiny dim fr-path">' + esc(s.path) + '</div>' : '') + '</td>' +
          '<td><span class="chip fr-cad cad-' + cad + '" title="' + esc(frCadTip(cad, max)) + '">' + esc(tk('fr_cad_', cad)) + '</span>' + (isNum(max) ? ' <span class="mono tiny dim">≤ ' + esc(frDur(max)) + '</span>' : '') + '</td>' +
          '<td class="mono small nowrap">' + esc(s.updated ? fmtTime(s.updated) : '—') + '</td>' +
          '<td class="mono small nowrap">' + esc(isNum(r.age) ? fmtDur(r.age) : '—') + '</td><td>' + st + '</td>' +
          '<td class="fr-used">' + (used.length ? used.map(function (u) { return '<span class="chip mono tiny" title="' + esc(u) + '">' + esc(useName(u)) + '</span>'; }).join(' ') : '<span class="dim">—</span>') + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  // ======================================================================== VIEWS
  var VIEWS = {};

  // ------------------------------------------------------------------ Overview
  function shortId(id) { return id ? String(id).split('_')[0] : ''; }
  /** Overview best-Dice live line from the leaderboard field (used when best_dice.live is absent) */
  function ovLiveLine(L) {
    if (!L || typeof L !== 'object' || L.error || L.ok === false) return null;
    var top = L.top_ours || {}, bb = L.best_baseline || {};
    if (!top.run_id && !bb.id) return null;
    return { metric: L.metric, ours_id: top.run_id, ours_name: top.name, ours: top.value, baseline_id: bb.id, baseline_name: bb.name, baseline: bb.value,
      verdict: top.verdict, provisional: !!(top.provisional || bb.provisional) };
  }
  VIEWS.overview = {
    mount: function () {
      return '<div class="kpis" id="ov-kpis"></div><div class="kpi-asof" id="ov-kpi-asof" data-srcs="workflow,experiments,results,system,literature,paper" hidden></div>' +
        '<div class="grid"><div class="card s12 brief-card" data-src="briefing" data-asof="stale"><h2>' + esc(t('ov_briefing')) + '<span class="grow"></span><span class="tag small" id="ov-brief-meta"></span></h2><div id="ov-brief" class="brief"></div></div></div>' +
        '<div class="grid"><div class="card s12 lb-ov-card" data-src="runs"><h2>' + esc(t('lb_ov_title')) + '<span class="grow"></span><span class="tag muted small" id="ov-race-meta"></span><a class="tag small" href="#/leaderboard">' + esc(t('lb_open')) + ' →</a></h2><div id="ov-race"></div></div></div>' +
        '<div class="grid"><div class="card s12" data-src="workflow"><h2>' + esc(t('ov_phases')) + '<span class="grow"></span><a class="tag small" href="#/workflow">' + esc(t('open_workflow')) + ' →</a></h2><div class="stepper" id="ov-stepper"></div></div></div>' +
        '<div class="grid">' +
        '<div class="card s5" data-src="runs"><h2>' + esc(t('ov_curves')) + '<span class="grow"></span><a class="tag small" href="#/training">' + esc(t('open_training')) + ' →</a></h2><div id="ov-curves" class="chart" style="display:none"></div><div id="ov-curves-empty"></div></div>' +
        '<div class="card s4" data-src="events"><h2>' + esc(t('ov_events')) + '<span class="grow"></span><a class="tag small" href="#/events">' + esc(t('view_all')) + ' →</a></h2><div class="feed" id="ov-events"></div></div>' +
        '<div class="card s3" data-src="routing"><h2>' + esc(t('ov_routing')) + '</h2><div id="ov-routing"></div></div>' +
        '</div>' +
        '<div class="grid"><div class="card s12" data-src="events"><h2>' + esc(t('ov_milestones')) + '<span class="grow"></span><a class="tag small" href="#/events?type=milestone">' + esc(t('view_all')) + ' →</a></h2><div class="mtl" id="ov-milestones"></div></div></div>';
    },
    load: function () { var self = this; return api('/api/overview').then(function (d) { self.data = d; }); },
    update: function (d) {
      if (!d || d.ok === false) { $('#ov-kpis').innerHTML = '<div class="card s12">' + emptyBox('load_error', null) + '</div>'; return; }
      // payload timestamps for the freshness badges (fallback when /api/freshness is absent)
      frOverview(d.freshness);
      frNote('workflow', d.workflow_updated); frNote('experiments', (d.experiments || {}).updated); frNote('system', d.gpus_ts || d.now);
      frNote('literature', (d.literature || {}).updated); frNote('paper', (d.paper || {}).updated); frNote('routing', d.routing_updated);
      if ((d.events || []).length) frNote('events', d.events[0].ts);
      if (d.briefing && !d.briefing.missing) frNote('briefing', d.briefing.updated);
      function srcd(html, key) { return html.replace('<div class="card kpi', '<div data-src="' + key + '" class="card kpi'); }
      var phases = d.phases || [];
      var ph = phases.filter(function (p) { return p.id === d.current_phase; })[0];
      var nDone = phases.filter(function (p) { return p.status === 'done'; }).length;
      var nRun = phases.filter(function (p) { return p.status === 'running'; }).length;
      function kpi(lbl, val, sub, extra, cls) {
        return '<div class="card kpi ' + (cls || '') + '"><div class="lbl">' + esc(t(lbl)) + '</div><div class="val' + ((cls || '').indexOf('txt') >= 0 ? ' txt' : '') + '">' + val + '</div>' +
          (sub ? '<div class="subl">' + sub + '</div>' : '') + (extra || '') + '</div>';
      }
      var tiles = [];
      tiles.push(srcd(kpi('kpi_phase', ph ? esc(bi(ph, 'name')) : '—',
        (ph ? stChip(ph.status) : '') + '<span>' + esc(t('phases_done', { n: nDone, total: phases.length })) + '</span><span>' + esc(t('phases_running', { n: nRun })) + '</span>',
        bar(phases.length ? nDone / phases.length : 0), 'txt accent-cyan'), 'workflow'));
      tiles.push(kpi('kpi_elapsed', esc(fmtDur(d.elapsed_s)), d.first_event_ts ? esc(t('since', { t: fmtTime(d.first_event_ts) })) : esc(t('no_events'))));
      var ex = d.experiments || { total: 0, by_status: {} }, bs = ex.by_status || {};
      var exSub = ['running', 'queued', 'done', 'pruned', 'failed'].filter(function (s) { return s !== 'failed' || bs[s]; }).map(function (s) {
        return '<span class="chip st-' + s + '">' + esc(tk('st_', s)) + ' ' + (bs[s] || 0) + '</span>';
      }).join('');
      var rr = d.runs || { total: 0, by_state: {} };
      tiles.push(srcd(kpi('kpi_experiments', String(ex.total || 0), exSub,
        '<div class="subl">' + esc(t('runs_running', { n: (rr.by_state || {}).running || 0, total: rr.total || 0 })) + '</div>'), 'experiments'));
      var q = d.queue || {}, qc = q.counts || {}, qEnd = toDate(q.eta_end);
      var qSub = '<span class="chip st-running">' + esc(t('st_running')) + ' ' + (qc.running || 0) + '</span><span class="chip st-queued">' + esc(t('st_queued')) + ' ' + (qc.queued || 0) + '</span>';
      tiles.push(srcd(qEnd ? kpi('kpi_queue_eta', '<span title="' + esc(fmtTime(qEnd)) + '">' + esc(fmtTime(qEnd).slice(0, 11)) + '</span>',
        '<span>' + esc(qEnd.getTime() > Date.now() ? t('in_about', { d: fmtDur((qEnd.getTime() - Date.now()) / 1000) }) : t('queue_due')) + '</span>',
        '<div class="subl">' + qSub + '<a href="#/workflow">' + esc(t('open_workflow')) + ' →</a></div>', 'accent-cyan') :
        kpi('kpi_queue_eta', '—', esc(t('queue_empty')), '<div class="subl">' + qSub + '</div>'), 'experiments'));
      var bd = d.best_dice || {}, bdKey = bd.source === 'experiments' ? 'experiments' : 'results';
      if (bd.freshness_id) FR.idFor[bdKey] = String(bd.freshness_id);
      frNote(bdKey, bd.updated || bd.data_ts);
      // live line under the tile: our top run vs the best baseline on live validation Dice (leaderboard field)
      var lv = bd.live && typeof bd.live === 'object' ? bd.live : ovLiveLine(d.leaderboard), liveH = '';
      if (lv && (isNum(lv.ours) || isNum(lv.baseline))) {
        var lvDg = lbDg(lv.metric || 'val_dice'), lvV = LB_VERDICTS.indexOf(lv.verdict) >= 0 ? lv.verdict : null;
        var lvVd = lvV ? '<b class="vd-txt vd-' + lvV + '">' + esc(tk('vd_', lvV) + (lv.provisional ? ' · ' + t('lb_provisional') : '')) + '</b>' : '<span class="dim">—</span>';
        liveH = '<a class="kpi-live" href="#/leaderboard" title="' + esc(t('kpi_live_tip', { o: lv.ours_name || lv.ours_id || '—', b: lv.baseline_name || lv.baseline_id || '—' })) + '">' +
          t('kpi_live_line', { o: esc(lv.ours_short || shortId(lv.ours_id) || '—'), ov: esc(fmt(lv.ours, lvDg)), b: esc(lv.baseline_short || shortId(lv.baseline_id) || '—'), bv: esc(fmt(lv.baseline, lvDg)), vd: lvVd }) + ' →</a>';
      }
      if (bd.source && (isNum(bd.ours) || isNum(bd.baseline))) {
        var delta = isNum(bd.ours) && isNum(bd.baseline) ? bd.ours - bd.baseline : null;
        var sotaK = isNum(delta) && delta > 0;
        // inhouse_val = validation split (daily monitoring never uses a test split): 院内验证 · 正式评估
        var bdVal = bd.source === 'results' && /(^|_)val(_|$)/i.test(String(bd.dataset || ''));
        var bdLbl = bd.source === 'results' ? (bdVal ? 'kpi_best_dice_val' : 'kpi_best_dice_final') : 'kpi_best_dice';
        tiles.push(srcd(kpi(bdLbl, (sotaK ? '<span class="star" title="' + esc(t('kpi_sota_tip')) + '">★</span>' : '') + '<span style="color:' + (sotaK ? 'var(--sota)' : 'var(--amber)') + '">' + fmt(bd.ours) + '</span><span class="unit"> ' + esc(t('vs')) + ' </span><span style="color:var(--blue);font-size:.7em">' + fmt(bd.baseline) + '</span>',
          '<span class="' + (delta > 0 ? 'pos' : delta < 0 ? 'neg' : '') + '">Δ ' + fmtSigned(delta) + '</span><span>' + esc(t('ours')) + ': ' + esc(bd.ours_method || '—') + '</span><span>' + esc(t('baseline')) + ': ' + esc(bd.baseline_method || '—') + '</span>',
          '<div class="subl"><span class="chip">' + esc(bd.source === 'results' ? t('src_results') : t('src_experiments')) + '</span>' + (bd.dataset ? '<span title="' + esc(bd.dataset) + '">' + esc(bi(bd, 'dataset_name') || bd.dataset) + '</span>' : '') + asOfKey(bdKey) + '</div>' +
          (liveH ? '<div class="subl">' + liveH + '</div>' : '')), bdKey));
      } else {
        tiles.push(srcd(kpi('kpi_best_dice', '—', esc(t('dice_waiting')), liveH ? '<div class="subl">' + liveH + '</div>' : ''), bdKey));
      }
      var gpus = d.gpus || [];
      var gh = gpus.length ? '<div class="gpu-mini">' + gpus.map(function (g) {
        var mem = isNum(g.mem_used) && isNum(g.mem_total) && g.mem_total ? g.mem_used / g.mem_total : null;
        return '<span class="mono">GPU' + esc(g.index) + '</span>' + bar((g.util || 0) / 100, (g.util || 0) > 85 ? 'amber' : '') + '<span class="mono">' + (isNum(g.util) ? g.util + '%' : '—') + '</span>' +
          '<span></span>' + bar(mem, 'violet') + '<span class="mono tiny muted">' + fmtBytes(g.mem_used) + '</span>';
      }).join('') + '</div>' : '<div class="subl">' + esc(t('no_gpu')) + '</div>';
      var avgU = gpus.length ? gpus.reduce(function (a, g) { return a + (g.util || 0); }, 0) / gpus.length : null;
      tiles.push('<div class="card kpi" data-src="system"><div class="lbl">' + esc(t('kpi_gpu')) + '</div><div class="val">' + (isNum(avgU) ? avgU.toFixed(0) + '<span class="unit">%</span>' : '—') + '</div>' + gh + '</div>');
      var lit = d.literature || {};
      tiles.push(srcd(kpi('kpi_papers', String(lit.found || 0), '<span>' + esc(t('verified_n', { n: lit.verified_3x || 0, k: 3 })) + '</span><span>' + esc(t('verified_n', { n: lit.verified_1x || 0, k: 1 })) + '</span>',
        bar(lit.found ? (lit.verified_3x || 0) / lit.found : 0), 'accent-teal'), 'literature'));
      var pp = d.paper || {};
      tiles.push(srcd(kpi('kpi_sections', (pp.sections_done || 0) + '<span class="unit">/ ' + (pp.sections_total || 0) + '</span>',
        '<span>' + esc(t('words_n', { n: pp.words || 0 })) + '</span>' + (pp.pdf ? '<a href="/api/paper/pdf" target="_blank" rel="noopener">PDF ↗</a>' : '<span>' + esc(t('pdf_none')) + '</span>'),
        bar(pp.sections_total ? (pp.sections_done || 0) / pp.sections_total : 0)), 'paper'));
      var rf = pp.references || {};
      tiles.push(srcd(kpi('kpi_refs', (rf.verified_3x || 0) + '<span class="unit">/ ' + (rf.total || 0) + '</span>',
        '<span>1× ' + (rf.verified_1x || 0) + '</span><span>2× ' + (rf.verified_2x || 0) + '</span><span>3× ' + (rf.verified_3x || 0) + '</span>',
        bar(rf.total ? (rf.verified_3x || 0) / rf.total : 0, 'amber'), 'accent-amber'), 'paper'));
      $('#ov-kpis').innerHTML = tiles.join('');

      $('#ov-stepper').innerHTML = phases.length ? phases.map(function (p, i) {
        return '<div class="step ' + esc(p.status) + (p.id === d.current_phase ? ' current' : '') + '" title="' + esc(tk('st_', p.status)) + '"><div class="n">' + pad(i + 1) + ' · ' + esc(tk('st_', p.status)) + '</div><div class="nm">' + esc(bi(p, 'name')) + '</div>' + bar(p.status === 'done' ? 1 : p.progress) + '</div>';
      }).join('') : emptyBox('wf_none', 'wf_none_hint');

      var curves = d.curves || [];
      var c = chartOrEmpty('ov-curves', curves.length > 0, emptyBox('ov_no_running', 'ov_no_running_hint'));
      if (c) {
        c.setOption({
          backgroundColor: 'transparent', animation: false,
          grid: { left: 48, right: 14, top: 34, bottom: 28 }, tooltip: Object.assign({ trigger: 'axis' }, TT), legend: Object.assign({}, LEG),
          xAxis: ax({ type: 'value', scale: true }), yAxis: ax({ type: 'value', scale: true }),
          series: curves.map(function (cv) {
            return { name: starName(cv.name, cv.family) + ' · ' + cv.split + '/' + cv.metric, type: 'line', showSymbol: false, smooth: false, lineStyle: { width: 1.6 }, color: colorFor('run:' + cv.run_id),
              data: cv.x.map(function (x, i) { return [x === null ? i : x, cv.y[i]]; }) };
          })
        }, true);
      }
      var evs = d.events || [];
      $('#ov-events').innerHTML = evs.length ? evs.map(evRow).join('') : emptyBox('no_events', null);
      var r = d.routing;
      if (r && typeof r === 'object') {
        $('#ov-routing').innerHTML = '<div class="kv">' + Object.keys(r).map(function (k) {
          var v = r[k], body;
          if (v && typeof v === 'object') {
            body = (v.model ? '<span class="chip st-running mono">' + esc(v.model) + '</span> ' : '') +
              Object.keys(v).filter(function (kk) { return kk !== 'model'; }).map(function (kk) { return '<div class="small muted">' + esc(tk('route_', kk)) + ': <span style="color:var(--text)">' + esc(typeof v[kk] === 'object' ? JSON.stringify(v[kk]) : v[kk]) + '</span></div>'; }).join('');
          } else body = esc(v);
          return '<dt>' + esc(tk('route_', k)) + '</dt><dd>' + body + '</dd>';
        }).join('') + '</div>';
      } else $('#ov-routing').innerHTML = emptyBox('routing_none', null);
      // race card (leaderboard summary; absent on servers without the leaderboard)
      lbOverview(d.leaderboard);
      // progress briefing (state/briefing.json, written by the orchestrator)
      var b = d.briefing || { missing: true };
      var btxt = b.missing ? '' : String((lang === 'zh' ? (b.zh || b.en) : (b.en || b.zh)) || '');
      var bh = btxt.trim() ? md(btxt) : emptyBox('ov_brief_none', 'ov_brief_none_hint');
      var be = $('#ov-brief');
      if (be.getAttribute('data-h') !== bh) { be.innerHTML = bh; be.setAttribute('data-h', bh); }
      $('#ov-brief-meta').innerHTML = b.missing ? '' : (b.updated ? '<span class="muted" title="' + esc(fmtTime(b.updated)) + '">' + esc(t('updated_at', { t: fmtTime(b.updated) })) + ' · ' + esc(ago(b.updated)) + '</span>' : '') +
        (b.author ? ' <span class="chip mono">' + esc(b.author) + '</span>' : '');
      // milestones & decisions timeline
      var ms = d.milestones || [];
      $('#ov-milestones').innerHTML = ms.length ? ms.map(function (e) {
        return '<div class="mtl-item"><div class="mtl-dot"></div><div class="mtl-body"><div class="mtl-head"><span class="chip mono act">' + esc(e.actor) + '</span>' +
          '<span class="mono small">' + esc(fmtTime(e.ts)) + '</span><span class="dim small">' + esc(ago(e.ts)) + '</span></div><div class="mtl-msg">' + esc(lang === 'zh' ? e.msg_zh : e.msg_en) + '</div></div></div>';
      }).join('') : emptyBox('ov_no_milestones', null);
    }
  };

  // ------------------------------------------------------------------ Workflow
  var W = { sel: LS.get('an_exp_sel', null) };
  function layoutTree(exps) {
    var byId = {}, kids = {}, roots = [], pos = {}, seen = {}, leaf = 0;
    exps.forEach(function (e) { byId[String(e.id)] = e; });
    exps.forEach(function (e) {
      var p = e.parent_id !== undefined && e.parent_id !== null ? String(e.parent_id) : null;
      if (p && byId[p] && p !== String(e.id)) (kids[p] = kids[p] || []).push(e); else roots.push(e);
    });
    var famOrder = { baseline: 0, novel: 1, ablation: 2 };
    roots.sort(function (a, b) { return (famOrder[a.family] === undefined ? 3 : famOrder[a.family]) - (famOrder[b.family] === undefined ? 3 : famOrder[b.family]); });
    var maxDepth = 0;
    function visit(e, depth) {
      var id = String(e.id);
      if (seen[id]) return;
      seen[id] = 1;
      maxDepth = Math.max(maxDepth, depth);
      var ys = [];
      (kids[id] || []).forEach(function (c) { visit(c, depth + 1); if (pos[String(c.id)]) ys.push(pos[String(c.id)][1]); });
      var y = ys.length ? (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2 : leaf++;
      pos[id] = [depth, y];
    }
    roots.forEach(function (r) { visit(r, 0); });
    exps.forEach(function (e) { if (!seen[String(e.id)]) visit(e, 0); });
    return { pos: pos, leaves: Math.max(leaf, 1), maxDepth: maxDepth, byId: byId };
  }
  VIEWS.workflow = {
    mount: function () {
      return '<div class="grid">' +
        '<div class="card s12" data-src="experiments"><h2>' + esc(t('wf_queue')) + '<span class="grow"></span><span class="chips tag" id="wf-q-legend"></span></h2>' +
        '<div class="muted small" id="wf-q-meta" style="margin:-.3rem 0 .4rem"></div><div id="wf-queue" class="chart" style="display:none"></div><div id="wf-queue-empty"></div>' +
        '<div class="tbl-wrap scroll q-tbl" id="wf-q-table"></div></div>' +
        '<div class="card s12" data-src="workflow"><h2>' + esc(t('wf_pipeline')) + '<span class="grow"></span><span class="tag muted small" id="wf-updated"></span></h2><div class="phase-list" id="wf-phases"></div></div>' +
        '<div class="card s12" data-src="workflow"><h2>' + esc(t('wf_gantt')) + '</h2><div id="wf-gantt" class="chart" style="display:none"></div><div id="wf-gantt-empty"></div></div>' +
        '<div class="card s8" data-src="experiments"><h2>' + esc(t('wf_lineage')) + '<span class="grow"></span><span class="chips tag" id="wf-legend"></span></h2><div id="wf-graph" class="chart tall" style="display:none"></div><div id="wf-graph-empty"></div></div>' +
        '<div class="card s4" data-src="experiments"><h2>' + esc(t('wf_details')) + '</h2><div id="wf-detail"></div></div>' +
        '</div>';
    },
    load: function () {
      var self = this;
      return Promise.all([api('/api/workflow'), api('/api/experiments'), api('/api/queue')]).then(function (r) { self.data = { wf: r[0], ex: r[1], q: r[2] }; });
    },
    update: function (d) {
      renderQueue(d.q);
      var wf = d.wf || {}, phases = wf.phases || [];
      frNote('workflow', wf.updated); frNote('experiments', (d.ex || {}).updated || wf.progress_updated);
      // progress source tags (auto = derived server-side from state/experiments.json; shown only when the server says)
      var hasPS = phases.some(function (p) { return p.progress_source === 'auto' || p.progress_source === 'manual'; });
      var nAuto = phases.filter(function (p) { return p.progress_source === 'auto'; }).length;
      $('#wf-updated').innerHTML = hasPS ? '<span title="' + esc(t('wf_ps_auto_tip') + '\n' + t('wf_ps_manual_tip')) + '">' + esc(t('wf_ps_summary', { a: nAuto, m: phases.length - nAuto })) + '</span>' +
        (wf.progress_error ? ' <span class="chip lv-warn" title="' + esc(wf.progress_error) + '">' + esc(t('wf_ps_error')) + '</span>' : '') : '';
      function psTag(p) {
        if (!hasPS) return '';
        var auto = p.progress_source === 'auto', det = p.progress_auto || p.progress_detail || p.progress_counts, tip = t(auto ? 'wf_ps_auto_tip' : 'wf_ps_manual_tip');
        if (auto && det && typeof det === 'object') {
          var nd = isNum(det.done) ? det.done : null, nt = isNum(det.total) ? det.total : (isNum(det.done) ? det.done + (det.running || 0) + (det.queued || 0) : null);
          if (isNum(det.ok) && isNum(nt)) tip += '\n' + t('wf_ps_counts_eval', { ok: det.ok, n: nt });
          else if (isNum(nd) && isNum(nt)) tip += '\n' + t('wf_ps_counts', { d: nd, n: nt, r: det.running || 0, q: det.queued || 0 });
          if (det.rule) tip += '\n' + String(det.rule);
        }
        if (!auto && isNum(p.progress_manual) && det && isNum(det.progress)) tip += '\n' + t('wf_ps_auto_alt', { p: fmtPct(det.progress) });
        return '<span class="tag tiny ps-tag ps-' + (auto ? 'auto' : 'manual') + '" title="' + esc(tip) + '">' + esc(t(auto ? 'wf_ps_auto' : 'wf_ps_manual')) + '</span>';
      }
      $('#wf-phases').innerHTML = phases.length ? phases.map(function (p, i) {
        var st = toDate(p.started), en = toDate(p.ended);
        var dur = st ? ((en ? en.getTime() : Date.now()) - st.getTime()) / 1000 : null;
        var notes = bi(p, 'notes');
        return '<div class="phase-card ' + esc(p.status) + '"><div class="hd"><span class="mono dim">' + pad(i + 1) + '</span><span class="nm">' + esc(bi(p, 'name')) + '</span>' + psTag(p) + stChip(p.status) + '</div>' +
          bar(p.status === 'done' ? 1 : p.progress, p.status === 'failed' ? 'red' : '') +
          '<div class="meta">' + esc(t('started')) + ' ' + esc(fmtTime(p.started)) + (p.ended ? ' · ' + esc(t('ended')) + ' ' + esc(fmtTime(p.ended)) : '') + (dur !== null ? ' · ' + esc(fmtDur(dur)) : '') + ' · ' + fmtPct(p.status === 'done' ? 1 : p.progress) + '</div>' +
          (notes ? '<div class="notes">' + esc(notes) + '</div>' : '') + '</div>';
      }).join('') : emptyBox('wf_none', 'wf_none_hint');

      // Gantt
      var started = phases.filter(function (p) { return toDate(p.started); });
      var gh = Math.max(220, phases.length * 30 + 70);
      var g = chartOrEmpty('wf-gantt', started.length > 0, emptyBox('wf_gantt_none', null), gh);
      if (g) {
        var now = Date.now();
        var cats = phases.map(function (p) { return bi(p, 'name'); });
        var data = [];
        phases.forEach(function (p, i) {
          var s = toDate(p.started);
          if (!s) return;
          var e = toDate(p.ended);
          var end = e ? e.getTime() : now;
          data.push({ value: [i, s.getTime(), Math.max(end, s.getTime() + 1000), p.status, clamp01(p.status === 'done' ? 1 : p.progress)], itemStyle: { color: ST_COLOR[p.status] || '#8296b3' } });
        });
        g.setOption({
          backgroundColor: 'transparent', animation: false,
          grid: { left: 12, right: 30, top: 16, bottom: 30, containLabel: true },
          tooltip: Object.assign({ formatter: function (pr) {
            var v = pr.value;
            return esc(cats[v[0]]) + '<br>' + esc(tk('st_', v[3])) + ' · ' + fmtPct(v[4]) + '<br>' + esc(fmtTime(v[1])) + ' → ' + esc(fmtTime(v[2])) + '<br>' + esc(fmtDur((v[2] - v[1]) / 1000));
          } }, TT),
          xAxis: ax({ type: 'time', min: function (v) { return v.min - Math.max(60000, (v.max - v.min) * 0.03); }, max: function (v) { return Math.max(v.max, now) + Math.max(60000, (v.max - v.min) * 0.05); } }),
          yAxis: ax({ type: 'category', data: cats, inverse: true, splitLine: { show: false } }),
          series: [{
            type: 'custom', encode: { x: [1, 2], y: 0 }, data: data,
            renderItem: function (params, a) {
              var y = a.value(0), s = a.coord([a.value(1), y]), e = a.coord([a.value(2), y]);
              var h = a.size([0, 1])[1] * 0.56, w = Math.max(e[0] - s[0], 3);
              var cs = params.coordSys;
              var rect = window.echarts.graphic.clipRectByRect({ x: s[0], y: s[1] - h / 2, width: w, height: h }, { x: cs.x, y: cs.y, width: cs.width, height: cs.height });
              if (!rect) return null;
              var col = a.visual('color');
              return { type: 'group', children: [
                { type: 'rect', shape: rect, style: { fill: col, opacity: 0.28 } },
                { type: 'rect', shape: { x: rect.x, y: rect.y, width: rect.width * a.value(4), height: rect.height }, style: { fill: col, opacity: 0.85 } }
              ] };
            },
            markLine: { symbol: 'none', silent: true, data: [{ xAxis: now }], lineStyle: { color: CC.amber, type: 'dashed' }, label: { formatter: t('now'), color: CC.amber } }
          }]
        }, true);
      }

      // lineage
      var exps = ((d.ex || {}).experiments || []).filter(function (e) { return e && e.id !== undefined && e.id !== null; });
      $('#wf-legend').innerHTML = ['baseline', 'novel', 'ablation'].map(function (f) { return '<span class="chip"><span class="dot" style="background:' + FAM_COLOR[f] + '"></span>' + esc(tk('fam_', f)) + '</span>'; }).join('') +
        '<span class="chip"><span class="dot run"></span>' + esc(t('st_running')) + '</span><span class="chip st-pruned">' + esc(t('st_pruned')) + '</span>';
      var L = layoutTree(exps);
      var gg = chartOrEmpty('wf-graph', exps.length > 0, emptyBox('wf_no_exps', 'wf_no_exps_hint'), Math.max(360, L.leaves * 44 + 40));
      if (gg) {
        var nodes = exps.map(function (e) {
          var id = String(e.id), p = L.pos[id], col = FAM_COLOR[e.family] || '#8296b3';
          var dead = e.status === 'pruned' || e.status === 'skipped';
          return {
            name: id, id: id, value: p, symbolSize: e.status === 'running' ? 20 : 15,
            itemStyle: { color: e.status === 'queued' ? '#070d19' : (dead ? '#3b4a63' : col), borderColor: dead ? '#50627e' : (e.status === 'failed' ? '#f87171' : col), borderWidth: 2, opacity: dead ? 0.55 : 1 },
            label: { show: true, position: 'right', color: dead ? '#50627e' : (isOursFam(e.family) ? '#fde68a' : CC.text), fontWeight: isOursFam(e.family) ? 'bold' : 'normal', fontSize: 11, formatter: starName(clip(e.name || id, isOursFam(e.family) ? 25 : 28), e.family) }
          };
        });
        var links = exps.filter(function (e) { return e.parent_id !== undefined && e.parent_id !== null && L.byId[String(e.parent_id)] && String(e.parent_id) !== String(e.id); })
          .map(function (e) { return { source: String(e.parent_id), target: String(e.id) }; });
        var running = exps.filter(function (e) { return e.status === 'running'; }).map(function (e) { return { value: L.pos[String(e.id)], itemStyle: { color: FAM_COLOR[e.family] || CC.cyan } }; });
        gg.setOption({
          backgroundColor: 'transparent', animation: false,
          grid: { left: 20, right: 170, top: 20, bottom: 20 },
          tooltip: Object.assign({ formatter: function (pr) {
            if (pr.seriesType !== 'graph' || pr.dataType !== 'node') return '';
            var e = L.byId[pr.data.id] || {};
            return '<b>' + esc(e.name || e.id) + '</b><br>' + esc(tk('fam_', e.family)) + ' · ' + esc(tk('st_', e.status)) + (bi(e, 'hypothesis') ? '<br><span style="color:#8296b3">' + esc(clip(bi(e, 'hypothesis'), 160)) + '</span>' : '');
          } }, TT),
          xAxis: { type: 'value', show: false, min: -0.25, max: L.maxDepth + 0.6 },
          yAxis: { type: 'value', show: false, inverse: true, min: -0.7, max: L.leaves - 0.3 },
          series: [
            { type: 'effectScatter', coordinateSystem: 'cartesian2d', data: running, symbolSize: 20, rippleEffect: { scale: 2.6, brushType: 'stroke' }, silent: true, z: 1 },
            { type: 'graph', coordinateSystem: 'cartesian2d', data: nodes, links: links, edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 7, lineStyle: { color: '#2a4a72', width: 1.4, curveness: 0.12, opacity: 0.9 }, emphasis: { focus: 'adjacency' }, z: 2 }
          ]
        }, true);
        gg.off('click');
        gg.on('click', function (pr) { if (pr.seriesType === 'graph' && pr.dataType === 'node') { W.sel = pr.data.id; LS.set('an_exp_sel', W.sel); renderExpDetail(L.byId); } });
      }
      renderExpDetail(L.byId, exps);
    }
  };
  // ------------------------------------------------------------------ experiment queue (Gantt + table)
  var Q_STYLE = {
    done: { fill: 'rgba(52,211,153,0.55)', stroke: '#34d399' }, running: { fill: 'rgba(34,211,238,0.55)', stroke: '#22d3ee' },
    failed: { fill: 'rgba(248,113,113,0.6)', stroke: '#f87171' }, queued: { fill: 'rgba(130,150,179,0.10)', stroke: '#6b7f9e', dash: [4, 3] }
  };
  function laneName(l) { return l === 'any' ? t('lane_any') : 'GPU ' + l; }
  /** keep the user's dataZoom window across the 4 s refresh (setOption(..., true) would reset it) */
  function keepZoom(c, dz) {
    try {
      var o = c.getOption(), cur = o && o.dataZoom;
      if (cur && cur.length) dz.forEach(function (z, i) { var k = cur[i]; if (k && isNum(k.start) && isNum(k.end)) { z.start = k.start; z.end = k.end; delete z.startValue; delete z.endValue; } });
    } catch (e) { /* first render */ }
    return dz;
  }
  function renderQueue(q) {
    var lanes = (q && q.lanes) || [], now = toDate(q && q.now) || new Date();
    var items = [];
    lanes.forEach(function (L, li) { (L.items || []).forEach(function (it) { var s = toDate(it.start), e = toDate(it.end); if (s && e) items.push({ it: it, li: li, lane: L.lane, s: s.getTime(), e: Math.max(e.getTime(), s.getTime() + 60000) }); }); });
    var cn = (q && q.counts) || {}, du = (q && q.durations) || {};
    $('#wf-q-legend').innerHTML = ['done', 'running', 'failed', 'queued'].map(function (k) {
      return '<span class="chip"><span class="qsw' + (k === 'queued' ? ' dash' : '') + '" style="background:' + Q_STYLE[k].fill + ';border-color:' + Q_STYLE[k].stroke + '"></span>' + esc(tk('st_', k)) + '</span>';
    }).join('') + ['baseline', 'novel', 'ablation'].map(function (f) { return '<span class="chip"><span class="qsw stripe" style="background:' + FAM_COLOR[f] + '"></span>' + esc(tk('fam_', f)) + '</span>'; }).join('');
    var famMed = du.median_s_by_family || {};
    $('#wf-q-meta').innerHTML = q && q.ok !== false ? esc(t('q_meta', { r: cn.running || 0, q: cn.queued || 0, d: cn.done || 0, f: cn.failed || 0, p: cn.skipped_planned || 0, x: (cn.skipped_pruned || 0) + (cn.skipped_eval_only || 0) })) +
      ' · ' + esc(t('q_durations')) + ' ' + Object.keys(famMed).map(function (f) { return esc(tk('fam_', f)) + ' ' + esc(fmtDur(famMed[f])); }).join('; ') +
      (isNum(du.median_s_all) ? ' · ' + esc(t('q_dur_all')) + ' ' + esc(fmtDur(du.median_s_all)) : ' · ' + esc(t('q_dur_default'))) +
      (q.eta_end ? ' · <b style="color:var(--cyan)">' + esc(t('q_eta', { t: fmtTime(q.eta_end) })) + '</b>' : '') : '';
    var c = chartOrEmpty('wf-queue', items.length > 0, emptyBox('q_none', 'q_none_hint'), Math.max(170, lanes.length * 64 + 90));
    if (c) {
      var nowMs = now.getTime();
      var data = items.map(function (x, i) { return { value: [x.li, x.s, x.e, i] }; });
      var dz = keepZoom(c, [{ type: 'inside', xAxisIndex: 0, filterMode: 'weakFilter' }, { type: 'slider', xAxisIndex: 0, filterMode: 'weakFilter', height: 14, bottom: 6, borderColor: '#24466e', textStyle: { color: CC.muted }, fillerColor: 'rgba(34,211,238,0.12)', moveHandleSize: 5, moveHandleStyle: { color: '#24466e' }, handleStyle: { color: '#22d3ee', borderColor: '#0a1222' }, brushSelect: false, labelFormatter: function (v) { return fmtTime(v).slice(0, 11); } }]);
      c.setOption({
        backgroundColor: 'transparent', animation: false,
        grid: { left: 8, right: 24, top: 18, bottom: 48, containLabel: true },
        tooltip: Object.assign({ formatter: function (pr) {
          var x = items[pr.value[3]]; if (!x) return '';
          var it = x.it;
          return '<b>' + esc(it.id) + '</b> ' + esc(tk('fam_', it.family)) + '<br>' + esc(clip(it.name, 80)) + '<br>' + esc(tk('st_', it.status)) + ' · ' + esc(laneName(x.lane)) + (it.any_lane ? ' (' + esc(t('lane_any')) + ')' : '') + ' · P' + esc(it.priority) +
            '<br>' + esc(t('started')) + ' ' + esc(fmtTime(it.start)) + '<br>' + esc(it.estimated ? t('q_end_est') : t('ended')) + ' ' + esc(fmtTime(it.end)) +
            '<br>' + esc(t('q_duration')) + ' ' + esc(fmtDur(it.duration_s)) + (it.duration_src ? ' <span style="color:#8296b3">(' + esc(tk('q_src_', it.duration_src)) + ')</span>' : '') +
            (isNum(it.epoch) ? '<br>' + esc(t('epoch')) + ' ' + esc(it.epoch) + ' / ' + esc(it.total_epochs) : '') +
            '<br>val_dice ' + esc(fmt(it.val_dice, 4));
        } }, TT),
        xAxis: ax({ type: 'time', min: function (v) { return v.min - Math.max(600000, (v.max - v.min) * 0.01); }, max: function (v) { return v.max + Math.max(600000, (v.max - v.min) * 0.01); } }),
        yAxis: ax({ type: 'category', data: lanes.map(function (L) { return laneName(L.lane); }), inverse: true, splitLine: { show: false }, axisLabel: { color: CC.text, fontWeight: 600 } }),
        dataZoom: dz,
        series: [{
          type: 'custom', encode: { x: [1, 2], y: 0 }, data: data, clip: true,
          renderItem: function (params, a) {
            var x = items[a.value(3)]; if (!x) return null;
            var it = x.it, li = a.value(0), s = a.coord([a.value(1), li]), e = a.coord([a.value(2), li]);
            var h = a.size([0, 1])[1] * 0.56, cs = params.coordSys;
            var rect = window.echarts.graphic.clipRectByRect({ x: s[0], y: s[1] - h / 2, width: Math.max(e[0] - s[0], 2), height: h }, { x: cs.x, y: cs.y, width: cs.width, height: cs.height });
            if (!rect) return null;
            var st = Q_STYLE[it.status] || Q_STYLE.queued, kids = [];
            if (it.status === 'running') {
              var nx = Math.min(Math.max(a.coord([nowMs, li])[0], rect.x), rect.x + rect.width);
              kids.push({ type: 'rect', shape: { x: rect.x, y: rect.y, width: nx - rect.x, height: rect.height }, style: { fill: st.fill } });
              kids.push({ type: 'rect', shape: { x: nx, y: rect.y, width: rect.x + rect.width - nx, height: rect.height }, style: { fill: 'rgba(34,211,238,0.14)', stroke: st.stroke, lineDash: [4, 3], lineWidth: 1 } });
              kids.push({ type: 'rect', shape: rect, style: { fill: 'none', stroke: st.stroke, lineWidth: 1.4 } });
            } else {
              kids.push({ type: 'rect', shape: rect, style: { fill: st.fill, stroke: st.stroke, lineWidth: 1, lineDash: st.dash || null } });
            }
            kids.push({ type: 'rect', shape: { x: rect.x, y: rect.y, width: Math.min(4, rect.width), height: rect.height }, style: { fill: FAM_COLOR[it.family] || '#8296b3' } });
            if (isOursFam(it.family)) kids.push({ type: 'rect', shape: rect, style: { fill: 'none', stroke: '#fbbf24', lineWidth: 1 } });
            if (rect.width > 26) kids.push({ type: 'text', style: { text: String(it.id), x: rect.x + 7, y: rect.y + rect.height / 2, fill: it.status === 'queued' ? '#b9c7dc' : '#f1f5fb', font: '11px ' + 'sans-serif', textVerticalAlign: 'middle', width: rect.width - 10, overflow: 'truncate', ellipsis: '…' } });
            return { type: 'group', children: kids };
          },
          markLine: { symbol: 'none', silent: true, data: [{ xAxis: nowMs }], lineStyle: { color: CC.amber, type: 'dashed', width: 1.5 }, label: { formatter: t('now'), color: CC.amber } }
        }]
      }, true);
    }
    // compact table: running, then queued in projected order, then finished (newest first)
    var rk = { running: 0, queued: 1, done: 2, failed: 2 };
    var rows = items.slice().sort(function (a, b) { var ra = rk[a.it.status] === undefined ? 3 : rk[a.it.status], rb = rk[b.it.status] === undefined ? 3 : rk[b.it.status]; return ra - rb || (ra === 2 ? b.e - a.e : a.s - b.s); });
    var th = ['#', 'q_col_lane', 'q_col_id', 'q_col_name', 'q_col_family', 'q_col_status', 'q_col_priority', 'started', 'q_col_end', 'q_col_dice'];
    var html = rows.length ? '<table class="tbl"><thead><tr>' + th.map(function (k, i) { return '<th' + (i >= 6 ? ' class="right"' : '') + '>' + esc(k === '#' ? '#' : t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.map(function (x, i) {
      var it = x.it;
      return '<tr class="' + (it.status === 'running' ? 'q-running' : it.status === 'queued' ? 'q-queued' : '') + (isOursFam(it.family) ? ' ours-row' : '') + '"><td class="mono dim">' + (i + 1) + '</td><td class="mono">' + esc(laneName(x.lane)) + (it.any_lane ? ' <span class="dim tiny">(' + esc(t('lane_any')) + ')</span>' : '') + '</td>' +
        '<td class="mono">' + esc(it.id) + '</td><td class="small">' + esc(clip(it.name, 70)) + '</td><td>' + famChip(it.family) + '</td><td>' + stChip(it.status) + '</td>' +
        '<td class="num">' + esc(it.priority) + '</td><td class="num small">' + esc(fmtTime(it.start)) + '</td><td class="num small">' + (it.estimated ? '≈ ' : '') + esc(fmtTime(it.end)) + '</td><td class="num">' + esc(fmt(it.val_dice, 4)) + '</td></tr>';
    }).join('') + '</tbody></table>' : '';
    var te = $('#wf-q-table');
    if (te.getAttribute('data-h') !== html) { var sc = te.scrollTop; te.innerHTML = html; te.setAttribute('data-h', html); te.scrollTop = sc; }
  }
  function renderExpDetail(byId, exps) {
    var el = $('#wf-detail');
    if (!el) return;
    var e = W.sel !== null && byId[String(W.sel)];
    if (!e && exps && exps.length) e = exps.filter(function (x) { return x.status === 'running'; })[0] || exps[exps.length - 1];
    if (!e) { el.innerHTML = emptyBox('wf_detail_none', 'wf_detail_hint'); return; }
    var ms = e.metrics_summary && typeof e.metrics_summary === 'object' ? e.metrics_summary : {};
    var runId = e.run_dir ? String(e.run_dir).replace(/\/+$/, '').split('/').pop() : null;
    var html = '<div class="card-h" style="text-transform:none;letter-spacing:0;font-size:1rem;color:var(--text)">' + esc(e.name || e.id) + '</div>' +
      '<div class="chips" style="margin-bottom:.6rem">' + famChip(e.family) + stChip(e.status) + '<span class="chip mono">' + esc(e.id) + '</span></div><dl class="kv">' +
      '<dt>' + esc(t('exp_parent')) + '</dt><dd class="mono">' + esc(e.parent_id === undefined || e.parent_id === null ? '—' : e.parent_id) + '</dd>' +
      '<dt>' + esc(t('exp_hypothesis')) + '</dt><dd>' + esc(bi(e, 'hypothesis') || '—') + '</dd>' +
      '<dt>' + esc(t('exp_verdict')) + '</dt><dd>' + esc(bi(e, 'verdict') || '—') + '</dd>' +
      '<dt>' + esc(t('exp_rundir')) + '</dt><dd class="mono small">' + esc(e.run_dir || '—') + '</dd>' +
      '<dt>GPU</dt><dd class="mono">' + esc(e.gpu === undefined || e.gpu === null ? '—' : e.gpu) + '</dd></dl>';
    var keys = Object.keys(ms);
    html += '<div class="card-h" style="margin-top:.8rem">' + esc(t('exp_metrics')) + '</div>' + (keys.length ? '<table class="tbl"><tbody>' + keys.map(function (k) {
      var v = ms[k];
      return '<tr><td class="mono">' + esc(k) + '</td><td class="num">' + esc(isNum(v) ? fmt(v, 4) : (typeof v === 'object' ? JSON.stringify(v) : v)) + '</td></tr>';
    }).join('') + '</tbody></table>' : '<div class="muted small">' + esc(t('exp_no_metrics')) + '</div>');
    if (runId) html += '<div style="margin-top:.7rem"><button class="btn" type="button" id="wf-open-run" data-run="' + esc(runId) + '">' + esc(t('open_in_training')) + ' →</button></div>';
    el.innerHTML = html;
    var b = $('#wf-open-run');
    if (b) b.addEventListener('click', function () { var id = b.getAttribute('data-run'); if (T.sel.indexOf(id) < 0) T.sel.push(id); T.focus = id; T.init = true; LS.set('an_runs_sel', T.sel); location.hash = '#/training'; });
  }

  // ------------------------------------------------------------------ Training
  var T = { sel: LS.get('an_runs_sel', []), metric: LS.get('an_tr_metric', ''), split: LS.get('an_tr_split', 'val'), xaxis: LS.get('an_tr_x', 'step'), smooth: LS.get('an_tr_smooth', 0.6), logy: false, focus: null, follow: true, init: false };
  if (!Array.isArray(T.sel)) T.sel = [];
  T.hidden = LS.get('an_tr_hidden', false) === true;
  /** `_discarded`, other `_*` and `*_smoke` run dirs are hidden unless 显示隐藏运行 is on (server flag `hidden` wins) */
  function isHiddenRun(r) { return r && (r.hidden === true || (r.hidden === undefined && /^_|_smoke$/i.test(String(r.run_id || '')))); }
  function runName(r) { return (r && r.status && r.status.name) || (r && r.run_id) || '?'; }
  /** gold badge for our own runs, violet chip for ablations, nothing for baselines / unknown */
  function runFamChip(r) { var f = r && r.family; return isOursFam(f) || f === 'ablation' ? famChip(f) : ''; }
  function ema(vals, w) {
    var out = [], last = 0, num = 0;
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      if (!isNum(v)) { out.push(null); continue; }
      last = last * w + (1 - w) * v; num = num * w + (1 - w);
      out.push(last / num);
    }
    return out;
  }
  VIEWS.training = {
    src: 'runs',
    mount: function () {
      return '<div class="grid" id="tr-emptywrap"><div class="card s12"><h2>' + esc(t('tab_training')) + '</h2>' + emptyBox('tr_no_runs', 'tr_no_runs_hint') + '</div></div>' +
        '<div id="tr-main" style="display:none">' +
        '<div class="grid">' +
        '<div class="card s3"><h2>' + esc(t('tr_runs')) + '<span class="grow"></span><span class="tag muted small" id="tr-count"></span></h2>' +
        '<div class="controls"><button class="btn" type="button" id="tr-sel-running">' + esc(t('tr_sel_running')) + '</button><button class="btn" type="button" id="tr-sel-all">' + esc(t('tr_sel_all')) + '</button><button class="btn" type="button" id="tr-sel-none">' + esc(t('tr_sel_none')) + '</button>' +
        '<label class="tag small tr-hidden-lbl" title="' + esc(t('tr_show_hidden_tip')) + '"><input type="checkbox" id="tr-hidden"> ' + esc(t('tr_show_hidden')) + ' <span class="mono dim" id="tr-hidden-n"></span></label></div>' +
        '<div class="run-list" id="tr-runlist"></div></div>' +
        '<div class="card s9"><h2>' + esc(t('tr_curves')) + '</h2><div class="controls">' +
        '<label>' + esc(t('tr_metric')) + ' <select id="tr-metric"></select></label>' +
        '<span class="seg" id="tr-split"><button type="button" data-v="train">' + esc(t('split_train')) + '</button><button type="button" data-v="val">' + esc(t('split_val')) + '</button><button type="button" data-v="test">' + esc(t('split_test')) + '</button></span>' +
        '<label>' + esc(t('tr_xaxis')) + '</label><span class="seg" id="tr-xaxis"><button type="button" data-v="step">' + esc(t('tr_step')) + '</button><button type="button" data-v="epoch">' + esc(t('tr_epoch')) + '</button></span>' +
        '<label>' + esc(t('tr_smoothing')) + ' <input type="range" id="tr-smooth" min="0" max="0.99" step="0.01"> <span class="mono" id="tr-smooth-v"></span></label>' +
        '<label><input type="checkbox" id="tr-logy"> ' + esc(t('tr_logy')) + '</label></div>' +
        '<div id="tr-chart" class="chart xtall" style="display:none"></div><div id="tr-chart-empty"></div></div>' +
        '</div>' +
        '<div class="grid"><div class="card s12"><h2>' + esc(t('tr_status')) + '</h2><div class="run-cards" id="tr-cards"></div></div></div>' +
        '<div class="grid">' +
        '<div class="card s7"><h2>' + esc(t('tr_log')) + '<span class="grow"></span><select id="tr-focus" class="tag"></select><label class="tag small"><input type="checkbox" id="tr-follow" checked> ' + esc(t('follow')) + '</label></h2><pre class="log" id="tr-log"></pre></div>' +
        '<div class="card s5"><h2>' + esc(t('tr_samples')) + '<span class="grow"></span><span class="tag muted small" id="tr-samples-n"></span></h2><div id="tr-samples"></div></div>' +
        '</div></div>';
    },
    bind: function () {
      var self = this;
      function save() { LS.set('an_runs_sel', T.sel); LS.set('an_tr_metric', T.metric); LS.set('an_tr_split', T.split); LS.set('an_tr_x', T.xaxis); LS.set('an_tr_smooth', T.smooth); }
      $('#tr-runlist').addEventListener('click', function (e) {
        var it = e.target.closest('.run-item');
        if (!it) return;
        var id = it.getAttribute('data-id'), i = T.sel.indexOf(id);
        if (i >= 0) T.sel.splice(i, 1); else { T.sel.push(id); T.focus = id; }
        save(); refreshNow();
      });
      $('#tr-sel-running').addEventListener('click', function () { T.sel = (self.runs || []).filter(function (r) { return r.status.state === 'running'; }).map(function (r) { return r.run_id; }); save(); refreshNow(); });
      $('#tr-sel-all').addEventListener('click', function () { T.sel = (self.runs || []).slice(0, 24).map(function (r) { return r.run_id; }); save(); refreshNow(); });
      $('#tr-sel-none').addEventListener('click', function () { T.sel = []; save(); refreshNow(); });
      $('#tr-metric').addEventListener('change', function (e) { T.metric = e.target.value; save(); refreshNow(); });
      $('#tr-split').addEventListener('click', function (e) { var b = e.target.closest('button'); if (b && !b.disabled) { T.split = b.getAttribute('data-v'); save(); refreshNow(); } });
      $('#tr-xaxis').addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { T.xaxis = b.getAttribute('data-v'); save(); if (self.data) self.update(self.data); } });
      $('#tr-smooth').addEventListener('input', function (e) { T.smooth = parseFloat(e.target.value) || 0; save(); if (self.data) self.drawChart(self.data); $('#tr-smooth-v').textContent = T.smooth.toFixed(2); });
      $('#tr-logy').addEventListener('change', function (e) { T.logy = e.target.checked; if (self.data) self.drawChart(self.data); });
      $('#tr-focus').addEventListener('change', function (e) { T.focus = e.target.value; refreshNow(); });
      $('#tr-follow').addEventListener('change', function (e) { T.follow = e.target.checked; });
      $('#tr-hidden').checked = T.hidden;
      $('#tr-hidden').addEventListener('change', function (e) { T.hidden = e.target.checked; LS.set('an_tr_hidden', T.hidden); refreshNow(); });
    },
    load: function () {
      var self = this;
      return api('/api/runs' + (T.hidden ? '?hidden=1' : '')).then(function (rr) {
        var all = (rr && rr.runs) || [];
        var runs = T.hidden ? all : all.filter(function (r) { return !isHiddenRun(r); });
        var nHid = rr && isNum(rr.n_hidden) ? rr.n_hidden : all.filter(isHiddenRun).length;
        self.runs = runs;
        frNote('runs', rr && rr.updated);
        var ids = runs.map(function (r) { return r.run_id; });
        T.sel = T.sel.filter(function (id) { return ids.indexOf(id) >= 0; });
        if (!T.init && runs.length) {
          T.init = true;
          if (!T.sel.length) {
            T.sel = runs.filter(function (r) { return r.status.state === 'running'; }).slice(0, 8).map(function (r) { return r.run_id; });
            if (!T.sel.length) T.sel = ids.slice(0, 3);
          }
        }
        // metric/split options from selected runs (or all)
        var pool = runs.filter(function (r) { return T.sel.indexOf(r.run_id) >= 0; });
        if (!pool.length) pool = runs;
        var splits = {}, names = {};
        pool.forEach(function (r) { (r.series || []).forEach(function (s) { splits[s.split] = 1; if (s.split === T.split) names[s.name] = 1; }); });
        if (!splits[T.split] && Object.keys(splits).length) {
          T.split = splits.val ? 'val' : (splits.train ? 'train' : Object.keys(splits)[0]);
          names = {};
          pool.forEach(function (r) { (r.series || []).forEach(function (s) { if (s.split === T.split) names[s.name] = 1; }); });
        }
        var nameList = Object.keys(names).sort();
        if (nameList.indexOf(T.metric) < 0) T.metric = nameList.indexOf('dice') >= 0 ? 'dice' : (nameList.indexOf('loss') >= 0 ? 'loss' : (nameList[0] || ''));
        if (T.sel.indexOf(T.focus) < 0) T.focus = T.sel[0] || ids[0] || null;
        var jobs = T.sel.slice(0, 24).map(function (id) {
          return T.metric ? api('/api/runs/' + enc(id) + '/metrics?name=' + enc(T.metric) + '&split=' + enc(T.split)).then(function (m) { return [id, m]; }) : Promise.resolve([id, null]);
        });
        var fjobs = T.focus ? [api('/api/runs/' + enc(T.focus) + '/log?lines=200'), api('/api/runs/' + enc(T.focus) + '/samples')] : [Promise.resolve(null), Promise.resolve(null)];
        return Promise.all([Promise.all(jobs), Promise.all(fjobs)]).then(function (res) {
          var series = {};
          res[0].forEach(function (p) { series[p[0]] = p[1]; });
          self.data = { runs: runs, series: series, splits: Object.keys(splits), names: nameList, log: res[1][0], samples: res[1][1], focus: T.focus, nHidden: nHid };
        });
      });
    },
    update: function (d) {
      var runs = d.runs || [], anyRuns = runs.length > 0 || (isNum(d.nHidden) && d.nHidden > 0);
      $('#tr-emptywrap').style.display = anyRuns ? 'none' : '';
      $('#tr-main').style.display = anyRuns ? '' : 'none';
      if (!anyRuns) return;
      $('#tr-count').textContent = t('n_runs', { n: runs.length, s: T.sel.length });
      $('#tr-hidden').checked = T.hidden;
      $('#tr-hidden-n').textContent = isNum(d.nHidden) && d.nHidden > 0 ? '(' + d.nHidden + ')' : '';
      if (!toDate(FR.note.runs)) {  // older servers: newest status.json `updated` as the runs timestamp
        var newest = null;
        runs.forEach(function (r) { var u = toDate((r.status || {}).updated); if (u && (!newest || u > newest)) newest = u; });
        if (newest) frNote('runs', newest.toISOString());
      }
      $('#tr-runlist').innerHTML = !runs.length ? '<div class="muted small">' + esc(t('tr_all_hidden', { n: d.nHidden })) + '</div>' : runs.map(function (r) {
        var st = r.status || {}, sel = T.sel.indexOf(r.run_id) >= 0;
        var ep = isNum(st.epoch) ? st.epoch + (isNum(st.total_epochs) ? '/' + st.total_epochs : '') : '';
        return '<div class="run-item' + (sel ? ' sel' : '') + (isOursFam(r.family) ? ' ours-card' : '') + '" data-id="' + esc(r.run_id) + '" title="' + esc(r.run_id) + '"><input type="checkbox" tabindex="-1" ' + (sel ? 'checked' : '') + '>' +
          '<span class="sw" style="background:' + colorFor('run:' + r.run_id) + '"></span><span class="nm-wrap"><span class="nm">' + esc(runName(r)) + '</span>' + runFamChip(r) + (isHiddenRun(r) ? '<span class="chip tiny st-pruned" title="' + esc(t('tr_hidden_tip')) + '">' + esc(t('tr_hidden_chip')) + '</span>' : '') + '</span><span>' + stChip(st.state || 'unknown') + (ep ? ' <span class="mono tiny muted">' + esc(ep) + '</span>' : '') + '</span></div>';
      }).join('');
      var ms = $('#tr-metric');
      var opts = d.names.map(function (n) { return '<option value="' + esc(n) + '"' + (n === T.metric ? ' selected' : '') + '>' + esc(n) + '</option>'; }).join('');
      if (ms.getAttribute('data-h') !== opts) { ms.innerHTML = opts || '<option value="">—</option>'; ms.setAttribute('data-h', opts); }
      $$('#tr-split button').forEach(function (b) { var v = b.getAttribute('data-v'); b.classList.toggle('on', v === T.split); b.disabled = d.splits.indexOf(v) < 0; b.style.opacity = b.disabled ? 0.35 : 1; });
      $$('#tr-xaxis button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === T.xaxis); });
      $('#tr-smooth').value = T.smooth;
      $('#tr-smooth-v').textContent = Number(T.smooth).toFixed(2);
      $('#tr-logy').checked = T.logy;
      this.drawChart(d);
      // status cards
      var shown = runs.filter(function (r) { return T.sel.indexOf(r.run_id) >= 0; });
      if (!shown.length) shown = runs.slice(0, 12);
      $('#tr-cards').innerHTML = shown.map(function (r) {
        var st = r.status || {}, col = colorFor('run:' + r.run_id);
        var prog = isNum(st.epoch) && isNum(st.total_epochs) && st.total_epochs > 0 ? st.epoch / st.total_epochs : null;
        var upd = toDate(st.updated);
        var stale = st.state === 'running' && upd && (Date.now() - upd.getTime()) > 600000;
        var best = st.best && typeof st.best === 'object' ? Object.keys(st.best).map(function (k) { return '<dt class="mono">' + esc(k) + '</dt><dd class="mono">' + esc(isNum(st.best[k]) ? fmt(st.best[k], 4) : st.best[k]) + '</dd>'; }).join('') : '';
        return '<div class="run-card' + (isOursFam(r.family) ? ' ours-card' : '') + '" style="border-left-color:' + col + '"><div class="ttl"><span class="nm" title="' + esc(r.run_id) + '">' + esc(runName(r)) + '</span>' + runFamChip(r) + stChip(st.state || 'unknown') + (stale ? '<span class="chip lv-warn">' + esc(t('stale')) + '</span>' : '') + '</div>' +
          '<div class="muted small mono">' + esc(r.run_id) + (st.exp_id ? ' · ' + esc(st.exp_id) : '') + '</div>' +
          '<div class="small">' + esc(t('epoch')) + ' <span class="mono">' + esc(isNum(st.epoch) ? st.epoch : '—') + ' / ' + esc(isNum(st.total_epochs) ? st.total_epochs : '—') + '</span> · ' + esc(t('eta')) + ' <span class="mono">' + esc(st.state === 'running' ? fmtDur(st.eta_s) : '—') + '</span> · GPU <span class="mono">' + esc(st.gpu === undefined || st.gpu === null ? '—' : st.gpu) + '</span></div>' +
          bar(prog) + (best ? '<dl class="kv small">' + best + '</dl>' : '<div class="muted small">' + esc(t('no_best')) + '</div>') +
          '<div class="muted tiny">' + esc(t('started')) + ' ' + esc(fmtTime(st.started)) + ' · ' + esc(t('updated')) + ' ' + esc(ago(st.updated || r.mtime)) + '</div></div>';
      }).join('');
      // log
      var fs = $('#tr-focus');
      var fopts = T.sel.map(function (id) { var r = runs.filter(function (x) { return x.run_id === id; })[0]; return '<option value="' + esc(id) + '"' + (id === T.focus ? ' selected' : '') + '>' + esc(runName(r) || id) + '</option>'; }).join('');
      if (fs.getAttribute('data-h') !== fopts) { fs.innerHTML = fopts || '<option value="">—</option>'; fs.setAttribute('data-h', fopts); }
      var pre = $('#tr-log');
      var lines = (d.log && d.log.lines) || [];
      var atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
      var txt = lines.length ? lines.join('\n') : t('log_empty');
      if (pre.textContent !== txt) { pre.textContent = txt; if (T.follow || atBottom) pre.scrollTop = pre.scrollHeight; }
      // samples
      var sm = (d.samples && d.samples.samples) || [];
      $('#tr-samples-n').textContent = sm.length ? t('n_images', { n: sm.length }) : '';
      var sh = sm.length ? '<div class="gallery">' + sm.slice(0, 24).map(function (s) {
        var src = '/api/runs/' + enc(d.focus) + '/samples/' + enc(s.file) + '?v=' + Math.round(s.mtime || 0);
        return '<figure data-src="' + esc(src) + '" data-cap="' + esc(s.file) + '"><img loading="lazy" alt="' + esc(s.file) + '" src="' + esc(src) + '"><figcaption>' + esc(s.file) + ' · ' + esc(ago(s.mtime)) + '</figcaption></figure>';
      }).join('') + '</div>' : emptyBox('no_samples', 'no_samples_hint');
      var se = $('#tr-samples');
      if (se.getAttribute('data-h') !== sh) { se.innerHTML = sh; se.setAttribute('data-h', sh); }
    },
    drawChart: function (d) {
      var runs = d.runs || [];
      var ser = [];
      var lib = lowerIsBetter(T.metric);
      T.sel.forEach(function (id) {
        var m = d.series[id];
        if (!m || !m.series || !m.series.length) return;
        var s = m.series[0];
        var r = runs.filter(function (x) { return x.run_id === id; })[0];
        var nm = starName(runName(r), r && r.family) + (runs.filter(function (x) { return runName(x) === runName(r); }).length > 1 ? ' (' + id + ')' : '');
        var xs = s[T.xaxis];
        if (!xs || xs.every(function (v) { return v === null; })) xs = s[T.xaxis === 'step' ? 'epoch' : 'step'];
        if (!xs || xs.every(function (v) { return v === null; })) xs = s.value.map(function (_, i) { return i; });
        var pts = xs.map(function (x, i) { return [x === null ? i : x, s.value[i]]; }).filter(function (p) { return isNum(p[1]) && (!T.logy || p[1] > 0); });
        if (!pts.length) return;
        var col = colorFor('run:' + id);
        var bi_ = 0;
        pts.forEach(function (p, i) { if (lib ? p[1] < pts[bi_][1] : p[1] > pts[bi_][1]) bi_ = i; });
        var mark = { symbol: 'pin', symbolSize: 38, data: [{ coord: pts[bi_], value: fmt(pts[bi_][1], 4) }], label: { color: '#04080f', fontSize: 9 }, itemStyle: { color: col } };
        if (T.smooth > 0 && pts.length > 2) {
          var sm = ema(pts.map(function (p) { return p[1]; }), T.smooth);
          ser.push({ name: nm, type: 'line', showSymbol: false, data: pts, color: col, lineStyle: { width: 1, opacity: 0.25 }, silent: true, markPoint: mark, z: 1 });
          ser.push({ name: nm, type: 'line', showSymbol: false, data: pts.map(function (p, i) { return [p[0], sm[i]]; }), color: col, lineStyle: { width: 2 }, z: 2 });
        } else {
          ser.push({ name: nm, type: 'line', showSymbol: pts.length < 60, symbolSize: 4, data: pts, color: col, lineStyle: { width: 1.8 }, markPoint: mark });
        }
      });
      var hint = !T.sel.length ? emptyBox('tr_select_runs', null) : emptyBox('tr_no_series', 'tr_no_series_hint', { m: esc(T.metric || '—'), s: esc(tk('split_', T.split)) });
      var c = chartOrEmpty('tr-chart', ser.length > 0, hint);
      if (!c) return;
      c.setOption({
        backgroundColor: 'transparent', animation: false,
        grid: { left: 60, right: 28, top: 58, bottom: 60 },
        legend: Object.assign({}, LEG),
        tooltip: Object.assign({ trigger: 'axis', valueFormatter: function (v) { return fmt(v, 4); } }, TT),
        xAxis: ax({ type: 'value', name: T.xaxis === 'step' ? t('tr_step') : t('tr_epoch'), nameLocation: 'middle', nameGap: 26, scale: true }),
        yAxis: ax({ type: T.logy ? 'log' : 'value', name: T.metric + ' (' + tk('split_', T.split) + ')', scale: true }),
        dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 8, borderColor: '#24466e', textStyle: { color: CC.muted }, fillerColor: 'rgba(34,211,238,0.12)', moveHandleSize: 5, moveHandleStyle: { color: '#24466e' }, handleStyle: { color: '#22d3ee', borderColor: '#0a1222' }, brushSelect: false }],
        series: ser
      }, true);
    }
  };

  // ------------------------------------------------------------------ Results
  var R = { ds: LS.get('an_rs_ds', ''), metric: LS.get('an_rs_metric', ''), volm: LS.get('an_rs_volm', ''),
    stat: LS.get('an_rs_stat', 'mean') === 'median' ? 'median' : 'mean', primary: LS.get('an_rs_primary', true) !== false, fam: LS.get('an_rs_fam', { ours: true, ablation: true, baseline: true }) };
  if (!R.fam || typeof R.fam !== 'object') R.fam = { ours: true, ablation: true, baseline: true };
  /** the selected statistic of a result cell: median (falls back to the mean when a cell has no median) or mean */
  function statVal(c) { return !c ? null : (R.stat === 'median' && isNum(c.median)) ? c.median : (isNum(c.mean) ? c.mean : null); }
  function isOurs(m) { return !!m && (m.family === 'ours' || m.family === 'novel'); }
  function famKey(m) { return isOurs(m) ? 'ours' : (m && m.family === 'ablation') ? 'ablation' : (m && m.family === 'baseline') ? 'baseline' : 'other'; }
  /** The single SOTA rule, shared by the leaderboard, the SOTA matrix, the grouped bars and the exports:
   *  a cell is SOTA when a method of our family (ours | novel) is strictly better than EVERY baseline
   *  on that dataset x metric column, compared on the selected statistic. Best baseline / delta use the same value. */
  function sotaModel(methods, datasets, metrics, cell, hib) {
    var bases = methods.filter(function (m) { return m.family === 'baseline'; }), bb = {};
    function better(metId, a, b) { var eps = 1e-6 * Math.max(1, Math.abs(a), Math.abs(b)); return hib(metId) ? a > b + eps : a < b - eps; }
    datasets.forEach(function (ds) {
      metrics.forEach(function (mt) {
        var best = null;
        bases.forEach(function (m) {
          var v = statVal(cell[m.id + '|' + ds.id + '|' + mt.id]);
          if (isNum(v) && (!best || better(mt.id, v, best.v))) best = { id: m.id, v: v };
        });
        if (best) bb[ds.id + '|' + mt.id] = best;
      });
    });
    function bestBase(dsId, metId) { return bb[dsId + '|' + metId] || null; }
    function isSota(m, dsId, metId) {
      if (!isOurs(m)) return false;
      var b = bb[dsId + '|' + metId], v = statVal(cell[m.id + '|' + dsId + '|' + metId]);
      return !!b && isNum(v) && better(metId, v, b.v);
    }
    /** delta vs the best baseline, sign-normalised so that positive = better */
    function gain(m, dsId, metId) {
      var b = bb[dsId + '|' + metId], v = statVal(cell[m.id + '|' + dsId + '|' + metId]);
      return b && isNum(v) ? (hib(metId) ? v - b.v : b.v - v) : null;
    }
    /** SOTA columns of one dataset: n = columns where we have an ours-family value and a baseline, k = SOTA columns */
    function count(dsId) {
      var n = 0, k = 0;
      metrics.forEach(function (mt) {
        var ours = methods.filter(function (m) { return isOurs(m) && isNum(statVal(cell[m.id + '|' + dsId + '|' + mt.id])); });
        if (!ours.length || !bb[dsId + '|' + mt.id]) return;
        n++;
        if (ours.some(function (m) { return isSota(m, dsId, mt.id); })) k++;
      });
      return { n: n, k: k };
    }
    return { val: statVal, bestBase: bestBase, isSota: isSota, gain: gain, count: count, isOurs: isOurs,
      fallback: function (c) { return R.stat === 'median' && !!c && !isNum(c.median) && isNum(c.mean); } };
  }
  function stars(p) { return !isNum(p) ? '' : p < 0.001 ? '***' : p < 0.01 ? '**' : p < 0.05 ? '*' : 'n.s.'; }
  function quartiles(arr) {
    var a = arr.slice().sort(function (x, y) { return x - y; });
    function q(p) { var i = (a.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return a[lo] + (a[hi] - a[lo]) * (i - lo); }
    var q1 = q(0.25), q2 = q(0.5), q3 = q(0.75), iqr = q3 - q1;
    var lo = a.filter(function (v) { return v >= q1 - 1.5 * iqr; })[0], hi = a.filter(function (v) { return v <= q3 + 1.5 * iqr; }).pop();
    return { box: [lo, q1, q2, q3, hi], out: a.filter(function (v) { return v < lo || v > hi; }) };
  }
  VIEWS.results = {
    src: 'results',
    mount: function () {
      function cc(id, cls, key, extra) { return '<div class="card ' + cls + '"><h2>' + esc(t(key)) + (extra || '') + '</h2><div id="' + id + '" class="chart tall" style="display:none"></div><div id="' + id + '-empty"></div></div>'; }
      return '<div class="grid"><div class="card s12"><div class="controls" style="margin:0">' +
        '<label>' + esc(t('rs_dataset')) + ' <select id="rs-ds"></select></label><label>' + esc(t('rs_metric')) + ' <select id="rs-metric"></select></label>' +
        '<label>' + esc(t('rs_stat')) + '</label><span class="seg" id="rs-stat"><button type="button" data-v="mean">' + esc(t('rs_stat_mean')) + '</button><button type="button" data-v="median">' + esc(t('rs_stat_median')) + '</button></span>' +
        '<span class="chips" id="rs-fam">' + ['ours', 'ablation', 'baseline'].map(function (f) { return '<span class="chip clickable fam-' + f + '" data-fam="' + f + '" role="button" tabindex="0">' + esc(tk('fam_', f)) + '</span>'; }).join('') + '</span>' +
        '<span class="muted tiny fam-hint">' + esc(t('fam_legend_hint')) + '</span>' +
        '<label title="' + esc(t('rs_primary_only_tip')) + '"><input type="checkbox" id="rs-primary"> ' + esc(t('rs_primary_only')) + '</label>' +
        '<span class="chip lv-warn" id="rs-fallback" style="display:none">† ' + esc(t('rs_fallback_note')) + '</span>' +
        '<span class="grow"></span><button class="btn" type="button" id="rs-csv">' + esc(t('rs_export_csv')) + '</button><button class="btn" type="button" id="rs-md">' + esc(t('rs_copy_md')) + '</button>' +
        '<span class="muted small" id="rs-updated"></span></div></div></div>' +
        '<div class="grid"><div class="card s12"><h2>' + esc(t('rs_matrix')) + '<span class="grow"></span><span class="tag muted small">' + esc(t('rs_matrix_legend')) + '</span></h2><div id="rs-matrix" class="chart" style="display:none"></div><div id="rs-matrix-empty"></div></div></div>' +
        '<div class="grid"><div class="card s12"><h2>' + esc(t('rs_leaderboard')) + ' <span class="tag sota" id="rs-sota-total" style="display:none"></span><span class="grow"></span><span class="tag muted small"><span class="star">★</span>' + esc(t('rs_sota_legend')) + '</span><span class="tag muted small">' + esc(t('rs_sig_legend')) + '</span></h2><div id="rs-tables"></div></div></div>' +
        '<div class="grid">' + cc('rs-bar', 's7', 'rs_bars') + cc('rs-radar', 's5', 'rs_radar') + '</div>' +
        '<div class="grid">' + cc('rs-box', 's4', 'rs_box') +
        cc('rs-vol', 's4', 'rs_vol_scatter', '<span class="grow"></span><label class="tag small">' + esc(t('rs_method')) + ' <select id="rs-volm"></select></label>') +
        cc('rs-ba', 's4', 'rs_bland') + '</div>' +
        '<div class="grid"><div class="card s12" data-src="cases"><h2>' + esc(t('rs_gallery')) + '<span class="grow"></span><span class="tag muted small" id="rs-gallery-n"></span></h2>' +
        '<div class="muted tiny rs-gallery-legend">' + esc(t('rs_gallery_legend')) + '</div><div id="rs-gallery"></div></div></div>';
    },
    bind: function () {
      var self = this;
      function redraw() { rsHash(); if (self.data) self.update(self.data); }
      $('#rs-ds').addEventListener('change', function (e) { R.ds = e.target.value; LS.set('an_rs_ds', R.ds); redraw(); });
      $('#rs-metric').addEventListener('change', function (e) { R.metric = e.target.value; LS.set('an_rs_metric', R.metric); redraw(); });
      $('#rs-stat').addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { R.stat = b.getAttribute('data-v') === 'median' ? 'median' : 'mean'; LS.set('an_rs_stat', R.stat); redraw(); } });
      function famToggle(e) {
        var c = e.target.closest('[data-fam]');
        if (!c || (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ')) return;
        e.preventDefault();
        var f = c.getAttribute('data-fam');
        R.fam[f] = R.fam[f] === false;
        LS.set('an_rs_fam', R.fam); redraw();
      }
      $('#rs-fam').addEventListener('click', famToggle);
      $('#rs-fam').addEventListener('keydown', famToggle);
      $('#rs-primary').addEventListener('change', function (e) { R.primary = e.target.checked; LS.set('an_rs_primary', R.primary); redraw(); });
      $('#rs-csv').addEventListener('click', function () { self.exportCsv(); });
      $('#rs-gallery').addEventListener('error', function (e) { var f = e.target && e.target.tagName === 'IMG' && e.target.closest('figure'); if (f) { f.classList.add('broken'); f.removeAttribute('data-src'); } }, true);
      $('#rs-md').addEventListener('click', function () { self.copyMd(); });
      $('#rs-volm').addEventListener('change', function (e) { R.volm = e.target.value; LS.set('an_rs_volm', R.volm); if (self.data) self.update(self.data); });
    },
    load: function () { var self = this; return api('/api/results').then(function (d) { self.data = d; }); },
    update: function (d) {
      var s = d && d.summary, cells = (s && s.cells) || [];
      var waiting = emptyBox('rs_waiting', 'rs_waiting_hint');
      frNote('results', s && s.updated);
      frNote('cases', d && (d.cases_updated || d.cases_ts));
      this.gallery(d);
      if (!s || !cells.length) {
        $('#rs-tables').innerHTML = waiting;
        ['rs-matrix', 'rs-bar', 'rs-radar', 'rs-box', 'rs-vol', 'rs-ba'].forEach(function (id) { chartOrEmpty(id, false, emptyBox('rs_waiting', null)); });
        this.view = null;
        $('#rs-ds').innerHTML = '<option>—</option>'; $('#rs-metric').innerHTML = '<option>—</option>'; $('#rs-volm').innerHTML = '<option>—</option>';
        $('#rs-updated').textContent = '';
        return;
      }
      $('#rs-updated').textContent = s.updated ? t('updated_at', { t: fmtTime(s.updated) }) : '';
      var datasets = s.datasets.length ? s.datasets : uniq(cells.map(function (c) { return c.dataset; })).map(function (id) { return { id: id }; });
      var metrics = s.metrics.length ? s.metrics : uniq(cells.map(function (c) { return c.metric; })).map(function (id) { return { id: id, higher_is_better: !lowerIsBetter(id) }; });
      var methods = s.methods.length ? s.methods : uniq(cells.map(function (c) { return c.method; })).map(function (id) { return { id: id, name: id, family: 'baseline' }; });
      var mById = {}; methods.forEach(function (m) { mById[m.id] = m; });
      var metById = {}; metrics.forEach(function (m) { metById[m.id] = m; });
      if (!datasets.some(function (x) { return x.id === R.ds; })) R.ds = datasets[0].id;
      if (!metrics.some(function (x) { return x.id === R.metric; })) R.metric = (metrics.filter(function (x) { return /dice|dsc/i.test(x.id); })[0] || metrics[0]).id;
      setOpts('#rs-ds', datasets.map(function (x) { return [x.id, (bi(x, 'name') || x.id) + (isNum(x.n) ? ' (n=' + x.n + ')' : '')]; }), R.ds);
      setOpts('#rs-metric', metrics.map(function (x) { return [x.id, bi(x, 'name') || x.id]; }), R.metric);
      $$('#rs-stat button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === R.stat); });
      $$('#rs-fam [data-fam]').forEach(function (c) { var on = R.fam[c.getAttribute('data-fam')] !== false; c.classList.toggle('off', !on); c.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      $('#rs-primary').checked = R.primary;
      var cell = {};
      cells.forEach(function (c) { cell[c.method + '|' + c.dataset + '|' + c.metric] = c; });
      function hib(mid) { var m = metById[mid]; return m && m.higher_is_better !== undefined ? !!m.higher_is_better : !lowerIsBetter(mid); }
      function pval(a, b, ds, met) {
        var p = (s.pvalues || []).filter(function (x) { return x.dataset === ds && x.metric === met && ((x.method_a === a && x.method_b === b) || (x.method_a === b && x.method_b === a)); })[0];
        return p ? p.p : null;
      }
      function mname(id) { return (mById[id] && mById[id].name) || id; }
      function fmtP(p) { return p < 0.001 ? '< 0.001' : fmt(p, 3); }
      // one SOTA model (shared by the leaderboard, the SOTA matrix, the bars and the exports)
      var M = sotaModel(methods, datasets, metrics, cell, hib);
      function sotaTip(m, ds, mt) {
        var bb = M.bestBase(ds.id, mt.id), c = cell[m.id + '|' + ds.id + '|' + mt.id], p = pval(m.id, bb.id, ds.id, mt.id);
        return t('rs_sota_tip', { m: m.name || m.id, ds: bi(ds, 'name') || ds.id, met: bi(mt, 'name') || mt.id, b: mname(bb.id), bv: fmt(bb.v, 4),
          d: fmtSigned(M.val(c) - bb.v, 4), p: isNum(p) ? t(p < 0.05 ? 'rs_sota_p' : 'rs_sota_ns', { p: fmtP(p) }) : '' });
      }
      function statTxt(c) {
        if (R.stat === 'median' && isNum(c.median)) return fmt(c.median, 4) + (isNum(c.q1) && isNum(c.q3) ? ' <span class="dim">[' + fmt(c.q1, 3) + ', ' + fmt(c.q3, 3) + ']</span>' : '');
        return fmt(c.mean, 4) + (isNum(c.std) ? ' <span class="dim">± ' + fmt(c.std, 3) + '</span>' : '');
      }
      // displayed subsets (filters only hide rows/datasets; best baseline + SOTA always use every method)
      var dsShown = datasets.filter(function (ds) { return !R.primary || !ds.postprocess || ds.postprocess === 'none'; });
      if (!dsShown.length) dsShown = datasets;
      var mShown = methods.filter(function (m) { var f = famKey(m); return R.fam[f] !== false; });
      this.view = { datasets: dsShown, methods: mShown, metrics: metrics, cell: cell, M: M, hib: hib, pval: pval, mname: mname, s: s };
      $('#rs-fallback').style.display = R.stat === 'median' && cells.some(function (c) { return !isNum(c.median) && isNum(c.mean); }) ? '' : 'none';
      var totN = 0, totK = 0;
      // (a) leaderboards
      var selMet = metById[R.metric] || { id: R.metric };
      $('#rs-tables').innerHTML = dsShown.map(function (ds) {
        var rows = mShown.filter(function (m) { return metrics.some(function (mt) { return cell[m.id + '|' + ds.id + '|' + mt.id]; }); });
        var sc = M.count(ds.id);
        totN += sc.n; totK += sc.k;
        if (!rows.length) return '';
        var best = {};
        metrics.forEach(function (mt) {
          var vals = rows.map(function (m) { return M.val(cell[m.id + '|' + ds.id + '|' + mt.id]); }).filter(isNum);
          if (vals.length) best[mt.id] = hib(mt.id) ? Math.max.apply(null, vals) : Math.min.apply(null, vals);
        });
        var bb = M.bestBase(ds.id, R.metric);
        var head = '<tr><th>' + esc(t('rs_method')) + '</th>' + metrics.map(function (mt) { return '<th class="right">' + esc(bi(mt, 'name') || mt.id) + (mt.unit ? ' <span class="dim">(' + esc(mt.unit) + ')</span>' : '') + ' ' + (hib(mt.id) ? '↑' : '↓') + '</th>'; }).join('') +
          '<th class="right">' + esc(t('rs_delta', { m: bi(selMet, 'name') || selMet.id })) + '</th></tr>';
        var body = rows.map(function (m) {
          var tds = metrics.map(function (mt) {
            var c = cell[m.id + '|' + ds.id + '|' + mt.id], v = M.val(c);
            if (!isNum(v)) return '<td class="num dim">—</td>';
            var isBest = best[mt.id] !== undefined && v === best[mt.id];
            var sota = M.isSota(m, ds.id, mt.id), fb = M.fallback(c);
            var tip = (sota ? sotaTip(m, ds, mt) : '') + (fb ? (sota ? '\n' : '') + t('rs_fallback_tip') : '');
            return '<td class="num' + (isBest ? ' best' : '') + (sota ? ' sota' : '') + '"' + (tip ? ' title="' + esc(tip) + '"' : '') + '>' + (sota ? '<span class="star" role="img" aria-label="SOTA">★</span>' : '') + (isBest ? '<b>' : '') + statTxt(c) + (isBest ? '</b>' : '') + (fb ? '<sup class="dim">†</sup>' : '') +
              (R.stat === 'mean' && isNum(c.ci_low) && isNum(c.ci_high) ? '<div class="tiny dim">[' + fmt(c.ci_low, 3) + ', ' + fmt(c.ci_high, 3) + ']</div>' : '') + '</td>';
          }).join('');
          var c = cell[m.id + '|' + ds.id + '|' + R.metric], dl = '<td class="num dim">—</td>';
          if (bb && isNum(M.val(c))) {
            if (m.id === bb.id) dl = '<td class="num dim">' + esc(t('rs_ref')) + '</td>';
            else {
              var dv = M.val(c) - bb.v, good = hib(R.metric) ? dv > 0 : dv < 0;
              var st = stars(pval(m.id, bb.id, ds.id, R.metric));
              dl = '<td class="num ' + (good ? 'pos' : dv === 0 ? '' : 'neg') + '">' + fmtSigned(dv, 4) + (st ? ' <sup>' + esc(st) + '</sup>' : '') + '</td>';
            }
          }
          var ours = isOurs(m);
          return '<tr class="' + (m.is_primary ? 'primary' : '') + (ours ? ' ours-row' : '') + '"><td>' + (ours ? famChip(m.family) + ' ' : '') + '<span class="nowrap' + (ours ? ' ours-name' : '') + '">' + esc(m.name || m.id) + '</span>' + (ours ? '' : ' ' + famChip(m.family)) + (m.is_primary ? ' <span class="chip st-running">' + esc(t('primary')) + '</span>' : '') + '</td>' + tds + dl + '</tr>';
        }).join('');
        return '<div style="margin-bottom:1rem"><div class="card-h"><span style="color:var(--text)">' + esc(bi(ds, 'name') || ds.id) + '</span>' + (isNum(ds.n) ? '<span class="tag dim">n = ' + ds.n + '</span>' : '') + (bb ? '<span class="tag dim">' + esc(t('rs_best_baseline')) + ': ' + esc(mname(bb.id)) + '</span>' : '') + (sc.n ? '<span class="tag sota' + (sc.k ? '' : ' off') + '" title="' + esc(t('rs_sota_count_title')) + '">' + esc(t('rs_sota_count', { k: sc.k, n: sc.n })) + '</span>' : '') + '</div>' +
          '<div class="tbl-wrap"><table class="tbl sticky1"><thead>' + head + '</thead><tbody>' + body + '</tbody></table></div></div>';
      }).join('') || waiting;
      var tot = $('#rs-sota-total');
      if (tot) { tot.style.display = totN ? '' : 'none'; tot.className = 'tag sota' + (totK ? '' : ' off'); tot.title = t('rs_sota_count_title'); tot.textContent = t('rs_sota_count', { k: totK, n: totN }); }
      this.matrix();

      // (b) grouped bars with CI (mean) or IQR (median)
      var dsNames = dsShown.map(function (x) { return bi(x, 'name') || x.id; });
      var mWith = mShown.filter(function (m) { return dsShown.some(function (ds) { return cell[m.id + '|' + ds.id + '|' + R.metric]; }); });
      var bc = chartOrEmpty('rs-bar', mWith.length > 0, emptyBox('rs_no_metric', null));
      if (bc) {
        var N = mWith.length, ser = [];
        mWith.forEach(function (m, si) {
          var col = methodColor(m.id, isOurs(m));
          var vals = dsShown.map(function (ds) { var v = M.val(cell[m.id + '|' + ds.id + '|' + R.metric]); return isNum(v) ? v : null; });
          var sn = isOurs(m) ? '★ ' + (m.name || m.id) : (m.name || m.id);
          ser.push({ name: sn, type: 'bar', data: vals, color: col, barGap: '10%', barCategoryGap: '28%', itemStyle: { borderColor: isOurs(m) ? '#fff7d6' : col, borderWidth: isOurs(m) ? 1.5 : 0 } });
          var errs = dsShown.map(function (ds, di) {
            var c = cell[m.id + '|' + ds.id + '|' + R.metric], v = M.val(c);
            if (!isNum(v)) return [di, null, null, 0, null];
            var lo, hi;
            if (R.stat === 'median' && isNum(c.median) && isNum(c.q1) && isNum(c.q3)) { lo = c.q1; hi = c.q3; } else {
              lo = isNum(c.ci_low) ? c.ci_low : (isNum(c.std) ? c.mean - c.std : null); hi = isNum(c.ci_high) ? c.ci_high : (isNum(c.std) ? c.mean + c.std : null);
            }
            return [di, lo, hi, M.isSota(m, ds.id, R.metric) ? 1 : 0, v];
          });
          ser.push({ name: sn, type: 'custom', data: errs, z: 10, silent: true, tooltip: { show: false },
            renderItem: (function (si_) {
              return function (params, a) {
                var hasErr = isNum(a.value(1)) && isNum(a.value(2)), sota = a.value(3) === 1;
                if (!hasErr && !sota) return null;
                var band = a.size([1, 0])[0], gw = band * (1 - 0.28), w = gw / (N + (N - 1) * 0.1);
                var x0 = a.coord([a.value(0), 0])[0] - gw / 2 + si_ * w * 1.1 + w / 2;
                var cap = Math.min(6, w / 3), st = { stroke: '#d7e3f4', lineWidth: 1.2 }, kids = [];
                if (hasErr) {
                  var lo = a.coord([a.value(0), a.value(1)])[1], hi = a.coord([a.value(0), a.value(2)])[1];
                  kids.push({ type: 'line', shape: { x1: x0, y1: lo, x2: x0, y2: hi }, style: st },
                    { type: 'line', shape: { x1: x0 - cap, y1: lo, x2: x0 + cap, y2: lo }, style: st },
                    { type: 'line', shape: { x1: x0 - cap, y1: hi, x2: x0 + cap, y2: hi }, style: st });
                }
                if (sota) {
                  var topV = hasErr ? Math.max(a.value(2), a.value(4)) : a.value(4), ty = a.coord([a.value(0), topV])[1];
                  kids.push({ type: 'text', style: { text: '★', x: x0, y: ty - 3, fill: '#ff4d4f', font: 'bold 15px sans-serif', textAlign: 'center', textVerticalAlign: 'bottom' } });
                }
                return { type: 'group', children: kids };
              };
            })(si) });
        });
        bc.setOption({
          backgroundColor: 'transparent', animation: false, legend: Object.assign({ data: mWith.map(function (m) { return isOurs(m) ? '★ ' + (m.name || m.id) : (m.name || m.id); }) }, LEG),
          grid: { left: 56, right: 16, top: 58, bottom: 34 }, tooltip: Object.assign({ trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: function (v) { return fmt(v, 4); } }, TT),
          xAxis: ax({ type: 'category', data: dsNames }), yAxis: ax({ type: 'value', scale: true, name: bi(selMet, 'name') || R.metric }), series: ser
        }, true);
      }
      // (c) radar
      var mets = metrics.filter(function (mt) { return methods.some(function (m) { var c = cell[m.id + '|' + R.ds + '|' + mt.id]; return c && isNum(c.mean); }); });
      var rmeth = methods.filter(function (m) { return mets.some(function (mt) { return cell[m.id + '|' + R.ds + '|' + mt.id]; }); });
      var rc = chartOrEmpty('rs-radar', mets.length >= 3 && rmeth.length > 0, emptyBox('rs_radar_need', null));
      if (rc) {
        var rng = {};
        mets.forEach(function (mt) {
          var v = rmeth.map(function (m) { var c = cell[m.id + '|' + R.ds + '|' + mt.id]; return c && isNum(c.mean) ? c.mean : null; }).filter(isNum);
          rng[mt.id] = [Math.min.apply(null, v), Math.max.apply(null, v)];
        });
        function norm(mt, v) { var r = rng[mt.id]; if (!isNum(v)) return 0; var x = r[1] === r[0] ? 1 : (v - r[0]) / (r[1] - r[0]); if (!hib(mt.id)) x = 1 - x; return 0.15 + 0.85 * x; }
        rc.setOption({
          backgroundColor: 'transparent', animation: false, legend: Object.assign({}, LEG),
          tooltip: Object.assign({ formatter: function (p) {
            var m = rmeth[p.dataIndex];
            return '<b>' + esc(m.name || m.id) + '</b><br>' + mets.map(function (mt) { var c = cell[m.id + '|' + R.ds + '|' + mt.id]; return esc(bi(mt, 'name') || mt.id) + ': ' + fmt(c && c.mean, 4); }).join('<br>');
          } }, TT),
          radar: { indicator: mets.map(function (mt) { return { name: (bi(mt, 'name') || mt.id) + (hib(mt.id) ? ' ↑' : ' ↓'), max: 1, min: 0 }; }), center: ['50%', '56%'], radius: '64%',
            axisName: { color: CC.muted }, splitLine: { lineStyle: { color: CC.grid } }, splitArea: { areaStyle: { color: ['rgba(34,211,238,0.02)', 'transparent'] } }, axisLine: { lineStyle: { color: CC.axis } } },
          series: [{ type: 'radar', data: rmeth.map(function (m) {
            var col = methodColor(m.id, isOurs(m));
            return { name: isOurs(m) ? '★ ' + (m.name || m.id) : (m.name || m.id), value: mets.map(function (mt) { var c = cell[m.id + '|' + R.ds + '|' + mt.id]; return norm(mt, c && c.mean); }), lineStyle: { color: col, width: m.is_primary ? 2.5 : 1.4 }, itemStyle: { color: col }, areaStyle: { color: col, opacity: m.is_primary ? 0.18 : 0.04 }, symbolSize: 4 };
          }) }]
        }, true);
      }
      // (d) box plot of per-case values
      var pc = (s.per_case || []).filter(function (r) { return r.dataset === R.ds && r.metric === R.metric && isNum(r.value); });
      var byM = {};
      pc.forEach(function (r) { (byM[r.method] = byM[r.method] || []).push(r.value); });
      var bms = methods.filter(function (m) { return byM[m.id] && byM[m.id].length; }).map(function (m) { return m.id; });
      Object.keys(byM).forEach(function (k) { if (bms.indexOf(k) < 0 && k !== 'ground_truth') bms.push(k); });
      var xc = chartOrEmpty('rs-box', bms.length > 0, emptyBox('rs_no_percase', 'rs_no_percase_hint'));
      if (xc) {
        var qs = bms.map(function (id) { return quartiles(byM[id]); });
        var outs = [];
        qs.forEach(function (q, i) { q.out.forEach(function (v) { outs.push([i, v]); }); });
        xc.setOption({
          backgroundColor: 'transparent', animation: false, grid: { left: 56, right: 16, top: 34, bottom: 60 },
          tooltip: Object.assign({ trigger: 'item' }, TT),
          xAxis: ax({ type: 'category', data: bms.map(function (id) { return isOurs(mById[id]) ? '★ ' + mname(id) : mname(id); }), axisLabel: { color: CC.muted, rotate: bms.length > 4 ? 30 : 0, interval: 0, formatter: function (v) { return clip(v, bms.length > 4 ? 20 : 28); } } }),
          yAxis: ax({ type: 'value', scale: true, name: bi(selMet, 'name') || R.metric }),
          series: [
            { type: 'boxplot', data: qs.map(function (q, i) { var col = methodColor(bms[i], isOurs(mById[bms[i]])); return { value: q.box, itemStyle: { color: col + '33', borderColor: col } }; }),
              tooltip: { formatter: function (p) { var v = p.value; return esc(p.name) + '<br>max ' + fmt(v[5], 4) + '<br>Q3 ' + fmt(v[4], 4) + '<br>median ' + fmt(v[3], 4) + '<br>Q1 ' + fmt(v[2], 4) + '<br>min ' + fmt(v[1], 4) + '<br>n = ' + byM[bms[p.dataIndex]].length; } } },
            { type: 'scatter', data: outs, symbolSize: 5, itemStyle: { color: '#f87171', opacity: 0.7 } }
          ]
        }, true);
      }
      // (e) volume agreement + Bland-Altman
      var vol = (s.per_case || []).filter(function (r) { return r.metric === 'volume_ml' && r.dataset === R.ds && isNum(r.value); });
      var gt = {};
      vol.forEach(function (r) { if (r.method === 'ground_truth') gt[r.case_id] = r.value; });
      var vms = uniq(vol.filter(function (r) { return r.method !== 'ground_truth'; }).map(function (r) { return r.method; }));
      var hasVol = Object.keys(gt).length > 0 && vms.length > 0;
      if (hasVol && vms.indexOf(R.volm) < 0) { var prim = methods.filter(function (m) { return m.is_primary && vms.indexOf(m.id) >= 0; })[0]; R.volm = prim ? prim.id : vms[0]; }
      setOpts('#rs-volm', hasVol ? vms.map(function (id) { return [id, mname(id)]; }) : [['', '—']], R.volm);
      var pairs = hasVol ? vol.filter(function (r) { return r.method === R.volm && isNum(gt[r.case_id]); }).map(function (r) { return [gt[r.case_id], r.value, r.case_id]; }) : [];
      var vc = chartOrEmpty('rs-vol', pairs.length > 0, emptyBox('rs_no_volume', 'rs_no_volume_hint'));
      var ba = chartOrEmpty('rs-ba', pairs.length > 0, emptyBox('rs_no_volume', 'rs_no_volume_hint'));
      if (vc && ba) {
        var mx = Math.max.apply(null, pairs.map(function (p) { return Math.max(p[0], p[1]); })) * 1.05;
        var mag = Math.pow(10, Math.floor(Math.log10(mx || 1)));
        mx = Math.ceil(mx / mag * 2) * mag / 2;
        var n = pairs.length, mxs = 0, mys = 0;
        pairs.forEach(function (p) { mxs += p[0]; mys += p[1]; });
        mxs /= n; mys /= n;
        var sxy = 0, sxx = 0, syy = 0;
        pairs.forEach(function (p) { sxy += (p[0] - mxs) * (p[1] - mys); sxx += (p[0] - mxs) * (p[0] - mxs); syy += (p[1] - mys) * (p[1] - mys); });
        var rr = sxx && syy ? sxy / Math.sqrt(sxx * syy) : null;
        var col = methodColor(R.volm, isOurs(mById[R.volm]));
        vc.setOption({
          backgroundColor: 'transparent', animation: false, grid: { left: 62, right: 18, top: 30, bottom: 44 },
          title: { text: 'r = ' + fmt(rr, 3) + '   n = ' + n, right: 10, top: 0, textStyle: { color: CC.muted, fontSize: 12, fontWeight: 'normal' } },
          tooltip: Object.assign({ formatter: function (p) { return p.seriesType === 'scatter' ? esc(p.data[2]) + '<br>GT ' + fmt(p.data[0], 2) + ' ml<br>' + esc(mname(R.volm)) + ' ' + fmt(p.data[1], 2) + ' ml' : ''; } }, TT),
          xAxis: ax({ type: 'value', name: t('rs_gt_vol'), nameLocation: 'middle', nameGap: 26, min: 0, max: mx }), yAxis: ax({ type: 'value', name: t('rs_pred_vol'), nameLocation: 'middle', nameGap: 40, min: 0, max: mx }),
          series: [{ type: 'line', data: [[0, 0], [mx, mx]], showSymbol: false, silent: true, lineStyle: { color: '#50627e', type: 'dashed' } },
            { type: 'scatter', data: pairs, symbolSize: 6, itemStyle: { color: col, opacity: 0.75 } }]
        }, true);
        var bpts = pairs.map(function (p) { return [(p[0] + p[1]) / 2, p[1] - p[0], p[2]]; });
        var md_ = bpts.reduce(function (a, p) { return a + p[1]; }, 0) / n;
        var sd = Math.sqrt(bpts.reduce(function (a, p) { return a + (p[1] - md_) * (p[1] - md_); }, 0) / Math.max(1, n - 1));
        function ml(v, lbl, c2) { return { yAxis: v, lineStyle: { color: c2, type: 'dashed' }, label: { formatter: lbl + ' ' + fmt(v, 2), color: c2, position: 'insideEndTop' } }; }
        ba.setOption({
          backgroundColor: 'transparent', animation: false, grid: { left: 62, right: 18, top: 30, bottom: 44 },
          tooltip: Object.assign({ formatter: function (p) { return p.seriesType === 'scatter' ? esc(p.data[2]) + '<br>' + t('rs_mean_vol') + ' ' + fmt(p.data[0], 2) + '<br>Δ ' + fmt(p.data[1], 2) : ''; } }, TT),
          xAxis: ax({ type: 'value', name: t('rs_mean_vol'), nameLocation: 'middle', nameGap: 26, scale: true }), yAxis: ax({ type: 'value', name: t('rs_diff_vol'), nameLocation: 'middle', nameGap: 40, scale: true }),
          series: [{ type: 'scatter', data: bpts, symbolSize: 6, itemStyle: { color: col, opacity: 0.75 },
            markLine: { symbol: 'none', silent: true, data: [ml(md_, t('rs_bias'), CC.amber), ml(md_ + 1.96 * sd, '+1.96 SD', '#8296b3'), ml(md_ - 1.96 * sd, '−1.96 SD', '#8296b3')] } }]
        }, true);
      }
    },
    matrix: function () {
      var v = this.view;
      if (!v) return;
      var M = v.M, cell = v.cell, hib = v.hib, ord = { ours: 0, ablation: 1, baseline: 2, other: 3 };
      var rows = v.methods.map(function (m, i) { return [m, i]; }).sort(function (a, b) { return (ord[famKey(a[0])] - ord[famKey(b[0])]) || (a[1] - b[1]); }).map(function (x) { return x[0]; });
      var dsLbl = rsShortLabels(v.datasets), cols = [];
      v.datasets.forEach(function (ds, di) {
        v.metrics.forEach(function (mt) {
          if (rows.some(function (m) { return isNum(M.val(cell[m.id + '|' + ds.id + '|' + mt.id])); })) cols.push({ ds: ds, mt: mt, di: di, lbl: dsLbl[ds.id] });
        });
      });
      rows = rows.filter(function (m) { return cols.some(function (c) { return isNum(M.val(cell[m.id + '|' + c.ds.id + '|' + c.mt.id])); }); });
      var ch = chartOrEmpty('rs-matrix', cols.length > 0 && rows.length > 0, emptyBox('rs_waiting', null), Math.max(200, rows.length * 34 + (cols.length > 14 ? 150 : 120)));
      if (!ch) return;
      var data = [];
      cols.forEach(function (c, ci) {
        var vals = rows.map(function (m) { return M.val(cell[m.id + '|' + c.ds.id + '|' + c.mt.id]); });
        var gains = rows.map(function (m) { return M.gain(m, c.ds.id, c.mt.id); });
        var mx = Math.max.apply(null, [0].concat(gains.filter(isNum).map(Math.abs)));
        rows.forEach(function (m, ri) {
          var x = vals[ri];
          if (!isNum(x)) return;
          var rank = 1 + vals.filter(function (y) { return isNum(y) && (hib(c.mt.id) ? y > x : y < x); }).length;
          var dn = isNum(gains[ri]) && mx > 0 ? gains[ri] / mx : 0;
          data.push({ value: [ci, ri, dn], rank: rank, sota: M.isSota(m, c.ds.id, c.mt.id), label: { color: Math.abs(dn) > 0.6 ? '#04080f' : '#d7e3f4' } });
        });
      });
      var cw = ch.getWidth(), narrow = cw < 600, nmax = narrow ? 16 : cw < 900 ? 24 : 34, vis = narrow ? 4 : 14;
      var many = cols.length > vis;
      var dz = many ? keepZoom(ch, [{ type: 'slider', xAxisIndex: 0, startValue: 0, endValue: vis - 1, height: 14, bottom: 4, borderColor: '#24466e', textStyle: { color: CC.muted }, fillerColor: 'rgba(34,211,238,0.12)', moveHandleSize: 5, moveHandleStyle: { color: '#24466e' }, handleStyle: { color: '#22d3ee', borderColor: '#0a1222' }, brushSelect: false, labelFormatter: '' },
        { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true }]) : [];
      function plain(c) {
        if (R.stat === 'median' && isNum(c.median)) return fmt(c.median, 4) + (isNum(c.q1) && isNum(c.q3) ? ' [' + fmt(c.q1, 3) + ', ' + fmt(c.q3, 3) + ']' : '');
        return fmt(c.mean, 4) + (isNum(c.std) ? ' ± ' + fmt(c.std, 3) : '');
      }
      ch.setOption({
        backgroundColor: 'transparent', animation: false,
        grid: { left: 8, right: 16, top: 34, bottom: many ? 30 : 8, containLabel: true },
        tooltip: Object.assign({ formatter: function (p) {
          var d = p.data, c0 = cols[d.value[0]], m = rows[d.value[1]], c = cell[m.id + '|' + c0.ds.id + '|' + c0.mt.id], bb = M.bestBase(c0.ds.id, c0.mt.id);
          var pv = bb && bb.id !== m.id ? v.pval(m.id, bb.id, c0.ds.id, c0.mt.id) : null;
          return '<b>' + esc(m.name || m.id) + '</b> · ' + esc(tk('fam_', m.family)) + (d.sota ? ' <span style="color:#ff4d4f">★ SOTA</span>' : '') +
            '<br>' + esc(bi(c0.ds, 'name') || c0.ds.id) + '<br>' + esc(bi(c0.mt, 'name') || c0.mt.id) + ' ' + (hib(c0.mt.id) ? '↑' : '↓') + ': <b>' + esc(plain(c)) + '</b>' + (M.fallback(c) ? ' †' : '') +
            '<br>' + esc(t('rs_best_baseline')) + ': ' + (bb ? esc(v.mname(bb.id)) + ' ' + esc(fmt(bb.v, 4)) : '—') +
            (bb && bb.id !== m.id ? '<br>Δ ' + esc(fmtSigned(M.val(c) - bb.v, 4)) + (isNum(pv) ? ' · p = ' + esc(pv < 0.001 ? '< 0.001' : fmt(pv, 3)) + ' ' + esc(stars(pv)) : '') : '') +
            '<br>' + esc(t('rs_rank', { r: d.rank, n: rows.length })) + (M.fallback(c) ? '<br>† ' + esc(t('rs_fallback_tip')) : '');
        } }, TT),
        xAxis: { type: 'category', data: cols.map(function (c, i) { return i; }), position: 'top', splitArea: { show: false }, axisTick: { show: false }, axisLine: { show: false },
          axisLabel: { interval: 0, width: narrow ? 40 : 84, overflow: 'truncate', lineHeight: 13, fontSize: 10, color: CC.muted,
            formatter: function (i) { var c = cols[i]; return c ? '{d' + (c.di % 2) + '|' + c.lbl + '}\n{m|' + (bi(c.mt, 'name') || c.mt.id) + (hib(c.mt.id) ? ' ↑' : ' ↓') + '}' : ''; },
            rich: { d0: { color: CC.cyan, fontSize: 10 }, d1: { color: CC.amber, fontSize: 10 }, m: { color: CC.text, fontSize: 10 } } } },
        yAxis: { type: 'category', inverse: true, data: rows.map(function (m) { return m.id; }), axisTick: { show: false }, axisLine: { show: false },
          axisLabel: { color: CC.text, fontSize: 11, formatter: function (id) {
            var m = rows.filter(function (x) { return x.id === id; })[0], nm = clip((m && m.name) || id, nmax).replace(/[{}|]/g, ' '), f = famKey(m);
            return f === 'ours' ? '{o|★ ' + nm + '}' : f === 'ablation' ? '{a|' + nm + '}' : nm;
          }, rich: { o: { color: '#fde68a', fontWeight: 'bold', fontSize: 11 }, a: { color: '#a78bfa', fontSize: 11 } } } },
        visualMap: { type: 'continuous', min: -1, max: 1, dimension: 2, calculable: false, orient: 'horizontal', right: 8, top: 0, itemWidth: 10, itemHeight: 140,
          text: [t('rs_mx_better'), t('rs_mx_worse')], textStyle: { color: CC.muted, fontSize: 11 }, inRange: { color: ['#f97316', '#8a3a12', '#182234', '#0f4c75', '#38bdf8'] } },
        dataZoom: dz,
        series: [{ type: 'heatmap', data: data, itemStyle: { borderColor: '#04080f', borderWidth: 1 }, emphasis: { itemStyle: { borderColor: CC.cyan, borderWidth: 1.5 } },
          label: { show: true, fontSize: 11, fontFamily: 'monospace', formatter: function (p) { return p.data.sota ? '{s|★}' + p.data.rank : String(p.data.rank); },
            rich: { s: { color: '#ff4d4f', fontWeight: 'bold', fontSize: 12, textBorderColor: '#04080f', textBorderWidth: 2 } } } }]
      }, true);
    },
    /** rows for the exports: every displayed dataset x method x metric */
    exportRows: function () {
      var v = this.view, out = [];
      if (!v) return out;
      v.datasets.forEach(function (ds) {
        v.methods.forEach(function (m) {
          v.metrics.forEach(function (mt) {
            var c = v.cell[m.id + '|' + ds.id + '|' + mt.id], x = v.M.val(c);
            if (!isNum(x)) return;
            var bb = v.M.bestBase(ds.id, mt.id), p = bb && bb.id !== m.id ? v.pval(m.id, bb.id, ds.id, mt.id) : null;
            out.push({ ds: ds, m: m, mt: mt, c: c, v: x, bb: bb, d: bb ? x - bb.v : null, p: p, sota: v.M.isSota(m, ds.id, mt.id), fb: v.M.fallback(c) });
          });
        });
      });
      return out;
    },
    exportCsv: function () {
      var rows = this.exportRows();
      if (!rows.length) { toast(t('rs_export_none')); return; }
      function q(x) { var s2 = x === null || x === undefined ? '' : String(x); return /[",\n\r]/.test(s2) ? '"' + s2.replace(/"/g, '""') + '"' : s2; }
      function n(x) { return isNum(x) ? String(x) : ''; }
      var head = ['dataset', 'dataset_name', 'method', 'method_name', 'family', 'metric', 'higher_is_better', 'statistic', 'value', 'std', 'ci_low', 'ci_high', 'median', 'q1', 'q3', 'n',
        'best_baseline', 'best_baseline_value', 'delta_vs_best_baseline', 'p_vs_best_baseline', 'sota', 'median_missing_used_mean'];
      var hibF = this.view.hib;
      var lines = [head.join(',')].concat(rows.map(function (r) {
        var c = r.c;
        return [r.ds.id, bi(r.ds, 'name'), r.m.id, r.m.name || r.m.id, r.m.family, r.mt.id, hibF(r.mt.id) ? 1 : 0, R.stat, n(r.v), n(c.std), n(c.ci_low), n(c.ci_high), n(c.median), n(c.q1), n(c.q3), n(c.n),
          r.bb ? r.bb.id : '', r.bb ? n(r.bb.v) : '', n(r.d), n(r.p), r.sota ? 1 : 0, r.fb ? 1 : 0].map(q).join(',');
      }));
      var blob = new Blob(['\ufeff' + lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
      var a = document.createElement('a'), d = new Date();
      a.href = URL.createObjectURL(blob);
      a.download = 'an_results_' + R.stat + '_' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '_' + pad(d.getHours()) + pad(d.getMinutes()) + '.csv';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
      toast(t('rs_csv_done', { n: rows.length }));
    },
    copyMd: function () {
      var v = this.view;
      if (!v) { toast(t('rs_export_none')); return; }
      var rows = this.exportRows(), by = {};
      rows.forEach(function (r) { by[r.ds.id + '|' + r.m.id + '|' + r.mt.id] = r; });
      function cellTxt(r) {
        if (!r) return '—';
        var c = r.c, s2 = R.stat === 'median' && isNum(c.median) ? fmt(c.median, 4) + (isNum(c.q1) && isNum(c.q3) ? ' [' + fmt(c.q1, 3) + ', ' + fmt(c.q3, 3) + ']' : '') : fmt(c.mean, 4) + (isNum(c.std) ? ' ± ' + fmt(c.std, 3) : '');
        return (r.sota ? '★ ' : '') + s2 + (r.fb ? ' †' : '');
      }
      function pipe(x) { return String(x).replace(/\|/g, '\\|'); }
      var selMet = v.metrics.filter(function (m) { return m.id === R.metric; })[0] || { id: R.metric };
      var out = ['<!-- ' + t('rs_md_note', { s: R.stat === 'median' ? t('rs_stat_median') : t('rs_stat_mean') }) + ' -->', ''];
      v.datasets.forEach(function (ds) {
        var ms = v.methods.filter(function (m) { return v.metrics.some(function (mt) { return by[ds.id + '|' + m.id + '|' + mt.id]; }); });
        if (!ms.length) return;
        out.push('### ' + pipe(bi(ds, 'name') || ds.id) + (isNum(ds.n) ? ' (n = ' + ds.n + ')' : ''), '');
        out.push('| ' + t('rs_method') + ' | ' + v.metrics.map(function (mt) { return pipe(bi(mt, 'name') || mt.id) + (v.hib(mt.id) ? ' ↑' : ' ↓'); }).join(' | ') + ' | ' + pipe(t('rs_delta', { m: bi(selMet, 'name') || selMet.id })) + ' |');
        out.push('|---|' + v.metrics.map(function () { return '---:'; }).join('|') + '|---:|');
        ms.forEach(function (m) {
          var r = by[ds.id + '|' + m.id + '|' + R.metric], dl = '—';
          if (r && r.bb) dl = r.bb.id === m.id ? t('rs_ref') : fmtSigned(r.d, 4) + (isNum(r.p) ? ' ' + stars(r.p) : '');
          out.push('| ' + pipe(m.name || m.id) + ' (' + tk('fam_', m.family) + ') | ' + v.metrics.map(function (mt) { return pipe(cellTxt(by[ds.id + '|' + m.id + '|' + mt.id])); }).join(' | ') + ' | ' + pipe(dl) + ' |');
        });
        out.push('');
      });
      out.push('★ ' + t('rs_sota_legend') + ' · ' + t('rs_sig_legend'));
      copyText(out.join('\n'), function (ok) { toast(ok ? t('rs_md_done') : t('copy_failed')); });
    },
    /** qualitative gallery (results/cases/index.json, README §7): image, bilingual title,
     *  per-model Dice chips in the family colours (gold = ours, violet = ablation, blue = baseline), note */
    gallery: function (d) {
      var cases = ((d && d.cases) || []).filter(function (c) { return c && typeof c === 'object' && (c.image || c.file); });
      // cases of the selected dataset first, but every case stays visible (the v1 gallery is in-house val only)
      if (R.ds) cases = cases.filter(function (c) { return c.dataset === R.ds; }).concat(cases.filter(function (c) { return c.dataset !== R.ds; }));
      var fam = {}, mname = {};
      (((d && d.summary) || {}).methods || []).forEach(function (m) { if (m && m.id) { fam[m.id] = m.family; mname[m.id] = m.name || m.id; } });
      var dsName = {};
      (((d && d.summary) || {}).datasets || []).forEach(function (s) { if (s && s.id) dsName[s.id] = bi(s, 'name') || s.id; });
      function famOf(id, c) {
        var f = (c.families && c.families[id]) || fam[id];
        if (!f) f = /^B\d/i.test(id) ? 'baseline' : /^N\d/i.test(id) ? 'ablation' : /^[TV]\d/i.test(id) ? 'ours' : 'other';
        return isOursFam(f) ? 'ours' : f;
      }
      var forder = { ours: 0, ablation: 1, baseline: 2, other: 3 };
      var h = cases.length ? '<div class="gallery cases">' + cases.slice(0, 60).map(function (c) {
        var file = String(c.image || c.file), src = '/api/results/cases/' + encPath(file);
        var id = c.id || c.case_id || '';
        var title = bi(c, 'title') || bi(c, 'caption') || id || file;
        var dice = c.dice && typeof c.dice === 'object' ? Object.keys(c.dice).filter(function (k) { return isNum(c.dice[k]); }) : [];
        dice.sort(function (a, b) { return (forder[famOf(a, c)] - forder[famOf(b, c)]) || 0; });
        var best = dice.reduce(function (m, k) { return m === null || c.dice[k] > c.dice[m] ? k : m; }, null);
        var chips = dice.map(function (k) {
          var f = famOf(k, c);
          return '<span class="chip dchip fam-' + esc(f) + (k === best ? ' best' : '') + '" title="' + esc((mname[k] || k) + ' · ' + tk('fam_', f) + ' · Dice ' + fmt(c.dice[k], 4)) + '">' +
            (f === 'ours' ? '★ ' : '') + esc(shortId(k) || k) + ' <b class="mono">' + esc(fmt(c.dice[k], 3)) + '</b></span>';
        }).join('');
        var note = typeof c.note === 'string' ? c.note : (c.note && typeof c.note === 'object' ? biObj(c.note) : bi(c, 'note'));
        var cap = title + (dice.length ? ' · ' + dice.map(function (k) { return (shortId(k) || k) + ' ' + fmt(c.dice[k], 3); }).join(' · ') : '');
        return '<figure class="case-fig" data-src="' + esc(src) + '" data-cap="' + esc(cap) + '"><img loading="lazy" alt="' + esc(title) + '" src="' + esc(src) + '">' +
          '<figcaption><div class="case-ttl">' + esc(title) + '</div><div class="case-meta">' + (id ? '<span class="mono">' + esc(id) + '</span>' : '') + (c.dataset ? '<span class="tag tiny" title="' + esc(c.dataset) + '">' + esc(dsName[c.dataset] || c.dataset) + '</span>' : '') + '</div>' +
          (chips ? '<div class="case-dice">' + chips + '</div>' : '') + (note ? '<div class="case-note">' + esc(note) + '</div>' : '') + '</figcaption></figure>';
      }).join('') + '</div>' : emptyBox('rs_no_cases', 'rs_no_cases_hint');
      var el = $('#rs-gallery');
      if (el.getAttribute('data-h') !== h) { el.innerHTML = h; el.setAttribute('data-h', h); }
      var gn = $('#rs-gallery-n');
      if (gn) gn.textContent = cases.length ? t('n_cases', { n: cases.length }) : '';
    }
  };
  function uniq(a) { var o = [], s = {}; a.forEach(function (x) { if (x !== undefined && x !== null && !s[x]) { s[x] = 1; o.push(x); } }); return o; }
  function setOpts(sel, pairs, cur) {
    var el = $(sel);
    if (!el) return;
    var h = pairs.map(function (p) { return '<option value="' + esc(p[0]) + '"' + (p[0] === cur ? ' selected' : '') + '>' + esc(p[1]) + '</option>'; }).join('');
    if (el.getAttribute('data-h') !== h) { el.innerHTML = h; el.setAttribute('data-h', h); }
  }

  /** short column labels for datasets: split + (·LCC when post-processed); outputs disambiguate collisions */
  function rsShortLabels(datasets) {
    function base(ds, withOut) {
      var tok = withOut ? String(ds.output || '').split(/[_\s]+/).filter(function (x) { return x && !/^(ref|lcc)$/i.test(x); }).join('·') : '';
      return String(ds.split || ds.id) + (tok ? '·' + tok : '') + (ds.postprocess && ds.postprocess !== 'none' ? '·LCC' : '');
    }
    var out = {}, cnt = {};
    datasets.forEach(function (ds) { var b = base(ds, false); cnt[b] = (cnt[b] || 0) + 1; });
    datasets.forEach(function (ds) { var b = base(ds, false); out[ds.id] = cnt[b] > 1 ? base(ds, true) : b; });
    var seen = {};
    datasets.forEach(function (ds) { if (seen[out[ds.id]]) out[ds.id] = ds.id; seen[out[ds.id]] = 1; });
    return out;
  }
  function rsHash() {
    if (current !== 'results' || !window.history || !history.replaceState) return;
    try { history.replaceState(null, '', '#/results?ds=' + enc(R.ds) + '&metric=' + enc(R.metric) + '&stat=' + enc(R.stat)); } catch (e) { /* ignore */ }
  }
  var toastT = null;
  function toast(msg) {
    var el = $('#toast');
    if (!el) { el = document.createElement('div'); el.id = 'toast'; el.className = 'toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastT);
    toastT = setTimeout(function () { el.classList.remove('show'); }, 2000);
  }
  function copyText(txt, cb) {
    function fallback() {
      var ta = document.createElement('textarea'), ok = false;
      ta.value = txt; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.left = '-9999px';
      document.body.appendChild(ta); ta.select();
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove(); cb(ok);
    }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(txt).then(function () { cb(true); }, fallback);
    else fallback();
  }

  // ------------------------------------------------------------------ Leaderboard (live race of our models vs the best baseline)
  var LB_LIVE_METRICS = ['val_dice', 'val_hd95', 'val_dice_aux', 'val_dice_mean'];
  var LB_VERDICTS = ['sota', 'ahead', 'tie', 'behind'];
  var LB_VD_COLOR = { sota: '#ff4d4f', ahead: '#34d399', tie: '#fbbf24', behind: '#8296b3', up: '#22d3ee' };
  var LB_TOL_DEF = { dice: 0.003, hd: 0.3 }, LB_TOL_MAX = { dice: 0.05, hd: 5 };
  var LB = { scope: LS.get('an_lb_scope', 'live') === 'final' ? 'final' : 'live', metric: LS.get('an_lb_metric', 'val_dice'), fmetric: LS.get('an_lb_fmetric', 'dice'),
    ds: LS.get('an_lb_ds', 'inhouse_val'), stat: LS.get('an_lb_stat', 'mean') === 'median' ? 'median' : 'mean', tol: LS.get('an_lb_tol', null),
    only: LS.get('an_lb_only', false) === true, focus: LS.get('an_lb_focus', true) !== false, curve: LS.get('an_lb_curve', 'best') === 'raw' ? 'raw' : 'best', notify: LS.get('an_lb_notify', false) === true,
    evRun: '', seenTs: LS.get('an_lb_seen_ts', null), seenIds: LS.get('an_lb_seen_ids', []), res: null, resAt: 0, seen: {}, kinds: {}, avail: {} };
  if (!Array.isArray(LB.seenIds)) LB.seenIds = [];
  LB.seenIds.forEach(function (k) { LB.seen[String(k)] = 1; });
  if (!LB.tol || typeof LB.tol !== 'object') LB.tol = { dice: LB_TOL_DEF.dice, hd: LB_TOL_DEF.hd };
  if (typeof LB.metric !== 'string' || !LB.metric) LB.metric = 'val_dice';
  if (typeof LB.fmetric !== 'string' || !LB.fmetric) LB.fmetric = 'dice';
  if (!isNum(LB.seenTs)) LB.seenTs = null;
  function lbMetric() { return LB.scope === 'final' ? LB.fmetric : LB.metric; }
  /** tolerance family: HD/ASD-type distances (mm) vs Dice-type scores */
  function lbTolKind(m) {
    m = String(m === undefined ? lbMetric() : m);
    var k = LB.kinds[m];
    return k === 'dist' ? 'hd' : k === 'ratio' ? 'dice' : /hd|asd/i.test(m) ? 'hd' : 'dice';
  }
  function lbClampTol(v, kind) { kind = kind || lbTolKind(); return isNum(v) ? Math.max(0, Math.min(LB_TOL_MAX[kind], v)) : LB_TOL_DEF[kind]; }
  function lbTol() { var k = lbTolKind(); return lbClampTol(LB.tol[k], k); }
  function lbDg(m) { return /hd|asd|ml|vol|mm/i.test(String(m)) ? 2 : 4; }
  function lbSet(el, h) { if (el && el.getAttribute('data-h') !== h) { el.innerHTML = h; el.setAttribute('data-h', h); } }
  function lbOursRow(r) { return !!r && isOursFam(r.family); }
  function lbMetricName(m) {
    var mk = 'lb_m_' + m;
    if (has(mk)) return t(mk);
    var res = LB.res, mm = res && Array.isArray(res.metrics) ? res.metrics.filter(function (x) { return x && x.id === m; })[0] : null;
    return (mm && bi(mm, 'name')) || String(m || '—');
  }
  /** verdict chip; `prov` adds the provisional suffix (best baseline still training) */
  function lbVdChip(v, prov) {
    if (LB_VERDICTS.indexOf(v) < 0) return '<span class="dim">—</span>';
    return '<span class="chip vd vd-' + v + '"' + (prov ? ' title="' + esc(t('lb_provisional_tip')) + '"' : '') + '>' + esc(tk('vd_', v)) +
      (prov ? '<span class="vd-prov">· ' + esc(t('lb_provisional')) + '</span>' : '') + '</span>';
  }
  function lbTrend(tr) {
    if (tr !== 'up' && tr !== 'flat' && tr !== 'final') return '<span class="dim">—</span>';
    return '<span class="lb-tr lb-tr-' + tr + '">' + esc(tk('tr_trend_', tr)) + '</span>';
  }
  function lbDcls(dl, tol) { return !isNum(dl) ? 'dim' : Math.abs(dl) <= tol + 1e-12 ? 'lb-flat' : dl > 0 ? 'pos' : 'neg'; }
  /** stable family colours: ours = gold shades, ablations = violet shades, baselines = blue shades */
  var LB_ABL = ['#a78bfa', '#c4b5fd', '#8b5cf6', '#ddd6fe', '#7c3aed'], LB_BASE = ['#60a5fa', '#93c5fd', '#3b82f6', '#38bdf8', '#bfdbfe', '#2563eb'], lbIdx = { abl: {}, base: {} };
  function lbColor(r) {
    if (lbOursRow(r)) return methodColor(r.run_id, true);
    var g = r.family === 'ablation' ? 'abl' : 'base', m = lbIdx[g], pal = g === 'abl' ? LB_ABL : LB_BASE;
    if (m[r.run_id] === undefined) m[r.run_id] = Object.keys(m).length;
    return pal[m[r.run_id] % pal.length];
  }
  /** points of a run: `best` = best-so-far curve (sparkline_best) when the server sends it, else the raw validation values */
  function lbPts(r, best) {
    var p = best && Array.isArray(r.sparkline_best) && r.sparkline_best.length ? r.sparkline_best : Array.isArray(r.series) ? r.series : r.sparkline;
    return (Array.isArray(p) ? p : []).filter(function (x) { return Array.isArray(x) && isNum(x[0]) && isNum(x[1]); });
  }
  /** inline 90x22 SVG sparkline; better is always drawn upwards (HD95 is flipped); dashed line = best baseline */
  function lbSpark(r, hib, base) {
    var pts = lbPts(r);
    if (pts.length < 2) return '<span class="dim">—</span>';
    var W = 90, H = 22, P = 2, x0 = pts[0][0], x1 = pts[pts.length - 1][0], lo = Infinity, hi = -Infinity;
    pts.forEach(function (p) { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); });
    if (isNum(base)) { lo = Math.min(lo, base); hi = Math.max(hi, base); }
    if (hi - lo < 1e-12) { hi += 1e-6; lo -= 1e-6; }
    function X(x) { return (x1 > x0 ? P + (x - x0) / (x1 - x0) * (W - 2 * P) : W / 2).toFixed(1); }
    function Y(v) { var f = (v - lo) / (hi - lo); return (hib ? H - P - f * (H - 2 * P) : P + f * (H - 2 * P)).toFixed(1); }
    var col = lbColor(r), last = pts[pts.length - 1];
    return '<svg class="spark" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true">' +
      (isNum(base) ? '<line x1="0" x2="' + W + '" y1="' + Y(base) + '" y2="' + Y(base) + '" stroke="#60a5fa" stroke-width="1" stroke-dasharray="3 2" opacity=".75"/>' : '') +
      '<polyline fill="none" stroke="' + col + '" stroke-width="1.5" stroke-linejoin="round" points="' + pts.map(function (p) { return X(p[0]) + ',' + Y(p[1]); }).join(' ') + '"/>' +
      '<circle cx="' + X(last[0]) + '" cy="' + Y(last[1]) + '" r="2" fill="' + col + '"/></svg>';
  }
  function lbEvTs(e) { var d = e && toDate(e.ts); return d ? d.getTime() : null; }
  function lbEvImproved(e) { return !!e && (e.kind === 'improved' || e.type === 'improved' || e.to === 'improved'); }
  function lbEvMsg(e, names) {
    var m = lang === 'zh' ? (e.msg_zh || e.msg_en) : (e.msg_en || e.msg_zh);
    if (m) return String(m);
    var run = (names && names[e.run_id]) || e.run_id || '?';
    if (lbEvImproved(e)) return t('lb_ev_fmt_up', { run: run, e: isNum(e.epoch) ? e.epoch : '—', v: fmt(e.value, lbDg(e.metric)) });
    return t('lb_ev_fmt', { run: run, e: isNum(e.epoch) ? e.epoch : '—', from: tk('vd_', e.from), to: tk('vd_', e.to) });
  }
  function lbToasts() {
    var el = $('#lb-toasts');
    if (!el) { el = document.createElement('div'); el.id = 'lb-toasts'; el.className = 'lb-toasts'; el.setAttribute('aria-live', 'polite'); document.body.appendChild(el); }
    return el;
  }
  function lbAnnounce(e) {
    var msg = lbEvMsg(e), box = lbToasts(), d = document.createElement('div'), v = LB_VERDICTS.indexOf(e.to) >= 0 ? e.to : 'ahead';
    d.className = 'lb-toast vd-' + v;
    d.innerHTML = '<div class="lb-toast-h">' + lbVdChip(v, false) + '<span>' + esc(t('lb_notify_title')) + '</span></div><div class="lb-toast-m">' + esc(msg) + '</div>';
    box.appendChild(d);
    while (box.children.length > 3) box.removeChild(box.firstElementChild);
    setTimeout(function () { d.classList.add('out'); setTimeout(function () { d.remove(); }, 400); }, 10000);
    if (LB.notify && window.Notification && window.Notification.permission === 'granted') {
      try { new window.Notification(t('lb_notify_title'), { body: msg, tag: 'an-lb-' + String(e.ts) + '-' + String(e.run_id) }); } catch (x) { /* some browsers only allow service-worker notifications */ }
    }
  }
  /** announce NEW ahead / SOTA events (newer than the last one this browser saw, and from the last 30 min) */
  function lbEvKey(e) { return e.id ? String(e.id) : String(e.ts) + '|' + e.run_id + '|' + e.metric + '|' + e.from + '|' + e.to; }
  function lbMarkSeen(k) {
    if (LB.seen[k]) return;
    LB.seen[k] = 1; LB.seenIds.push(k);
    if (LB.seenIds.length > 200) LB.seenIds = LB.seenIds.slice(-200);
  }
  // every caller passes the full recent list (Overview: recent_events), so one newer event (an `improved` one, or a
  // val_hd95 event at the same ts) can never move seenTs past an unseen SOTA event; equal ts is handled by the ids
  function lbCheckEvents(evs) {
    evs = (evs || []).filter(function (e) { return e && typeof e === 'object' && lbEvTs(e) !== null; });
    if (!evs.length) return;
    var maxTs = Math.max.apply(null, evs.map(lbEvTs));
    if (LB.seenTs === null) {  // first visit: no backlog
      evs.forEach(function (e) { lbMarkSeen(lbEvKey(e)); });
      LB.seenTs = maxTs; LS.set('an_lb_seen_ts', maxTs); LS.set('an_lb_seen_ids', LB.seenIds); return;
    }
    var fresh = [], n0 = LB.seenIds.length;
    evs.forEach(function (e) {
      var ts = lbEvTs(e), k = lbEvKey(e);
      if (ts < LB.seenTs || LB.seen[k]) return;
      lbMarkSeen(k);
      if (Date.now() - ts > 30 * 60000 || lbEvImproved(e)) return;
      // upgrades into ahead / SOTA only (LB_VERDICTS is best-first; a missing `from` counts as behind)
      var lt = LB_VERDICTS.indexOf(e.to), lf = LB_VERDICTS.indexOf(e.from);
      if ((e.to === 'ahead' || e.to === 'sota') && lt < (lf < 0 ? LB_VERDICTS.length : lf)) fresh.push(e);
    });
    if (maxTs > LB.seenTs) { LB.seenTs = maxTs; LS.set('an_lb_seen_ts', maxTs); }
    if (LB.seenIds.length !== n0) LS.set('an_lb_seen_ids', LB.seenIds);
    fresh.sort(function (a, b) { return lbEvTs(a) - lbEvTs(b); }).slice(-3).forEach(lbAnnounce);
  }
  function lbNotifyState() {
    var el = $('#lb-notify-st');
    if (!el) return;
    var N = window.Notification, k = '';
    if (LB.notify) k = !N ? 'lb_notify_unsupported' : N.permission === 'denied' ? 'lb_notify_denied' : N.permission === 'granted' ? 'lb_notify_on' : 'lb_notify_ask';
    el.textContent = k ? t(k) : '';
    el.className = 'tag small ' + (k === 'lb_notify_on' ? 'pos' : 'muted');
  }
  function lbHash() {
    if (current !== 'leaderboard' || !window.history || !history.replaceState) return;
    var q = '#/leaderboard?scope=' + LB.scope + '&metric=' + enc(lbMetric()) + (LB.scope === 'final' ? '&ds=' + enc(LB.ds) + '&stat=' + LB.stat : '');
    try { history.replaceState(null, '', q); } catch (e) { /* ignore */ }
  }
  function lbTile(lbl, val, sub, cls, title) {
    return '<div class="card kpi ' + (cls || '') + '"' + (title ? ' title="' + esc(title) + '"' : '') + '><div class="lbl">' + esc(t(lbl)) + '</div><div class="val' + ((cls || '').indexOf('txt') >= 0 ? ' txt' : '') + '">' + val + '</div>' +
      (sub ? '<div class="subl">' + sub + '</div>' : '') + '</div>';
  }
  /** Overview "赛况 / Race" card (fed by /api/overview -> leaderboard) */
  function lbOverview(L) {
    var el = $('#ov-race'), meta = $('#ov-race-meta');
    if (!el) return;
    if (!L || typeof L !== 'object' || L.ok === false) {
      lbSet(el, '<div class="muted small">' + esc(t('lb_ov_none')) + '</div>');
      if (meta) meta.textContent = '';
      return;
    }
    var bb = L.best_baseline || {}, m = L.metric || 'val_dice', dg = lbDg(m), tol = isNum(L.tol) ? L.tol : LB_TOL_DEF[lbTolKind(m)];
    var list = (Array.isArray(L.rows) ? L.rows : Array.isArray(L.ours) ? L.ours : (L.top_ours ? [L.top_ours] : [])).filter(function (r) { return r && typeof r === 'object'; });
    var h = '<div class="lb-ov"><div class="lb-ov-bb"><span class="chip fam-baseline">' + esc(t('lb_kpi_baseline')) + '</span><b>' + esc(bb.name || bb.id || '—') + '</b><span class="mono">' + esc(fmt(bb.value, dg)) + '</span>' +
      (bb.provisional ? '<span class="chip st-running" title="' + esc(t('lb_provisional_tip')) + '">' + esc(t('lb_provisional')) + '</span>' : '') + '</div>' +
      (list.length ? list.map(function (r) {
        return '<a class="lb-ov-line" href="#/leaderboard"><span class="ours-name">★ ' + esc(r.name || r.run_id || '—') + '</span><span class="mono lb-ov-val">' + esc(fmt(r.value, dg)) + '</span>' +
          lbVdChip(r.verdict, !!(r.provisional || bb.provisional)) + '<span class="mono ' + lbDcls(r.delta, tol) + '">Δ ' + esc(fmtSigned(r.delta, dg)) + '</span>' + (r.trend ? lbTrend(r.trend) : '') + '</a>';
      }).join('') : '<div class="muted small">' + esc(t('lb_no_ours')) + '</div>');
    var ev = L.latest_event;
    if (ev && typeof ev === 'object') {
      var v = lbEvImproved(ev) ? 'up' : (LB_VERDICTS.indexOf(ev.to) >= 0 ? ev.to : 'behind');
      h += '<div class="lb-ov-ev"><span class="lb-dot vd-' + v + '"></span><span class="lb-ov-evmsg">' + esc(lbEvMsg(ev)) + '</span><span class="dim small nowrap">' + esc(ago(ev.ts)) + '</span></div>';
    }
    lbSet(el, h + '</div>');
    if (meta) meta.textContent = lbMetricName(m) + ' · ' + t('lb_tol') + ' ' + fmt(tol, lbTolKind(m) === 'hd' ? 1 : 3);
    lbCheckEvents(Array.isArray(L.recent_events) ? L.recent_events : (ev ? [ev] : []));
  }

  VIEWS.leaderboard = {
    src: 'runs',
    mount: function () {
      return '<div class="grid"><div class="card s12"><div class="controls lb-controls" style="margin:0">' +
        '<label>' + esc(t('lb_scope')) + '</label><span class="seg" id="lb-scope"><button type="button" data-v="live">' + esc(t('lb_scope_live')) + '</button><button type="button" data-v="final">' + esc(t('lb_scope_final')) + '</button></span>' +
        '<label>' + esc(t('lb_metric')) + ' <select id="lb-metric"></select></label>' +
        '<label class="lb-final-only">' + esc(t('lb_dataset')) + ' <select id="lb-ds"></select></label>' +
        '<span class="lb-final-only lb-inline"><label>' + esc(t('rs_stat')) + '</label><span class="seg" id="lb-stat"><button type="button" data-v="mean">' + esc(t('rs_stat_mean')) + '</button><button type="button" data-v="median">' + esc(t('rs_stat_median')) + '</button></span></span>' +
        '<label title="' + esc(t('lb_tol_tip')) + '">' + esc(t('lb_tol')) + ' <input type="number" id="lb-tol" class="lb-tol" min="0" step="0.001" inputmode="decimal"><span class="dim small" id="lb-tol-unit"></span></label>' +
        '<label title="' + esc(t('lb_only_ours_tip')) + '"><input type="checkbox" id="lb-only"> ' + esc(t('lb_only_ours')) + '</label>' +
        '<label title="' + esc(t('lb_notify_tip')) + '"><input type="checkbox" id="lb-notify"> ' + esc(t('lb_notify')) + '</label><span id="lb-notify-st"></span>' +
        '<span class="grow"></span><span class="tag muted small">' + esc(t('lb_rule_note')) + '</span><span class="muted small" id="lb-updated"></span></div></div></div>' +
        '<div class="kpis lb-kpis" id="lb-kpis"></div><div class="kpi-asof" id="lb-kpi-asof" data-srcs="runs" hidden></div>' +
        '<div class="grid"><div class="card s12"><h2><span id="lb-table-h">' + esc(t('lb_table')) + '</span><span id="lb-sum" class="lb-sum"></span><span class="grow"></span>' +
        '<span class="chip lv-warn" id="lb-fallback" style="display:none" title="' + esc(t('rs_fallback_tip')) + '">† ' + esc(t('rs_fallback_note')) + '</span><span class="tag muted small" id="lb-count"></span></h2>' +
        '<div id="lb-table"></div></div></div>' +
        '<div class="grid">' +
        '<div class="card s8"><h2><span id="lb-race-h">' + esc(t('lb_race')) + '</span><span class="grow"></span><span class="lb-race-ctl" id="lb-race-ctl"><span class="seg" id="lb-curve"><button type="button" data-v="best">' + esc(t('lb_curve_best')) + '</button><button type="button" data-v="raw">' + esc(t('lb_curve_raw')) + '</button></span>' +
        '<label class="tag small"><input type="checkbox" id="lb-focus"> ' + esc(t('lb_focus')) + '</label></span></h2>' +
        '<div class="muted tiny lb-race-note" id="lb-race-note">' + esc(t('lb_race_note')) + '</div><div id="lb-race" class="chart tall" style="display:none"></div><div id="lb-race-empty"></div></div>' +
        '<div class="card s4" data-src="leaderboard"><h2>' + esc(t('lb_timeline')) + '<span class="grow"></span><select id="lb-ev-run" class="tag"></select></h2><div class="lb-tl" id="lb-tl"></div></div>' +
        '</div>';
    },
    bind: function () {
      var self = this;
      function reload() { lbHash(); self.data = null; self.update(null); refreshNow(); }
      $('#lb-scope').addEventListener('click', function (e) { var b = e.target.closest('button'); if (!b) return; var v = b.getAttribute('data-v') === 'final' ? 'final' : 'live'; if (v === LB.scope) return; LB.scope = v; LS.set('an_lb_scope', v); reload(); });
      $('#lb-metric').addEventListener('change', function (e) { if (LB.scope === 'final') { LB.fmetric = e.target.value; LS.set('an_lb_fmetric', LB.fmetric); } else { LB.metric = e.target.value; LS.set('an_lb_metric', LB.metric); } reload(); });
      $('#lb-ds').addEventListener('change', function (e) { LB.ds = e.target.value; LS.set('an_lb_ds', LB.ds); reload(); });
      $('#lb-stat').addEventListener('click', function (e) { var b = e.target.closest('button'); if (!b) return; LB.stat = b.getAttribute('data-v') === 'median' ? 'median' : 'mean'; LS.set('an_lb_stat', LB.stat); reload(); });
      $('#lb-tol').addEventListener('change', function (e) {
        var k = lbTolKind(), v = parseFloat(e.target.value);
        LB.tol[k] = lbClampTol(isFinite(v) ? v : LB_TOL_DEF[k], k);
        e.target.value = String(LB.tol[k]);
        LS.set('an_lb_tol', LB.tol); refreshNow();
      });
      $('#lb-only').addEventListener('change', function (e) { LB.only = e.target.checked; LS.set('an_lb_only', LB.only); if (self.data) self.update(self.data); });
      $('#lb-curve').addEventListener('click', function (e) { var b = e.target.closest('button'); if (!b) return; LB.curve = b.getAttribute('data-v') === 'raw' ? 'raw' : 'best'; LS.set('an_lb_curve', LB.curve); if (self.data) self.update(self.data); });
      $('#lb-focus').addEventListener('change', function (e) { LB.focus = e.target.checked; LS.set('an_lb_focus', LB.focus); if (self.data) self.update(self.data); });
      $('#lb-notify').addEventListener('change', function (e) {
        LB.notify = e.target.checked; LS.set('an_lb_notify', LB.notify);
        var N = window.Notification;
        if (LB.notify && N && N.permission === 'default' && N.requestPermission) {
          try { var p = N.requestPermission(lbNotifyState); if (p && p.then) p.then(lbNotifyState, lbNotifyState); } catch (x) { /* ignore */ }
        }
        lbNotifyState();
      });
      $('#lb-ev-run').addEventListener('change', function (e) { LB.evRun = e.target.value; if (self.data) self.update(self.data); });
      function openRow(tr) {
        var id = tr && tr.getAttribute('data-run');
        if (!id) return;
        location.hash = LB.scope === 'final' ? '#/results?ds=' + enc(LB.ds) + '&metric=' + enc(LB.fmetric) + '&stat=' + LB.stat : '#/training?run=' + enc(id);
      }
      $('#lb-table').addEventListener('click', function (e) { openRow(e.target.closest('tr[data-run]')); });
      $('#lb-table').addEventListener('keydown', function (e) { if (e.key === 'Enter') { var tr = e.target.closest('tr[data-run]'); if (tr) { e.preventDefault(); openRow(tr); } } });
    },
    load: function () {
      var self = this, m = lbMetric();
      var q = '/api/leaderboard?scope=' + LB.scope + '&metric=' + enc(m) + '&dataset=' + enc(LB.ds) + '&stat=' + LB.stat + '&tol=' + enc(String(lbTol()));
      var jobs = [api(q).catch(function (e) { return { ok: false, error: String((e && e.message) || e || 'error') }; })];
      if (LB.scope === 'final' && Date.now() - LB.resAt > 60000) {
        jobs.push(api('/api/results').then(function (r) { LB.res = (r && r.summary) || null; LB.resAt = Date.now(); }, function () { LB.resAt = Date.now(); }));
      }
      return Promise.all(jobs).then(function (r) { self.data = r[0]; });
    },
    controls: function (d) {
      var fin = LB.scope === 'final', res = LB.res;
      if (d && Array.isArray(d.metrics)) d.metrics.forEach(function (x) { if (x && typeof x === 'object' && x.id) { if (x.kind) LB.kinds[x.id] = x.kind; LB.avail[x.id] = x.available !== false; } });
      if (d && d.metric && d.kind) LB.kinds[d.metric] = d.kind;
      $$('#lb-scope button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === LB.scope); });
      $$('#lb-stat button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === LB.stat); });
      $$('.lb-final-only', this.el).forEach(function (x) { x.style.display = fin ? '' : 'none'; });
      var mets, dss = [];
      if (fin) {
        mets = (d && Array.isArray(d.metrics) && d.metrics.length ? d.metrics : (res && Array.isArray(res.metrics) ? res.metrics : [])).map(function (x) { return typeof x === 'string' ? { id: x } : x; }).filter(function (x) { return x && x.id; });
        dss = (d && Array.isArray(d.datasets) && d.datasets.length ? d.datasets : (res && Array.isArray(res.datasets) ? res.datasets : [])).map(function (x) { return typeof x === 'string' ? { id: x } : x; }).filter(function (x) { return x && x.id; });
        if (!mets.length) mets = [{ id: LB.fmetric }];
        if (!dss.length) dss = [{ id: LB.ds }];
        var fix = false;
        if (!mets.some(function (x) { return x.id === LB.fmetric; })) { LB.fmetric = (mets.filter(function (x) { return /dice|dsc/i.test(x.id); })[0] || mets[0]).id; fix = true; }
        if (!dss.some(function (x) { return x.id === LB.ds; })) { LB.ds = (dss.filter(function (x) { return x.id === 'inhouse_val'; })[0] || dss[0]).id; fix = true; }
        setOpts('#lb-metric', mets.map(function (x) { return [x.id, bi(x, 'name') || x.id]; }), LB.fmetric);
        setOpts('#lb-ds', dss.map(function (x) { return [x.id, (bi(x, 'name') || x.id) + (isNum(x.n) ? ' (n=' + x.n + ')' : '')]; }), LB.ds);
        if (fix) { setTimeout(refreshNow, 0); }
      } else {
        mets = (d && Array.isArray(d.metrics) && d.metrics.length ? d.metrics : LB_LIVE_METRICS).map(function (x) { return typeof x === 'string' ? x : x && x.id; }).filter(Boolean);
        if (mets.indexOf(LB.metric) < 0 && mets.indexOf('val_dice') >= 0) { LB.metric = 'val_dice'; setTimeout(refreshNow, 0); }
        setOpts('#lb-metric', mets.map(function (x) { return [x, lbMetricName(x) + (LB.avail[x] === false ? ' ' + t('lb_m_na') : '')]; }), LB.metric);
      }
      var k = lbTolKind(), inp = $('#lb-tol');
      inp.step = k === 'hd' ? '0.1' : '0.001';
      inp.max = String(d && isNum(d.tol_max) && (!d.metric || d.metric === lbMetric()) ? d.tol_max : LB_TOL_MAX[k]);
      if (document.activeElement !== inp) inp.value = String(lbTol());
      $('#lb-tol-unit').textContent = k === 'hd' ? 'mm' : '';
      $('#lb-only').checked = LB.only;
      $('#lb-focus').checked = LB.focus;
      $('#lb-notify').checked = LB.notify;
      $('#lb-race-ctl').style.display = fin ? 'none' : '';
      $$('#lb-curve button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === LB.curve); });
      $('#lb-table-h').textContent = t(fin ? 'lb_table_final' : 'lb_table');
      $('#lb-race-h').textContent = t(fin ? 'lb_race_final' : 'lb_race');
      $('#lb-race-note').textContent = t(fin ? 'lb_final_note' : 'lb_race_note');
      lbNotifyState();
    },
    update: function (d) {
      this.controls(d);
      var m = lbMetric(), fin = LB.scope === 'final';
      this.src = fin ? 'results' : 'runs';
      var lbStrip = $('#lb-kpi-asof');
      if (lbStrip) lbStrip.setAttribute('data-srcs', this.src);
      if (d && d.ok !== false) frNote(this.src, d.updated);
      var lbEv = d && Array.isArray(d.events) && d.events[0];
      if (lbEv) frNote('leaderboard', lbEv.ts);
      var stale = d && ((d.scope && d.scope !== LB.scope) || (d.metric && d.metric !== m));
      var ok = d && d.ok !== false && Array.isArray(d.rows) && !stale;
      var kp = $('#lb-kpis');
      if (!ok) {
        var box;
        if (!d || stale) box = emptyBox('lb_loading', null);
        else if (d.ok === false && d.error) box = emptyBox('lb_load_error', 'lb_load_error_hint', { e: esc(clip(d.error, 200)) });
        else box = emptyBox('lb_unavailable', 'lb_unavailable_hint');
        lbSet($('#lb-table'), box);
        lbSet(kp, ['lb_kpi_baseline', 'lb_kpi_ours', 'lb_kpi_gap', 'lb_kpi_latest'].map(function (k) { return lbTile(k, '—', '<span>' + esc(t('lb_waiting')) + '</span>'); }).join(''));
        $('#lb-sum').innerHTML = ''; $('#lb-count').textContent = ''; $('#lb-updated').textContent = ''; $('#lb-fallback').style.display = 'none';
        chartOrEmpty('lb-race', false, emptyBox(!d || stale ? 'lb_loading' : 'lb_unavailable', null));
        lbSet($('#lb-tl'), emptyBox('lb_no_events', null));
        setOpts('#lb-ev-run', [['', t('lb_all_runs')]], '');
        return;
      }
      function evsRaw() { return (Array.isArray(d.events) ? d.events : []).filter(function (e) { return e && typeof e === 'object'; }); }
      var hib = typeof d.hib === 'boolean' ? d.hib : !lowerIsBetter(m), dg = lbDg(m), tol = isNum(d.tol) ? d.tol : lbTol();
      var bb = d.best_baseline && typeof d.best_baseline === 'object' ? d.best_baseline : {}, prov = !!bb.provisional;
      $('#lb-updated').textContent = d.updated ? t('updated_at', { t: fmtTime(d.updated) }) : '';
      var all = d.rows.filter(function (r) { return r && typeof r === 'object' && r.run_id !== undefined; });
      function cmp(a, b) {
        var ra = isNum(a.rank) ? a.rank : Infinity, rb = isNum(b.rank) ? b.rank : Infinity;
        if (ra !== rb) return ra - rb;
        if (isNum(a.value) !== isNum(b.value)) return isNum(a.value) ? -1 : 1;
        return isNum(a.value) ? (hib ? b.value - a.value : a.value - b.value) : 0;
      }
      all.sort(cmp);
      var rows = all.filter(function (r) { return !LB.only || r.family !== 'ablation'; });
      var names = {};
      evsRaw().forEach(function (e) { if (e.run_id && e.name) names[e.run_id] = e.name; });
      all.forEach(function (r) { names[r.run_id] = r.name || r.run_id; });
      var ours = all.filter(function (r) { return lbOursRow(r) && isNum(r.value) && !r.not_counted; });
      // ---- KPI strip
      var tiles = [];
      tiles.push(lbTile('lb_kpi_baseline', isNum(bb.value) ? esc(fmt(bb.value, dg)) : '—',
        '<span class="lb-kpi-nm">' + esc(bb.name || names[bb.id] || bb.id || t('lb_none')) + '</span>' + (prov ? '<span class="chip st-running" title="' + esc(t('lb_provisional_tip')) + '">' + esc(t('lb_provisional')) + '</span>' : ''), 'accent-blue'));
      var top = ours[0];
      tiles.push(top ? lbTile('lb_kpi_ours', (top.verdict === 'sota' ? '<span class="star">★</span>' : '') + esc(fmt(top.value, dg)),
        '<span class="ours-name lb-kpi-nm">' + esc(top.name || top.run_id) + '</span>' + lbVdChip(top.verdict, !!(top.provisional || prov)) + '<span class="mono ' + lbDcls(top.delta, tol) + '">Δ ' + esc(fmtSigned(top.delta, dg)) + '</span>', 'ours-card accent-amber') :
        lbTile('lb_kpi_ours', '—', '<span>' + esc(t('lb_no_ours')) + '</span>', 'ours-card'));
      var runTop = ours.filter(function (r) { return r.status === 'running'; })[0], gr = runTop || top;
      if (gr) {
        var first = gr.rank === 1 || (d.sota && d.sota.id === gr.run_id) || (isNum(gr.delta_sota) && Math.abs(gr.delta_sota) < 1e-12);
        var gapV = first ? '<span class="lb-first">' + esc(t('lb_is_first')) + '</span>' : (isNum(gr.delta_sota) ? esc(fmt(Math.abs(gr.delta_sota), dg)) : '—');
        tiles.push(lbTile('lb_kpi_gap', gapV,
          '<span class="ours-name lb-kpi-nm">' + esc(gr.name || gr.run_id) + '</span>' + (first ? '' : '<span>' + esc(t('lb_gap_sota_lbl')) + '</span>') +
          '<span class="mono ' + lbDcls(gr.delta, tol) + '">' + esc(t('lb_vs_bb', { d: fmtSigned(gr.delta, dg) })) + '</span>' +
          (runTop ? (isNum(gr.epoch) ? '<span class="mono">' + esc(isNum(gr.total_epochs) ? t('lb_epoch_of', { e: gr.epoch, n: gr.total_epochs }) : t('lb_best_epoch', { e: gr.epoch })) + '</span>' : '') : '<span class="dim">' + esc(t('lb_no_running_ours')) + '</span>'),
          first ? 'accent-amber' : ''));
      } else tiles.push(lbTile('lb_kpi_gap', '—', '<span>' + esc(t('lb_no_ours')) + '</span>'));
      var evs = evsRaw().slice().sort(function (a, b) { return (lbEvTs(b) || 0) - (lbEvTs(a) || 0); });
      var le = evs[0];
      tiles.push(le ? lbTile('lb_kpi_latest', esc(clip(lbEvMsg(le, names), 90)), (lbEvImproved(le) ? '<span class="lb-tr lb-tr-up">' + esc(t('lb_ev_improved')) + '</span>' : lbVdChip(le.to, false)) + '<span>' + esc(ago(le.ts)) + '</span>', 'txt lb-kpi-latest', lbEvMsg(le, names)) :
        lbTile('lb_kpi_latest', '—', '<span>' + esc(t('lb_no_events')) + '</span>'));
      lbSet(kp, tiles.join(''));
      // ---- verdict summary of our models + counts
      $('#lb-sum').innerHTML = LB_VERDICTS.map(function (v) {
        var n = ours.filter(function (r) { return r.verdict === v; }).length;
        return n ? '<span class="chip vd vd-' + v + '">' + esc(tk('vd_', v)) + ' ' + n + '</span>' : '';
      }).join('');
      $('#lb-count').textContent = t('lb_count', { n: rows.length, k: ours.length });
      $('#lb-fallback').style.display = fin && LB.stat === 'median' && all.some(function (r) { return !!r.median_fallback; }) ? '' : 'none';
      // ---- table
      if (!rows.length) lbSet($('#lb-table'), emptyBox('lb_no_rows', 'lb_no_rows_hint'));
      else {
        var head = fin ? ['lb_col_model', 'lb_col_value', 'lb_col_ci', 'lb_col_n', 'lb_col_delta', 'lb_col_verdict'] :
          ['lb_col_model', 'lb_col_status', 'lb_col_best', 'lb_col_current', 'lb_col_delta', 'lb_col_verdict', 'lb_col_trend', 'lb_col_spark'];
        var tip = t(fin ? 'lb_row_tip_final' : 'lb_row_tip');
        var body = rows.map(function (r, i) {
          var isO = lbOursRow(r), isA = r.family === 'ablation', isBB = bb.id !== undefined && r.run_id === bb.id;
          var rk = isNum(r.rank) ? r.rank : (isNum(r.value) && !r.not_counted ? i + 1 : null);
          var nm = '<div class="lb-model"><span class="lb-rank' + (rk === 1 ? ' r1' : rk === 2 ? ' r2' : rk === 3 ? ' r3' : '') + '">' + (rk === null ? '–' : esc(rk)) + '</span>' +
            '<span class="lb-nm"><span class="' + (isO ? 'ours-name' : '') + '">' + esc(r.name || r.run_id) + '</span>' +
            '<span class="lb-badges">' + (isO || isA ? famChip(r.family) : '') + (isBB ? '<span class="chip fam-baseline">' + esc(t('lb_best_baseline_tag')) + '</span>' : '') +
            (r.not_counted ? '<span class="chip lb-nc" title="' + esc(t('lb_not_counted_tip')) + '">' + esc(t('lb_not_counted')) + '</span>' : '') + '</span>' +
            (r.name && r.name !== r.run_id ? '<span class="mono tiny dim">' + esc(r.run_id) + '</span>' : '') + '</span></div>';
          var dlTip = t('lb_delta_tip', { s: isNum(r.delta_sota) ? fmt(Math.abs(r.delta_sota), dg) : '—' });
          var dl = '<td class="num ' + (r.not_counted ? 'dim' : lbDcls(r.delta, tol)) + '" title="' + esc(r.not_counted ? t('lb_not_counted_tip') : dlTip) + '">' + esc(fmtSigned(r.delta, dg)) + '</td>';
          var vd = '<td>' + (r.not_counted ? '<span class="dim" title="' + esc(t('lb_not_counted_tip')) + '">—</span>' : isO ? lbVdChip(r.verdict, !!(r.provisional || prov)) : (LB_VERDICTS.indexOf(r.verdict) >= 0 ? lbVdChip(r.verdict, false) : '<span class="dim">—</span>')) + '</td>';
          var cells;
          if (fin) {
            cells = '<td class="num lb-val"' + (r.median_fallback ? ' title="' + esc(t('rs_fallback_tip')) + '"' : '') + '>' + esc(fmt(r.value, dg)) + (r.median_fallback ? '<span class="lb-fb"> †</span>' : '') + '</td>' +
              '<td class="num dim">' + (isNum(r.ci_low) && isNum(r.ci_high) ? '[' + esc(fmt(r.ci_low, dg)) + ', ' + esc(fmt(r.ci_high, dg)) + ']' : '—') + '</td>' +
              '<td class="num">' + (isNum(r.n) ? esc(r.n) : '—') + '</td>' + dl + vd;
          } else {
            var st = r.status || 'unknown', ep = isNum(r.epoch) ? (isNum(r.total_epochs) ? t('lb_epoch_of', { e: r.epoch, n: r.total_epochs }) : t('lb_best_epoch', { e: r.epoch })) : '';
            cells = '<td class="nowrap">' + stChip(st) + (ep ? ' <span class="mono small">' + esc(ep) + '</span>' : '') +
              (st === 'running' && isNum(r.epoch) && isNum(r.total_epochs) && r.total_epochs > 0 ? bar(r.epoch / r.total_epochs) : '') +
              (st === 'running' && isNum(r.eta_s) ? '<div class="dim tiny">' + esc(t('lb_eta', { d: fmtDur(r.eta_s) })) + '</div>' : '') + '</td>' +
              '<td class="num lb-val">' + esc(fmt(r.value, dg)) + (isNum(r.best_epoch) ? '<div class="dim tiny">' + esc(r.x_unit === 'step' ? t('lb_at_step', { s: r.best_epoch }) : t('lb_at_epoch', { e: r.best_epoch })) + '</div>' : '') + '</td>' +
              '<td class="num">' + esc(fmt(r.current, dg)) + '</td>' + dl + vd +
              '<td class="nowrap">' + lbTrend(r.trend) + '</td><td>' + lbSpark(r, hib, bb.value) + '</td>';
          }
          return '<tr data-run="' + esc(r.run_id) + '" tabindex="0" title="' + esc(tip) + '" class="' + (isO ? 'ours-row' : isA ? 'abl-row' : 'base-row') + (r.verdict === 'sota' ? ' sota-row' : '') + (r.not_counted ? ' lb-off' : '') + '"><td>' + nm + '</td>' + cells + '</tr>';
        }).join('');
        lbSet($('#lb-table'), '<div class="tbl-wrap lb-wrap"><table class="tbl sticky1 lb-tbl"><thead><tr>' + head.map(function (k, i) { return '<th' + (i > 0 && !/verdict|trend|spark|status/.test(k) ? ' class="right"' : '') + '>' + esc(t(k)) + '</th>'; }).join('') + '</tr></thead><tbody>' + body + '</tbody></table></div>');
      }
      // ---- race chart / final comparison
      if (fin) this.finalChart(rows, bb, hib, dg, tol); else this.raceChart(rows, bb, hib, dg, tol, d.crossings || {});
      // ---- change timeline
      var runIds = uniq(evs.map(function (e) { return e.run_id; }));
      if (LB.evRun && runIds.indexOf(LB.evRun) < 0) LB.evRun = '';
      setOpts('#lb-ev-run', [['', t('lb_all_runs')]].concat(runIds.map(function (id) { return [id, names[id] || id]; })), LB.evRun);
      var fe = evs.filter(function (e) { return !LB.evRun || e.run_id === LB.evRun; });
      lbSet($('#lb-tl'), fe.length ? fe.map(function (e) {
        var up = lbEvImproved(e), v = up ? 'up' : (LB_VERDICTS.indexOf(e.to) >= 0 ? e.to : 'behind'), edg = lbDg(e.metric || m);
        var tr = up ? '<span class="lb-tr lb-tr-up">' + esc(t('lb_ev_improved')) + '</span>' :
          (LB_VERDICTS.indexOf(e.from) >= 0 ? lbVdChip(e.from, false) + '<span class="dim">→</span>' : '') + lbVdChip(e.to, false);
        return '<div class="mtl-item lb-ev"><div class="mtl-dot lb-dot vd-' + v + '"></div><div class="mtl-body"><div class="mtl-head">' +
          '<span class="chip mono ' + (isOursFam((all.filter(function (r) { return r.run_id === e.run_id; })[0] || {}).family) ? 'fam-ours' : '') + '" title="' + esc(names[e.run_id] || e.run_id || '?') + '">' + esc(names[e.run_id] || e.run_id || '?') + '</span>' + tr +
          (e.metric ? '<span class="tag tiny muted">' + esc(lbMetricName(e.metric)) + '</span>' : '') + '</div>' +
          '<div class="mtl-msg">' + esc(lbEvMsg(e, names)) + '</div>' +
          '<div class="lb-ev-meta mono tiny">' + (isNum(e.epoch) ? '<span>' + esc(e.x_unit === 'step' ? t('lb_step_n', { s: e.epoch }) : t('lb_best_epoch', { e: e.epoch })) + '</span>' : '') +
          (isNum(e.value) ? '<span>' + esc(fmt(e.value, edg)) + (isNum(e.baseline) ? ' vs ' + esc(fmt(e.baseline, edg)) + (e.baseline_id ? ' (' + esc(names[e.baseline_id] || e.baseline_id) + ')' : '') : '') + '</span>' : '') +
          '<span title="' + esc(fmtTime(e.ts)) + '">' + esc(ago(e.ts)) + '</span></div></div></div>';
      }).join('') : emptyBox('lb_no_events', 'lb_no_events_hint'));
      lbCheckEvents(evs);
    },
    raceChart: function (rows, bb, hib, dg, tol, crossings) {
      var bestC = LB.curve !== 'raw', withPts = rows.filter(function (r) { return lbPts(r, bestC).length > 0; });
      var mob = window.matchMedia && window.matchMedia('(max-width: 700px)').matches;
      var c = chartOrEmpty('lb-race', withPts.length > 0, emptyBox('lb_no_series', 'lb_no_series_hint'), mob ? 260 : 440);
      if (!c) return;
      var B = isNum(bb.value) ? bb.value : null, thr = B === null ? null : (hib ? B + tol : B - tol);
      var lo = Infinity, hi = -Infinity, xmax = 0;
      var series = withPts.map(function (r) {
        var pts = lbPts(r, bestC), isO = lbOursRow(r), col = lbColor(r), cr = crossings[r.run_id] || {};
        pts.forEach(function (p) { lo = Math.min(lo, p[1]); hi = Math.max(hi, p[1]); xmax = Math.max(xmax, p[0]); });
        var mp = [];
        if (isO) {
          ['tie', 'ahead', 'sota'].forEach(function (k, ki) {
            var ep = cr[k];
            if (!isNum(ep)) return;
            var at = pts.filter(function (p) { return p[0] >= ep; })[0] || pts[pts.length - 1];
            mp.push({ coord: [ep, at[1]], name: k, symbol: k === 'sota' ? 'diamond' : 'circle', symbolSize: k === 'sota' ? 14 : 10,
              itemStyle: { color: LB_VD_COLOR[k], borderColor: '#04080f', borderWidth: 1 },
              label: { show: !mob, formatter: t('lb_cross_lbl', { v: tk('vd_', k), e: ep }), position: ['bottom', 'top', 'right'][ki], color: LB_VD_COLOR[k], fontSize: 11, fontWeight: 'bold', distance: 6, backgroundColor: 'rgba(4,8,15,0.78)', padding: [1, 4], borderRadius: 3 } });
          });
        }
        return { name: starName(r.name || r.run_id, r.family), type: 'line', showSymbol: false, symbolSize: 4, smooth: false, color: col, z: isO ? 5 : 2,
          lineStyle: { width: isO ? 2.6 : 1.4, opacity: isO ? 1 : 0.85, type: r.family === 'ablation' ? [6, 3] : 'solid' }, emphasis: { focus: 'series' },
          data: pts.map(function (p) { return [p[0], p[1]]; }), markPoint: mp.length ? { data: mp, animation: false } : undefined };
      });
      if (B !== null) {
        var ml = [{ yAxis: B, name: 'B', lineStyle: { type: 'dashed', color: '#60a5fa', width: 1.6 }, label: { formatter: t('lb_line_bb') + ' ' + fmt(B, dg), position: hib ? 'insideEndBottom' : 'insideEndTop', color: '#93c5fd', backgroundColor: 'rgba(4,8,15,0.78)', padding: [1, 4], borderRadius: 3 } }];
        if (tol > 0) ml.push({ yAxis: thr, name: 'T', lineStyle: { type: 'dotted', color: '#34d399', width: 1.6 }, label: { show: !mob, formatter: t(hib ? 'lb_line_tol_up' : 'lb_line_tol_dn') + ' ' + fmt(thr, dg), position: hib ? 'insideEndTop' : 'insideEndBottom', color: '#6ee7b7', backgroundColor: 'rgba(4,8,15,0.78)', padding: [1, 4], borderRadius: 3 } });
        series.push({ name: t('lb_line_bb'), type: 'line', data: [], color: '#60a5fa', silent: true, symbol: 'none', lineStyle: { type: 'dashed' },
          markLine: { silent: true, symbol: 'none', animation: false, data: ml },
          markArea: tol > 0 ? { silent: true, itemStyle: { color: 'rgba(251,191,36,0.07)' }, data: [[{ yAxis: B - tol }, { yAxis: B + tol }]] } : undefined });
      }
      var y = ax({ type: 'value', scale: true, name: lbMetricName(lbMetric()), nameGap: 10, nameTextStyle: { color: CC.muted, align: 'left' }, axisLabel: { color: CC.muted, formatter: function (v) { return fmt(v, dg >= 4 ? 3 : 1); } } });
      if (LB.focus && B !== null && isFinite(lo)) {
        if (dg >= 4) { y.min = Math.max(lo, B - Math.max(0.08, 12 * tol)); y.max = Math.min(Math.max(hi, B + 2 * tol) + 0.01, hi > 1 ? hi + 0.01 : 1); }
        else { y.min = Math.max(0, Math.min(lo, B - 2 * tol) - 0.2); y.max = Math.min(hi, B + Math.max(4, 6 * tol)); }
        // snap the window to a "nice" interval so the first / last tick labels never crowd
        var span = y.max - y.min, steps = dg >= 4 ? [0.002, 0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.2] : [0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20];
        var stp = steps.filter(function (x) { return x >= span / 6; })[0] || steps[steps.length - 1];
        y.min = Math.floor(y.min / stp + 1e-9) * stp; y.max = Math.ceil(y.max / stp - 1e-9) * stp;
        if (!(y.max > y.min)) { delete y.min; delete y.max; }
        else { y.min = +y.min.toFixed(4); y.max = +y.max.toFixed(4); y.interval = stp; }
      }
      var dz = keepZoom(c, [{ type: 'inside', xAxisIndex: 0 }, { type: 'slider', xAxisIndex: 0, height: 16, bottom: 6, borderColor: '#24466e', textStyle: { color: CC.muted }, fillerColor: 'rgba(34,211,238,0.12)', moveHandleSize: 5, moveHandleStyle: { color: '#24466e' }, handleStyle: { color: '#22d3ee', borderColor: '#0a1222' }, brushSelect: false }]);
      c.setOption({
        backgroundColor: 'transparent', animation: false,
        grid: { left: 52, right: mob ? 14 : 24, top: mob ? 66 : 60, bottom: 50 },
        tooltip: Object.assign({ trigger: 'axis', valueFormatter: function (v) { return fmt(v, dg); } }, TT),
        legend: Object.assign({}, LEG, { data: series.map(function (s) { return s.name; }) }),
        xAxis: ax({ type: 'value', name: t('tr_epoch'), nameLocation: 'middle', nameGap: 24, min: 0, max: xmax > 0 ? xmax : null, minInterval: 1 }),
        yAxis: y, dataZoom: dz, series: series
      }, true);
    },
    finalChart: function (rows, bb, hib, dg, tol) {
      var vr = rows.filter(function (r) { return isNum(r.value); });
      var c = chartOrEmpty('lb-race', vr.length > 0, emptyBox('lb_no_rows', null), Math.max(260, Math.min(720, 30 * vr.length + 70)));
      if (!c) return;
      var B = isNum(bb.value) ? bb.value : null, ml = [];
      if (B !== null) {
        ml.push({ xAxis: B, lineStyle: { type: 'dashed', color: '#60a5fa', width: 1.6 }, label: { formatter: t('lb_line_bb') + ' ' + fmt(B, dg), color: '#93c5fd', position: 'end', backgroundColor: 'rgba(4,8,15,0.78)', padding: [1, 4], borderRadius: 3 } });
        if (tol > 0) ml.push({ xAxis: hib ? B + tol : B - tol, lineStyle: { type: 'dotted', color: '#34d399', width: 1.6 }, label: { show: false } });
      }
      var lo = Math.min.apply(null, vr.map(function (r) { return isNum(r.ci_low) ? r.ci_low : r.value; }).concat(B !== null ? [B] : []));
      var hi = Math.max.apply(null, vr.map(function (r) { return isNum(r.ci_high) ? r.ci_high : r.value; }).concat(B !== null ? [B] : []));
      var pad = (hi - lo) * 0.15 || 0.01;
      c.setOption({
        backgroundColor: 'transparent', animation: false, grid: { left: 8, right: 64, top: 26, bottom: 28, containLabel: true },
        tooltip: Object.assign({ trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: function (v) { return fmt(v, dg); } }, TT),
        xAxis: ax({ type: 'value', min: +(lo - pad).toFixed(4), max: +(hi + pad).toFixed(4), axisLabel: { color: CC.muted, formatter: function (v) { return fmt(v, dg >= 4 ? 3 : 1); } } }),
        yAxis: ax({ type: 'category', inverse: true, data: vr.map(function (r) { return starName(r.name || r.run_id, r.family); }), axisLabel: { color: CC.text, width: 180, overflow: 'truncate' } }),
        series: [{ type: 'bar', barMaxWidth: 18, data: vr.map(function (r) { return { value: r.value, itemStyle: { color: lbColor(r), borderRadius: [0, 3, 3, 0] } }; }),
          label: { show: true, position: 'right', color: CC.text, fontSize: 11, formatter: function (p) { return fmt(p.value, dg); } }, markLine: ml.length ? { silent: true, symbol: 'none', animation: false, data: ml } : undefined }]
      }, true);
    }
  };

  // ------------------------------------------------------------------ Agents
  var A = { sel: LS.get('an_agent_sel', null), filter: '', activeOnly: false, follow: true, cursor: -1, streamFor: null, msgs: [], renderedSeq: -1, renderedFor: null };
  var MAX_CLIENT_MSGS = 600;
  function toolCard(b) {
    var i = b.input || {}, nm = String(b.name || '?');
    var h = '<div class="toolcard"><span class="tn">⚙ ' + esc(nm) + '</span>' + (i.desc ? '<span class="td">' + esc(i.desc) + '</span>' : '') + (i.flags ? ' <span class="chip">' + esc(i.flags) + '</span>' : '');
    if (i.main) h += '<pre>' + esc(i.main) + '</pre>';
    if (i.old) h += '<pre class="diff-old">− ' + esc(i.old) + '</pre>';
    if (i.new) h += '<pre class="diff-new">+ ' + esc(i.new) + '</pre>';
    return h + '</div>';
  }
  function resultBlock(b) {
    var txt = String(b.text || ''), short = txt.length > 600;
    var h = '<div class="result' + (b.is_error ? ' err' : '') + '"><div class="rh">↩ <span class="mono">' + esc(b.name || t('tool_result')) + '</span>' + (b.is_error ? '<span class="chip lv-error">' + esc(t('error')) + '</span>' : '') +
      '<span class="dim">' + esc(t('n_chars', { n: b.len || txt.length })) + '</span>' + (short ? '<button class="linkbtn" type="button" data-expand="1">' + esc(t('expand')) + '</button>' : '') + '</div>';
    if (short) h += '<pre class="r-short">' + esc(txt.slice(0, 600)) + '…</pre><pre class="r-full hidden">' + esc(txt) + '</pre>';
    else if (txt) h += '<pre>' + esc(txt) + '</pre>';
    return h + '</div>';
  }
  function msgHtml(m) {
    var role = m.role || 'assistant';
    var blocks = (m.blocks || []).map(function (b) {
      if (b.t === 'text') {
        if (role === 'user' && b.text.length > 1500) return '<div class="result"><div class="rh"><span>' + esc(t('long_prompt')) + '</span><span class="dim">' + esc(t('n_chars', { n: b.text.length })) + '</span><button class="linkbtn" type="button" data-expand="1">' + esc(t('expand')) + '</button></div><div class="plain r-short">' + esc(b.text.slice(0, 600)) + '…</div><div class="plain r-full hidden">' + esc(b.text) + '</div></div>';
        return role === 'assistant' ? md(b.text) : '<div class="plain">' + esc(b.text) + '</div>';
      }
      if (b.t === 'tool_use') return toolCard(b);
      if (b.t === 'tool_result') return resultBlock(b);
      if (b.t === 'thinking') return '<details class="think"><summary>' + esc(t('thinking')) + ' · ' + esc(t('n_chars', { n: b.text.length })) + '</summary><div class="plain">' + esc(b.text) + '</div></details>';
      return '';
    }).join('');
    return '<div class="msg r-' + esc(role) + '" data-seq="' + esc(m.seq) + '"><div class="mh"><span class="role r-' + esc(role) + '">' + esc(tk('role_', role)) + '</span><span class="mono">' + esc(fmtTime(m.ts)) + '</span><span class="dim mono">#' + esc(m.seq) + '</span></div>' + blocks + '</div>';
  }
  function agNoneHint(d) { return d && d.root ? 'ag_none_hint' : 'ag_none_hint_unset'; }   // AN_TRANSCRIPTS set?
  VIEWS.agents = {
    src: 'agents',
    mount: function () {
      return '<div class="grid"><div class="card s12"><h2>' + esc(t('ag_live')) + '<span class="grow"></span><span class="tag small muted" id="ag-count"></span></h2><div class="activity-strip" id="ag-activity"></div></div></div>' +
        '<div class="grid">' +
        '<div class="card s3"><h2>' + esc(t('ag_list')) + '</h2><div class="controls"><input type="search" id="ag-filter" placeholder="' + esc(t('ag_filter_ph')) + '"><label><input type="checkbox" id="ag-activeonly"> ' + esc(t('ag_active_only')) + '</label></div><div class="agent-list" id="ag-list"></div></div>' +
        '<div class="card s9"><h2><span id="ag-head">' + esc(t('ag_stream')) + '</span><span class="grow"></span><label class="tag small"><input type="checkbox" id="ag-follow" checked> ' + esc(t('follow')) + '</label><button class="btn tag" type="button" id="ag-bottom">' + esc(t('jump_latest')) + ' ↓</button></h2>' +
        '<div class="muted small mono" id="ag-meta" style="margin-bottom:.5rem"></div><div class="stream" id="ag-stream"></div></div>' +
        '</div>';
    },
    bind: function () {
      var self = this;
      $('#ag-filter').value = A.filter;
      $('#ag-activeonly').checked = A.activeOnly;
      $('#ag-follow').checked = A.follow;
      $('#ag-filter').addEventListener('input', function (e) { A.filter = e.target.value; if (self.data) self.renderList(self.data); });
      $('#ag-activeonly').addEventListener('change', function (e) { A.activeOnly = e.target.checked; if (self.data) self.renderList(self.data); });
      $('#ag-follow').addEventListener('change', function (e) { A.follow = e.target.checked; });
      $('#ag-bottom').addEventListener('click', function () { var s = $('#ag-stream'); s.scrollTop = s.scrollHeight; });
      function pick(e) {
        var it = e.target.closest('[data-agent]');
        if (!it) return;
        var id = it.getAttribute('data-agent');
        if (id !== A.sel) { A.sel = id; LS.set('an_agent_sel', id); A.cursor = -1; A.streamFor = null; A.msgs = []; A.renderedFor = null; if (self.data) self.renderList(self.data); refreshNow(); }
      }
      $('#ag-list').addEventListener('click', pick);
      $('#ag-activity').addEventListener('click', pick);
      $('#ag-stream').addEventListener('click', function (e) {
        var b = e.target.closest('[data-expand]');
        if (!b) return;
        var box = b.closest('.result');
        var sh = box.querySelector('.r-short'), fu = box.querySelector('.r-full');
        if (!sh || !fu) return;
        var open = fu.classList.contains('hidden');
        fu.classList.toggle('hidden', !open); sh.classList.toggle('hidden', open);
        b.textContent = open ? t('collapse') : t('expand');
      });
    },
    load: function () {
      var self = this;
      return api('/api/agents').then(function (lst) {
        var agents = (lst && lst.agents) || [];
        if (!A.sel || !agents.some(function (a) { return a.id === A.sel; })) {
          var m = agents.filter(function (a) { return a.is_main; })[0] || agents[0];
          if (A.sel !== (m ? m.id : null)) { A.sel = m ? m.id : null; A.cursor = -1; A.streamFor = null; A.msgs = []; A.renderedFor = null; }
        }
        self.data = lst;
        if (!A.sel) return null;
        var target = A.sel;
        function fetchMore(round) {
          var since = A.streamFor === target ? A.cursor : -1;
          return api('/api/agents/' + enc(target) + '/messages?since=' + since + '&limit=200').then(function (res) {
            if (A.sel !== target || !res || res.ok === false) return;
            if (A.streamFor !== target || res.gap) { A.msgs = []; A.renderedFor = null; }
            A.streamFor = target;
            A.cursor = res.cursor;
            A.summary = res.summary;
            Array.prototype.push.apply(A.msgs, res.messages || []);
            if (A.msgs.length > MAX_CLIENT_MSGS) A.msgs = A.msgs.slice(-MAX_CLIENT_MSGS);
            if (res.more && round < 5) return fetchMore(round + 1);
          });
        }
        return fetchMore(0);
      });
    },
    renderList: function (d) {
      var agents = (d && d.agents) || [];
      var q = A.filter.trim().toLowerCase();
      var list = agents.filter(function (a) { return (!A.activeOnly || a.active) && (!q || (String(a.label) + ' ' + a.id + ' ' + (a.phase || '') + ' ' + (a.model || '')).toLowerCase().indexOf(q) >= 0); });
      $('#ag-list').innerHTML = list.length ? list.map(function (a) {
        return '<div class="agent-item' + (a.id === A.sel ? ' sel' : '') + (a.is_main ? ' main' : '') + '" data-agent="' + esc(a.id) + '" title="' + esc(a.file) + '">' +
          '<div class="row1"><span class="dot' + (a.active ? ' live' : '') + '"></span><span class="lbl">' + esc(a.is_main ? '★ ' + a.label : a.label) + '</span>' + (a.done ? '<span class="chip st-done">' + esc(t('st_done')) + '</span>' : '') + '</div>' +
          '<div class="row2"><span>' + esc(a.is_main ? t('ag_main') : (a.phase || t('ag_sub'))) + '</span><span>' + esc(a.model || '') + '</span><span>' + esc(a.id.slice(0, 8)) + '</span></div>' +
          '<div class="row2"><span>' + esc(t('n_msgs', { n: a.n_messages })) + '</span><span>' + esc(t('n_tools', { n: a.n_tool_calls })) + '</span><span>' + esc(ago(a.mtime)) + '</span></div></div>';
      }).join('') : emptyBox(agents.length ? 'ag_none_match' : 'ag_none', agents.length ? null : agNoneHint(d), { dir: esc(d && d.root) });
    },
    update: function (d) {
      var agents = (d && d.agents) || [];
      frNote('agents', d && d.updated);
      $('#ag-count').textContent = t('ag_counts', { a: d.n_active || 0, n: agents.length });
      var act = (d && d.activity) || [];
      var ah = act.length ? act.map(function (x) {
        var tl = x.tool || {};
        return '<div class="act-chip" data-agent="' + esc(x.id) + '" title="' + esc(tl.main || '') + '"><div class="who"><span class="dot live"></span>' + esc(clip(x.label, 40)) + '<span class="tool">' + esc(tl.name || '') + '</span><span class="dim mono tiny">' + esc(ago(tl.ts)) + '</span></div><div class="what">' + esc(clip(tl.desc || tl.main || '', 90)) + '</div></div>';
      }).join('') : '<div class="muted small">' + esc(t('ag_no_activity')) + '</div>';
      $('#ag-activity').innerHTML = ah;
      this.renderList(d);
      var sum = A.summary && A.summary.id === A.sel ? A.summary : agents.filter(function (a) { return a.id === A.sel; })[0];
      $('#ag-head').textContent = sum ? (sum.is_main ? '★ ' : '') + sum.label : t('ag_stream');
      $('#ag-meta').textContent = sum ? [sum.file, sum.model || '', t('n_msgs', { n: sum.n_messages }), t('n_tools', { n: sum.n_tool_calls }), sum.active ? t('ag_active') : t('ag_idle') + ' · ' + ago(sum.mtime)].filter(Boolean).join('  ·  ') : '';
      var st = $('#ag-stream');
      if (!A.sel) { st.innerHTML = emptyBox('ag_none', agNoneHint(d), { dir: esc(d && d.root) }); return; }
      var atBottom = st.scrollTop + st.clientHeight >= st.scrollHeight - 60;
      if (A.renderedFor !== A.sel || st.getAttribute('data-for') !== A.sel) {
        st.innerHTML = A.msgs.length ? A.msgs.map(msgHtml).join('') : emptyBox('ag_no_msgs', null);
        st.setAttribute('data-for', A.sel);
        A.renderedFor = A.sel;
        A.renderedSeq = A.msgs.length ? A.msgs[A.msgs.length - 1].seq : -1;
        st.scrollTop = st.scrollHeight;
        return;
      }
      var fresh = A.msgs.filter(function (m) { return m.seq > A.renderedSeq; });
      if (!fresh.length) return;
      var emp = st.querySelector(':scope > .empty');
      if (emp) emp.remove();
      st.insertAdjacentHTML('beforeend', fresh.map(msgHtml).join(''));
      A.renderedSeq = fresh[fresh.length - 1].seq;
      var nodes = st.children;
      while (nodes.length > MAX_CLIENT_MSGS) st.removeChild(nodes[0]);
      if (A.follow && atBottom) st.scrollTop = st.scrollHeight;
    }
  };

  // ------------------------------------------------------------------ Session (mirror + continue the local orchestrator session)
  // Data: GET /api/session (status, usage, listening), GET /api/session/stream?after=<cursor> (transcript records + inbox),
  // POST /api/session/send (dashboard -> state/session_inbox.jsonl). See README §17.
  var SS_MODELS = [['fable-5.1', 'ss_m_fable', 'Fable 5.1'], ['opus-5.5', 'ss_m_opus', 'Opus 5.5'], ['sonnet-5.5', 'ss_m_sonnet', 'Sonnet 5.5'], ['haiku-5.5', 'ss_m_haiku', 'Haiku 5.5']];
  var SS_EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
  var SS_MAX = 900, SS_FIRST = 150, SS_EARLIER = 150;
  var S = {
    info: null, infoErr: null, streamErr: null, sessId: null,
    cursor: -1, msgs: [], inbox: [], firstSeq: null, latestSeq: null,
    showThink: LS.get('an_sess_think', false) === true,
    model: LS.get('an_sess_model', 'fable-5.1'), effort: LS.get('an_sess_effort', 'max'),
    draft: LS.get('an_sess_draft', ''), pending: [], tmpN: 0, sending: false, sendErr: null,
    open: {}, mdc: {}, feedEl: null, feedHtml: '', unseen: 0, seenSeq: -1, seenInbox: 0, prepend: false, earlierBusy: false, rcArm: 0,
    gen: 0, streamId: null, ro: null
  };
  var SS_SEND_MAX_BYTES = 32768;   // server body limit (UTF-8 JSON)
  var SS_ERR_CODES = ['rate_limited', 'too_large', 'text_too_long', 'empty_text', 'bad_host', 'no_header', 'bad_content_type', 'bad_json', 'bad_model', 'bad_effort', 'bad_kind', 'bad_text', 'bad_control', 'bad_value'];
  /** forget the mirrored transcript (session switch, rewritten file, stale cursor); in-flight stream responses are dropped via `gen` */
  function ssReset() {
    S.gen++; S.cursor = -1; S.msgs = []; S.mdc = {}; S.open = {}; S.feedEl = null;
    S.firstSeq = null; S.latestSeq = null; S.unseen = 0; S.seenSeq = -1;
  }
  if (!SS_MODELS.some(function (m) { return m[0] === S.model; })) S.model = 'fable-5.1';
  if (SS_EFFORTS.indexOf(S.effort) < 0) S.effort = 'max';
  if (typeof S.draft !== 'string') S.draft = '';

  function ssModelName(s) {
    var v = String(s || '').toLowerCase().replace(/^claude-/, '').replace(/\[[^\]]*\]$/, '');
    var m = v.match(/^(fable|opus|sonnet|haiku)[-_ ]?(\d+)(?:[-_.](\d+))?/);
    if (!m) return s ? String(s) : '—';
    return m[1].charAt(0).toUpperCase() + m[1].slice(1) + ' ' + m[2] + (m[3] !== undefined ? '.' + m[3] : '');
  }
  function ssTok(n) {
    if (!isNum(n)) return '—';
    var a = Math.abs(n);
    if (a >= 1e6) return (n / 1e6).toFixed(a >= 1e8 ? 0 : 2) + 'M';
    if (a >= 1e3) return (n / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'k';
    return String(Math.round(n));
  }
  function ssExact(n) { return isNum(n) ? Math.round(n).toLocaleString('en-US') : ''; }
  function ssOn(v) { return v === true || /^(on|true|enabled|active|connected)$/i.test(String(v === undefined || v === null ? '' : v)); }
  function ssOnOff(v) { return v === undefined || v === null || v === '' ? 'unknown' : (ssOn(v) ? 'on' : 'off'); }
  function ssTime(x) {
    var d = toDate(x);
    if (!d) return '';
    var n = new Date();
    return fmtTime(d, !(d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate()));
  }
  function ssMs(x) { var d = toDate(x); return d ? d.getTime() : null; }
  function ssMeterCls(p) { return !isNum(p) ? '' : p >= 90 ? 'sota' : p >= 70 ? 'amber' : ''; }
  function ssMeter(pct, marker) {
    var p = isNum(pct) ? Math.max(0, Math.min(100, pct)) : 0;
    return '<div class="bar ss-meter ' + ssMeterCls(pct) + '"><i style="width:' + p.toFixed(1) + '%"></i>' +
      (isNum(marker) ? '<b class="ss-mark" style="left:' + Math.max(0, Math.min(100, marker)).toFixed(1) + '%"></b>' : '') + '</div>';
  }
  function ssWinLabel(l) {
    var s = String(l || '');
    if (/5[\s-]*h(ou)?r?/i.test(s)) return t('ss_win_5h');
    if (/week/i.test(s) && /all/i.test(s)) return t('ss_win_week_all');
    if (/week/i.test(s)) { var m = s.match(/[·:\-]\s*([^·:\-]+)$/); return t('ss_win_week_model', { m: m ? m[1].trim() : s }); }
    return s || '—';
  }
  function ssCatName(n) {
    var k = 'ss_cat_' + String(n || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
    return has(k) ? t(k) : String(n || '—');
  }
  function ssInboxState(m) {
    if (m.state === 'delivered' || m.state === 'read' || m.state === 'replied') return m.state;
    var ack = (S.info && S.info.ack) || {}, id = String(m.id);
    if (ack.replied && ack.replied[id]) return 'replied';
    if ((ack.read && ack.read[id]) || (isNum(ack.last_read_id) && isNum(m.id) && m.id <= ack.last_read_id)) return 'read';
    return 'delivered';
  }
  var SYS_RE = /^\s*(<(task-notification|system-reminder|command-name|command-message|command-args|local-command-stdout|local-command-stderr|local-command-caveat|bash-input|bash-stdout|bash-stderr|user-prompt-submit-hook)\b|Caveat: |\[Request interrupted)/;

  /** flatten transcript records into display rows; tool results attach to their tool_use */
  function ssTranscriptRows() {
    var rows = [], res = {};
    S.msgs.forEach(function (m) { (m.blocks || []).forEach(function (b) { if (b && b.t === 'tool_result' && b.tool_use_id) res[String(b.tool_use_id)] = b; }); });
    S.msgs.forEach(function (m) {
      var role = m.role || 'assistant';
      (m.blocks || []).forEach(function (b, bi) {
        if (!b) return;
        var key = m.seq + ':' + bi, txt = String(b.text === undefined || b.text === null ? '' : b.text);
        if (b.t === 'text' && role === 'user') rows.push({ k: m.meta || SYS_RE.test(txt) ? 'sys' : 'user', ts: m.ts, seq: m.seq, text: txt, key: key, tag: m.meta === 'compact' ? 'compact-summary' : m.meta ? 'meta' : '' });
        else if (b.t === 'text') rows.push({ k: 'asst', ts: m.ts, seq: m.seq, text: txt, key: key });
        else if (b.t === 'tool_use') rows.push({ k: 'tool', ts: m.ts, seq: m.seq, b: b, res: res[String(b.id)], key: String(b.id || key) });
        else if (b.t === 'thinking' && S.showThink) rows.push({ k: 'think', ts: m.ts, seq: m.seq, text: txt, key: key });
      });
    });
    return rows;
  }
  function ssInboxRows() {
    var seen = {}, rows = [];
    (S.inbox || []).forEach(function (m) {
      if (!m || typeof m !== 'object') return;
      seen[String(m.id)] = 1;
      rows.push({ k: m.kind === 'control' ? 'ctl' : 'dash', ts: m.ts, m: m, st: ssInboxState(m), key: 'i' + m.id });
    });
    S.pending = S.pending.filter(function (p) { return p.id === undefined || p.id === null || !seen[String(p.id)]; });
    S.pending.forEach(function (p) { rows.push({ k: p.kind === 'control' ? 'ctl' : 'dash', ts: p.ts, m: p, st: p.st, key: 'p' + p.tmp, pending: true }); });
    return rows;
  }
  /** chronological merge (inbox first on ties), then collapse runs of consecutive tool chips */
  function ssRows() {
    var a = ssTranscriptRows(), b = ssInboxRows(), out = [], i = 0, j = 0, lastTs = null;
    b.sort(function (x, y) { return (ssMs(x.ts) || 9e15) - (ssMs(y.ts) || 9e15); });
    while (i < a.length || j < b.length) {
      var ta = i < a.length ? (ssMs(a[i].ts) || lastTs || 0) : null;
      var tb = j < b.length ? ssMs(b[j].ts) : null;
      if (i < a.length && ta !== null) lastTs = ta;
      if (j < b.length && (i >= a.length || (tb !== null && tb <= ta))) out.push(b[j++]);
      else if (i < a.length) out.push(a[i++]);
      else out.push(b[j++]);
    }
    var grouped = [];
    out.forEach(function (r) {
      var last = grouped[grouped.length - 1];
      if (r.k === 'tool' && last && last.k === 'tool') grouped[grouped.length - 1] = { k: 'run', key: last.key, items: [last, r] };
      else if (r.k === 'tool' && last && last.k === 'run') last.items.push(r);
      else grouped.push(r);
    });
    return grouped;
  }
  function ssToolLine(b) {
    var i = b.input || {};
    return String(i.desc || i.main || '').replace(/\s+/g, ' ');
  }
  function ssToolHtml(r) {
    var b = r.b, k = 't:' + r.key, open = !!S.open[k], res = r.res;
    var glyph = !res ? '<span class="ss-tg wait" title="' + esc(t('ss_tool_wait')) + '">…</span>' : res.is_error ? '<span class="ss-tg err">✗</span>' : '<span class="ss-tg ok">✓</span>';
    var h = '<div class="ss-tool' + (open ? ' open' : '') + '"><button type="button" class="ss-chip" data-ss-o="' + esc(k) + '" aria-expanded="' + open + '">' +
      '<span class="ss-ti">🔧</span><span class="ss-tn">' + esc(b.name || '?') + '</span><span class="ss-td">' + esc(clip(ssToolLine(b), 160)) + '</span>' + glyph + '</button>';
    if (open) h += '<div class="ss-tool-body">' + toolCard(b) + (res ? resultBlock(res) : '<div class="dim small">' + esc(t('ss_tool_wait')) + '</div>') + '</div>';
    return h + '</div>';
  }
  function ssStateGlyph(st, p) {
    return '<span class="ss-st st-' + esc(st) + '"' + (p && p.err ? ' title="' + esc(p.err) + '"' : '') + '>' + esc(tk('ss_st_', st)) + '</span>';
  }
  function ssLongText(text, key) {
    if (text.length <= 1500) return '<div class="ss-text">' + esc(text) + '</div>';
    var k = 'x:' + key, open = !!S.open[k];
    return '<div class="ss-text">' + esc(open ? text : text.slice(0, 600) + '…') + '</div><button type="button" class="linkbtn" data-ss-o="' + esc(k) + '">' +
      esc(open ? t('collapse') : t('expand')) + ' · ' + esc(t('n_chars', { n: text.length })) + '</button>';
  }
  function ssRowHtml(r) {
    if (r.k === 'user') {
      return '<div class="ss-row ss-u"><div class="ss-bubble"><div class="ss-meta"><span>' + esc(t('role_user')) + '</span><span class="chip">' + esc(t('ss_badge_local')) + '</span><span class="mono">' + esc(ssTime(r.ts)) + '</span></div>' + ssLongText(r.text, r.key) + '</div></div>';
    }
    if (r.k === 'dash') {
      var m = r.m, deleg = m.model && m.model !== 'fable-5.1';
      return '<div class="ss-row ss-u"><div class="ss-bubble ss-dash' + (r.st === 'failed' ? ' failed' : '') + '"><div class="ss-meta"><span class="chip ss-badge">' + esc(t('ss_badge_dash')) + '</span>' +
        (deleg ? '<span class="chip">' + esc(t('ss_delegate_to', { m: ssModelName(m.model), e: m.effort || '—' })) + '</span>' : '') +
        '<span class="mono">' + esc(ssTime(m.ts)) + '</span>' + (isNum(m.id) ? '<span class="dim mono">#' + esc(m.id) + '</span>' : '') + '</div>' +
        ssLongText(String(m.text || ''), r.key) + '<div class="ss-foot">' + ssStateGlyph(r.st, r.pending ? m : null) +
        (r.pending && r.st === 'failed' ? '<button type="button" class="linkbtn" data-ss-dismiss="' + esc(m.tmp) + '">' + esc(t('ss_dismiss')) + '</button>' : '') + '</div></div></div>';
    }
    if (r.k === 'ctl') {
      var c = r.m;
      return '<div class="ss-row ss-ctl"><span class="chip ss-badge">' + esc(t('ss_badge_dash')) + '</span><span>' + esc(t('ss_ctl_rc', { v: ssOn(c.value) ? t('ss_v_on') : t('ss_v_off') })) + '</span>' +
        '<span class="mono dim">' + esc(ssTime(c.ts)) + '</span>' + ssStateGlyph(r.st, r.pending ? c : null) +
        (r.pending && r.st === 'failed' ? '<button type="button" class="linkbtn" data-ss-dismiss="' + esc(c.tmp) + '">' + esc(t('ss_dismiss')) + '</button>' : '') + '</div>';
    }
    if (r.k === 'asst') {
      var h = S.mdc[r.key];
      if (h === undefined) { h = md(r.text); S.mdc[r.key] = h; }
      return '<div class="ss-row ss-a"><div class="ss-meta"><span class="role r-assistant">' + esc(t('role_assistant')) + '</span><span class="mono">' + esc(ssTime(r.ts)) + '</span></div>' + h + '</div>';
    }
    if (r.k === 'think') {
      return '<div class="ss-row ss-think"><div class="ss-meta"><span>' + esc(t('ss_think')) + '</span><span class="dim">' + esc(t('n_chars', { n: r.text.length })) + '</span><span class="mono dim">' + esc(ssTime(r.ts)) + '</span></div><div class="plain">' + esc(r.text) + '</div></div>';
    }
    if (r.k === 'sys') {
      var ks = 'x:' + r.key, so = !!S.open[ks], tag = r.tag || (r.text.match(/^\s*<([a-z-]+)/) || [])[1] || '';
      return '<div class="ss-row ss-sys"><button type="button" class="linkbtn ss-sysb" data-ss-o="' + esc(ks) + '" aria-expanded="' + so + '">' + (so ? '▾ ' : '▸ ') + esc(t('ss_sys')) + (tag ? ' · <span class="mono">' + esc(tag) + '</span>' : '') +
        ' <span class="mono dim">' + esc(ssTime(r.ts)) + '</span></button>' + (so ? '<pre class="ss-syspre">' + esc(r.text) + '</pre>' : '') + '</div>';
    }
    if (r.k === 'tool') return '<div class="ss-row ss-tools">' + ssToolHtml(r) + '</div>';
    if (r.k === 'run') {
      var kr = 'r:' + r.key, ro = !!S.open[kr], lastI = r.items[r.items.length - 1];
      var errs = r.items.filter(function (x) { return x.res && x.res.is_error; }).length;
      return '<div class="ss-row ss-tools ss-run' + (ro ? ' open' : '') + '"><button type="button" class="ss-runh" data-ss-o="' + esc(kr) + '" aria-expanded="' + ro + '">' +
        '<span class="ss-car">' + (ro ? '▾' : '▸') + '</span><span class="ss-ti">🔧</span><span class="ss-rn">' + esc(t('ss_tool_runs', { n: r.items.length })) + '</span>' +
        (errs ? '<span class="ss-tg err">✗ ' + errs + '</span>' : '') +
        '<span class="ss-td">' + esc(t('ss_tool_last', { x: (lastI.b.name || '?') + ' · ' + clip(ssToolLine(lastI.b), 120) })) + '</span><span class="mono dim ss-rt">' + esc(ssTime(lastI.ts)) + '</span></button>' +
        (ro ? '<div class="ss-run-body">' + r.items.map(ssToolHtml).join('') + '</div>' : '') + '</div>';
    }
    return '';
  }
  function ssAtBottom(el) { return el.scrollTop + el.clientHeight >= el.scrollHeight - 48; }
  function ssRenderFeed(force) {
    var el = $('#ss-feed');
    if (!el) return;
    var fresh = S.feedEl !== el;
    var rows = ssRows(), h;
    if (!rows.length) {
      h = S.streamErr ? emptyBox('ss_stream_err', 'ss_stream_err_hint') : (S.cursor < 0 && !S.info && !S.infoErr ? emptyBox('ss_loading', null) : emptyBox('ss_no_msgs', S.info && S.info.transcripts_set === false ? 'ag_none_hint_unset' : null));
    } else {
      var top = '';
      var oldest = S.msgs.length ? S.msgs[0].seq : null;
      if (isNum(S.firstSeq) && isNum(oldest)) {
        top = oldest > S.firstSeq ? '<div class="ss-earlier"><button type="button" class="btn tag" data-ss-earlier="1"' + (S.earlierBusy ? ' disabled' : '') + '>↑ ' + esc(t('ss_earlier')) + '</button></div>'
          : '<div class="ss-earlier dim tiny">' + esc(t('ss_window_start')) + '</div>';
      }
      h = top + rows.map(ssRowHtml).join('');
    }
    if (!fresh && !force && h === S.feedHtml) return;
    var atB = fresh || ssAtBottom(el), oldH = el.scrollHeight, oldTop = el.scrollTop;
    el.innerHTML = h;
    S.feedHtml = h;
    S.feedEl = el;
    var wasPrepend = S.prepend;
    if (wasPrepend) el.scrollTop = oldTop + (el.scrollHeight - oldH);
    else if (atB) { el.scrollTop = el.scrollHeight; S.unseen = 0; }
    var maxSeq = S.seenSeq, maxIn = S.seenInbox, nNew = 0;
    rows.forEach(function (r) {
      (r.items || [r]).forEach(function (x) {
        if (x.pending) return;                         // the viewer's own optimistic bubble
        if (isNum(x.seq)) { if (x.seq > S.seenSeq) nNew++; if (x.seq > maxSeq) maxSeq = x.seq; }
        else if (x.m && isNum(x.m.id)) { if (x.m.id > S.seenInbox) nNew++; if (x.m.id > maxIn) maxIn = x.m.id; }
      });
    });
    if (!wasPrepend && !atB) { el.scrollTop = oldTop; if (S.seenSeq >= 0 || S.seenInbox > 0) S.unseen += nNew; }
    S.seenSeq = maxSeq; S.seenInbox = maxIn;
    S.prepend = false;
    ssPill();
  }
  function ssPill() {
    var p = $('#ss-pill');
    if (!p) return;
    p.hidden = !S.unseen;
    p.textContent = S.unseen > 1 ? t('ss_new_n', { n: S.unseen }) : t('ss_new_msgs');
  }
  function ssFetch(round) {
    var first = S.cursor < 0, gen = S.gen;
    var url = '/api/session/stream?limit=' + (first ? SS_FIRST : 200) + (first ? '' : '&after=' + enc(S.cursor));
    return api(url).then(function (r) {
      if (gen !== S.gen) return;                       // issued before a reset: its cursor belongs to the old transcript
      if (!r || r.ok !== true || !Array.isArray(r.messages)) { S.streamErr = (r && (r.error || r.detail)) || 'bad response'; return; }
      S.streamErr = null;
      var switched = !!(S.streamId && r.id && r.id !== S.streamId);
      var behind = !first && isNum(r.latest_seq) && r.latest_seq < S.cursor;
      if (switched || (!first && (r.gap || r.reset || behind))) { ssReset(); S.streamId = r.id || null; if (round < 3) return ssFetch(round + 1); return; }
      if (r.id) S.streamId = r.id;
      var add = first ? r.messages : r.messages.filter(function (m) { return isNum(m.seq) && m.seq > S.cursor; });
      if (first) { S.msgs = []; S.mdc = {}; }
      Array.prototype.push.apply(S.msgs, add);
      var last = S.msgs.length ? S.msgs[S.msgs.length - 1].seq : null;
      S.cursor = isNum(r.cursor) ? r.cursor : (isNum(last) ? last : (isNum(r.latest_seq) ? r.latest_seq : 0));
      if (isNum(r.first_seq)) S.firstSeq = r.first_seq;
      if (isNum(r.latest_seq)) S.latestSeq = r.latest_seq;
      if (r.more_before !== undefined) S.hasBefore = true;
      if (Array.isArray(r.inbox)) S.inbox = r.inbox;
      if (S.msgs.length > SS_MAX) {
        S.msgs = S.msgs.slice(-SS_MAX);
        var keep = {};
        S.msgs.forEach(function (m) { (m.blocks || []).forEach(function (b, bi) { keep[m.seq + ':' + bi] = 1; }); });
        Object.keys(S.mdc).forEach(function (k) { if (!keep[k]) delete S.mdc[k]; });
      }
      if (r.more && round < 5) return ssFetch(round + 1);
    }, function (e) { S.streamErr = String((e && e.message) || e || 'error'); });
  }
  function ssEarlier() {
    var oldest = S.msgs.length ? S.msgs[0].seq : null;
    if (!isNum(oldest) || S.earlierBusy) return;
    // servers that report `more_before` accept ?before=<seq>; otherwise page with ?after= (same window)
    var after = Math.max(0, oldest - SS_EARLIER - 1, isNum(S.firstSeq) ? S.firstSeq - 1 : 0);
    var url = S.hasBefore ? '/api/session/stream?before=' + enc(oldest) + '&limit=' + SS_EARLIER : '/api/session/stream?after=' + enc(after) + '&limit=' + SS_EARLIER;
    S.earlierBusy = true;
    ssRenderFeed(true);
    var gen = S.gen;
    api(url).then(function (r) {
      if (gen !== S.gen || (S.streamId && r && r.id && r.id !== S.streamId)) return;
      if (!r || r.ok !== true || !Array.isArray(r.messages)) { toast(t('ss_stream_err')); return; }
      var add = r.messages.filter(function (m) { return isNum(m.seq) && m.seq < (S.msgs.length ? S.msgs[0].seq : Infinity); });
      if (isNum(r.first_seq)) S.firstSeq = r.first_seq;
      if (add.length) { S.msgs = add.concat(S.msgs); S.prepend = true; }
      else if (isNum(S.firstSeq)) S.firstSeq = Math.min(S.firstSeq, oldest);
    }, function () { toast(t('ss_stream_err')); }).then(function () { S.earlierBusy = false; ssRenderFeed(true); });
  }
  function ssAutosize(ta) {
    if (!ta) return;
    var cs = window.getComputedStyle(ta), lh = parseFloat(cs.lineHeight) || 20;
    var pad = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0) + (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
    ta.style.height = 'auto';
    ta.style.height = Math.max(2 * lh + pad, Math.min(8 * lh + pad, ta.scrollHeight + (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0))) + 'px';
  }
  function ssBytes(s) {
    if (window.TextEncoder) return new TextEncoder().encode(s).length;
    return unescape(encodeURIComponent(s)).length;
  }
  function ssSetErr(msg) {
    S.sendErr = msg || null;
    var e = $('#ss-err');
    if (!e) return;
    e.textContent = S.sendErr || '';
    e.hidden = !S.sendErr;
  }
  function ssSend(kind) {
    if (S.sending) return;
    var ta = $('#ss-input'), text = kind === 'control' ? '' : String(ta ? ta.value : '').trim();
    if (kind !== 'control') {
      if (!text) { ssSetErr(t('ss_err_empty')); if (ta) ta.focus(); return; }
      if (text.length > 20000) { ssSetErr(t('ss_err_long', { n: text.length })); return; }
    }
    var st = (S.info && S.info.status) || {};
    var body = { kind: kind, text: text, model: S.model, effort: S.effort };
    if (kind === 'control') { body.control = 'remote_control'; body.value = !ssOn(st.remote_control); }
    var nBytes = ssBytes(JSON.stringify(body));
    if (nBytes > SS_SEND_MAX_BYTES) { ssSetErr(t('ss_err_bytes', { n: nBytes, max: SS_SEND_MAX_BYTES })); return; }
    var p = { tmp: ++S.tmpN, ts: new Date().toISOString(), kind: kind, text: text, model: S.model, effort: S.effort, value: body.value, st: 'sending' };
    S.pending.push(p);
    if (kind !== 'control' && ta) { ta.value = ''; S.draft = ''; LS.set('an_sess_draft', ''); ssAutosize(ta); }
    ssSetErr(null);
    S.sending = true;
    ssComposerState();
    var fe = $('#ss-feed');
    if (fe) fe.scrollTop = fe.scrollHeight;
    ssRenderFeed(true);
    var ctl = window.AbortController ? new AbortController() : null;
    var to = setTimeout(function () { if (ctl) ctl.abort(); }, 12000);
    function fail(msg) {
      p.st = 'failed'; p.err = String(msg || 'error');
      if (kind !== 'control' && ta && !ta.value) { ta.value = text; S.draft = text; LS.set('an_sess_draft', text); ssAutosize(ta); }
      ssSetErr(t('ss_send_failed', { e: p.err }));
    }
    fetch('/api/session/send', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin', signal: ctl ? ctl.signal : undefined,
      headers: { 'Content-Type': 'application/json', 'X-AN-Session': '1' }, body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (d && d.ok === true && r.ok) return d;
        var code = d && typeof d.code === 'string' ? d.code : '';
        if (SS_ERR_CODES.indexOf(code) >= 0) return { ok: false, error: tk('ss_err_c_', code) };
        return { ok: false, error: (d && (d.error || (typeof d.detail === 'string' ? d.detail : ''))) || 'HTTP ' + r.status };
      });
    }).then(function (d) {
      if (d.ok === true) { p.st = 'delivered'; if (d.id !== undefined) p.id = d.id; if (d.ts) p.ts = d.ts; toast(t('ss_sent', { id: d.id !== undefined ? d.id : '?' })); }
      else fail(d.error);
    }, function (e) { fail(e && e.name === 'AbortError' ? 'timeout' : (e && e.message) || e); }).then(function () {
      clearTimeout(to);
      S.sending = false;
      ssComposerState();
      ssRenderFeed(true);
      if (p.st === 'delivered') refreshNow();
    });
  }
  function ssComposerState() {
    var b = $('#ss-send');
    if (b) { b.disabled = S.sending; b.textContent = S.sending ? t('ss_st_sending') : t('ss_send'); }
    var deleg = S.model !== 'fable-5.1', lbl = $('#ss-effort-lbl');
    if (lbl) lbl.textContent = deleg ? t('ss_effort_deleg') : t('ss_effort');
    var info = S.info || {}, st = info.status || {};
    var dh = $('#ss-deleg');
    if (dh) {
      var mm = SS_MODELS.filter(function (m) { return m[0] === S.model; })[0];
      dh.textContent = deleg ? t('ss_deleg_hint', { m: mm ? mm[2] : S.model }) : t('ss_self_hint');
    }
    var self = $('#ss-self');
    if (self) {
      var mdl = st.model || (info.session && info.session.model_seen) || (info.usage && info.usage.last_model);
      var note = bi(st, 'notes');
      self.textContent = t('ss_self_model', { m: mdl ? ssModelName(mdl) : '—', e: st.effort || '—' }) + ' — ' + (note || t('ss_self_switch'));
    }
    var nl = $('#ss-note');
    if (nl) nl.hidden = !(S.info && S.info.listening === false);
    var rc = $('#ss-rc');
    if (rc) {
      var armed = S.rcArm && Date.now() - S.rcArm < 5000;
      rc.textContent = armed ? t('ss_rc_confirm') : (ssOn(st.remote_control) ? t('ss_rc_off_btn') : t('ss_rc_on_btn'));
      rc.classList.toggle('on', !!armed);
      rc.disabled = S.sending;
    }
  }
  function ssStatusHtml() {
    var info = S.info;
    if (!info) return S.infoErr ? emptyBox('ss_err_title', 'ss_err_hint') : emptyBox('ss_loading', null);
    var st = info.status && typeof info.status === 'object' ? info.status : {}, se = info.session || {}, us = info.usage || {};
    var hasSt = Object.keys(st).length > 0;
    var mdl = st.model || se.model_seen || us.last_model;
    var fm = st.fast_mode, fState = fm && typeof fm === 'object' ? fm.state : fm;
    var badges = [
      '<span class="chip st-running mono" title="' + esc(mdl || '') + '">' + esc(mdl ? ssModelName(mdl) : '—') + '</span>',
      st.effort ? '<span class="chip">' + esc(t('ss_effort_badge', { e: st.effort })) + '</span>' : '',
      st.permission_mode ? '<span class="chip">' + esc(t('ss_perm_badge', { p: tk('ss_perm_', st.permission_mode) })) + '</span>' : '',
      fm !== undefined ? '<span class="chip"' + (fm && fm.disabled_reason ? ' title="' + esc(fm.disabled_reason) + '"' : '') + '>' + esc(t('ss_fast_badge', { s: tk('ss_onoff_', ssOnOff(fState)) })) + '</span>' : '',
      st.remote_control !== undefined ? '<span class="chip' + (ssOn(st.remote_control) ? ' st-done' : '') + '">' + esc(t('ss_rc_badge', { s: tk('ss_onoff_', ssOnOff(st.remote_control)) })) + '</span>' : ''
    ].join('');
    var ccd = st.ccd_session_id ? String(st.ccd_session_id) : '', tid = st.transcript_session_id || se.id || '';
    var ids = (ccd ? '<span title="' + esc(ccd) + '">' + esc(t('ss_ccd')) + ' <span class="mono">' + esc(clip(ccd, 14)) + '</span></span>' : '') +
      (tid ? '<span title="' + esc(tid + (se.file ? '\n' + se.file : '')) + '">' + esc(t('ss_transcript')) + ' <span class="mono">' + esc(String(tid).slice(0, 8)) + '</span></span>' : '');
    var stAge = isNum(info.status_age_s) ? info.status_age_s : (st.updated && toDate(st.updated) ? (Date.now() - toDate(st.updated).getTime()) / 1000 : null);
    var left = '<div class="ss-id"><div class="ss-ttl">' + esc(st.title || se.title || '—') + '</div><div class="ss-ids muted small">' + ids + '</div>' +
      '<div class="chips ss-badges">' + badges + '</div>' +
      '<div class="ss-act small"><span class="dot' + (se.active ? ' live' : '') + '"></span>' + esc(t('ss_last_activity', { t: se.last_ts ? ago(se.last_ts) : '—' })) +
      (se.active ? ' · <span class="pos">' + esc(t('ss_active')) + '</span>' : '') + '</div>' +
      (isNum(se.n_messages) ? '<div class="muted small">' + esc(t('ss_counts', { n: se.n_messages, k: isNum(se.n_tool_calls) ? se.n_tool_calls : 0 })) + '</div>' : '') +
      (hasSt ? '<div class="small ' + (isNum(stAge) && stAge > 1800 ? 'ss-stale' : 'muted') + '" title="' + esc(fmtTime(st.updated)) + '">' + esc(t('ss_as_of', { t: ssTime(st.updated) || '—' })) + (st.updated ? ' · ' + esc(ago(st.updated)) : '') +
        (st.author ? ' <span class="chip mono">' + esc(st.author) + '</span>' : '') + '</div>' : '<div class="small ss-stale">' + esc(t('ss_status_none')) + '</div>') + '</div>';
    // (a) plan windows
    var plan = st.plan && typeof st.plan === 'object' ? st.plan : {}, wins = (Array.isArray(plan.windows) ? plan.windows : []).filter(function (w) { return w && typeof w === 'object'; });
    var pa = '<div class="ss-box"><div class="ss-bh">' + esc(plan.name ? t('ss_plan', { p: plan.name }) : t('ss_plan_any')) + '</div>' + (wins.length ? wins.map(function (w) {
      var u = isNum(w.percent_used) ? w.percent_used : null, rd = toDate(w.resets_at), reset;
      if (!rd) reset = t('ss_reset_unknown');
      else if (rd.getTime() > Date.now()) reset = t('ss_resets_in', { d: fmtDur((rd.getTime() - Date.now()) / 1000) });
      else reset = t('ss_reset_passed');
      return '<div class="ss-win"><div class="ss-wl"><span>' + esc(ssWinLabel(w.label)) + '</span><span class="mono ' + (u >= 90 ? 'ss-hot' : u >= 70 ? 'ss-warm' : '') + '">' + (isNum(u) ? esc(fmt(u, 0)) + '%' : '—') + '</span></div>' + ssMeter(u) +
        '<div class="ss-wsub muted tiny" title="' + esc(rd ? fmtTime(rd) : '') + '">' + esc(t('ss_win_line', { u: isNum(u) ? fmt(u, 0) : '—', r: isNum(u) ? fmt(Math.max(0, 100 - u), 0) : '—', reset: reset })) + '</div></div>';
    }).join('') : '<div class="muted small">' + esc(t('ss_plan_none')) + '</div>') + '</div>';
    // (b) context window
    var cx = st.context && typeof st.context === 'object' ? st.context : {};
    var cu = isNum(cx.tokens_used) ? cx.tokens_used : null, cw = isNum(cx.window) ? cx.window : null;
    var cp = isNum(cx.percent_used) ? cx.percent_used : (isNum(cu) && cw ? cu / cw * 100 : null);
    var ac = isNum(cx.autocompact_at_percent) ? cx.autocompact_at_percent : 97;
    var cats = Array.isArray(cx.categories) ? cx.categories : [];
    var pb = '<div class="ss-box"><div class="ss-bh">' + esc(t('ss_ctx')) + '</div>' + (isNum(cu) || isNum(cp) ? '<div class="ss-big mono" title="' + esc(ssExact(cu)) + '">' +
      esc(t('ss_ctx_line', { u: ssTok(cu), w: ssTok(cw), p: isNum(cp) ? fmt(cp, 0) : '—' })) + '</div>' + ssMeter(cp, ac) +
      '<div class="muted tiny ss-acm">' + esc(t('ss_autocompact', { p: fmt(ac, 0) })) + '</div>' +
      (cats.length ? '<div class="ss-cats">' + cats.slice(0, 10).map(function (c) {
        return '<span><span class="muted">' + esc(ssCatName(c && c.name)) + '</span> <span class="mono">' + esc(ssTok(c && c.tokens)) + '</span></span>';
      }).join('') + '</div>' : '') : '<div class="muted small">' + esc(t('ss_ctx_none')) + '</div>') + '</div>';
    // (c) turn budget
    var pc = '<div class="ss-box"><div class="ss-bh">' + esc(t('ss_budget')) + '</div><div class="ss-big mono" title="' + esc(ssExact(st.turn_budget_left)) + '">' + esc(ssTok(st.turn_budget_left)) +
      (isNum(st.turn_budget_left) ? '<span class="unit muted"> ' + esc(t('ss_tokens_unit')) + '</span>' : '') + '</div>' +
      (hasSt ? '<div class="muted tiny">' + esc(t('ss_as_of', { t: ssTime(st.updated) || '—' })) + '</div>' : '') + '</div>';
    // (d) live transcript counters
    function cell(lbl, val, sub, title) { return '<div class="ss-cell"' + (title ? ' title="' + esc(title) + '"' : '') + '><div class="lbl">' + esc(lbl) + '</div><div class="v mono">' + esc(val) + '</div>' + (sub ? '<div class="muted tiny">' + esc(sub) + '</div>' : '') + '</div>'; }
    var pd = '<div class="ss-box ss-live"><div class="ss-bh">' + esc(t('ss_live')) + '</div><div class="ss-cells">' +
      cell(t('ss_c_turns'), isNum(us.turns) ? String(us.turns) : '—') +
      cell(t('ss_c_asst'), isNum(us.assistant_messages) ? String(us.assistant_messages) : '—') +
      cell(t('ss_c_out'), ssTok(us.output_tokens_total), isNum(us.thinking_tokens_total) ? t('ss_c_think', { n: ssTok(us.thinking_tokens_total) }) : '', ssExact(us.output_tokens_total)) +
      cell(t('ss_c_ctx'), ssTok(us.last_context_tokens), t('ss_c_ctx_sub'), ssExact(us.last_context_tokens)) +
      cell(t('ss_c_cache_lbl'), ssTok(us.cache_read_total), t('ss_c_cache', { w: ssTok(us.cache_creation_total) }), ssExact(us.cache_read_total)) +
      cell(t('ss_c_model'), us.last_model ? ssModelName(us.last_model) : '—', us.last_ts ? ago(us.last_ts) : '', us.last_model || '') +
      cell(t('ss_c_pending'), isNum(info.inbox_pending) ? String(info.inbox_pending) : '—') +
      '</div></div>';
    return '<div class="ss-status">' + left + '<div class="ss-tok">' + pa + pb + pc + pd + '</div></div>';
  }
  function ssListenHtml() {
    var info = S.info;
    if (!info) return '';
    var hb = isNum(info.heartbeat_age_s) ? info.heartbeat_age_s : null;
    if (info.listening === true) return '<span class="chip ss-listen on" title="' + esc(hb !== null ? t('ss_hb_age', { d: fmtDur(hb) }) : '') + '"><span class="dot live"></span>' + esc(t('ss_listening')) + '</span>';
    return '<span class="chip ss-listen off"><span class="dot"></span>' + esc(t('ss_not_listening')) + ' · ' + esc(hb !== null ? t('ss_hb_age', { d: fmtDur(hb) }) : t('ss_hb_none')) + '</span>';
  }
  VIEWS.session = {
    src: 'session',
    mount: function () {
      var quick = [['ss_q_report'], ['ss_q_queue'], ['ss_q_pause'], ['ss_q_continue']].map(function (q) {
        return '<button type="button" class="chip clickable" data-ss-q="' + esc(q[0]) + '">' + esc(t(q[0])) + '</button>';
      }).join('');
      return '<div class="grid ss-grid">' +
        '<div class="card s12 ss-card-status" data-src="session_status"><h2>' + esc(t('ss_title')) + '<span class="grow"></span><span id="ss-listen"></span></h2><div id="ss-status">' + emptyBox('ss_loading', null) + '</div></div>' +
        '<div class="card s12 ss-card-conv"><h2>' + esc(t('ss_conv')) + '<span class="tag small muted" id="ss-conv-meta"></span><span class="grow"></span>' +
        '<label class="tag small"><input type="checkbox" id="ss-think"> ' + esc(t('ss_show_think')) + '</label>' +
        '<button class="btn tag" type="button" id="ss-bottom">' + esc(t('jump_latest')) + ' ↓</button></h2>' +
        '<div class="ss-feedwrap"><div class="ss-feed" id="ss-feed" aria-live="polite">' + emptyBox('ss_loading', null) + '</div><button type="button" class="ss-pill" id="ss-pill" hidden></button></div></div>' +
        '<div class="card s12 ss-composer" id="ss-composer" data-src="none"><h2>' + esc(t('ss_composer')) + '<span class="grow"></span><span class="tag tiny dim ss-kbd">' + esc(t('ss_send_hint')) + '</span></h2>' +
        '<div class="ss-note" id="ss-note" hidden>⚠ ' + esc(t('ss_not_listening_note')) + '</div>' +
        '<textarea id="ss-input" rows="2" maxlength="20000" placeholder="' + esc(t('ss_ph')) + '" aria-label="' + esc(t('ss_ph')) + '"></textarea>' +
        '<div class="ss-quick">' + quick + '</div>' +
        '<div class="ss-ctrls"><label><span class="ss-lbl">' + esc(t('ss_target_model')) + '</span><select id="ss-model">' +
        SS_MODELS.map(function (m) { return '<option value="' + esc(m[0]) + '">' + esc(t(m[1])) + '</option>'; }).join('') + '</select></label>' +
        '<label><span class="ss-lbl" id="ss-effort-lbl">' + esc(t('ss_effort')) + '</span><select id="ss-effort">' +
        SS_EFFORTS.map(function (e) { return '<option value="' + esc(e) + '">' + esc(e) + '</option>'; }).join('') + '</select></label>' +
        '<span class="grow"></span><button class="btn ss-send" type="button" id="ss-send">' + esc(t('ss_send')) + '</button></div>' +
        '<div class="ss-err" id="ss-err" role="alert" hidden></div>' +
        '<div class="muted tiny" id="ss-deleg"></div><div class="muted tiny" id="ss-self"></div>' +
        '<div class="ss-rcrow"><button class="btn tag" type="button" id="ss-rc" title="' + esc(t('ss_rc_desc')) + '">Remote Control</button><span class="dim tiny ss-rcd">' + esc(t('ss_rc_desc')) + '</span></div>' +
        '</div></div>';
    },
    bind: function () {
      var ta = $('#ss-input'), feed = $('#ss-feed'), comp = $('#ss-composer');
      S.feedEl = null; S.feedHtml = ''; S.unseen = 0;
      if (S.ro) { S.ro.disconnect(); S.ro = null; }
      var setCompH = function () {
        var view = $('#view-session');
        if (!view || !comp.isConnected) return;
        var atB = ssAtBottom(feed), h = Math.ceil(comp.getBoundingClientRect().height);
        var top = Math.ceil(feed.getBoundingClientRect().top - feed.closest('.card').getBoundingClientRect().top);
        view.style.setProperty('--ss-comp-h', h + 'px');
        view.style.setProperty('--ss-feed-top', top + 'px');
        if (atB) feed.scrollTop = feed.scrollHeight;
      };
      if (window.ResizeObserver) { S.ro = new ResizeObserver(setCompH); S.ro.observe(comp); }
      setCompH();
      ta.value = S.draft || '';
      $('#ss-model').value = S.model;
      $('#ss-effort').value = S.effort;
      $('#ss-think').checked = S.showThink;
      ssAutosize(ta);
      ssSetErr(S.sendErr);
      ssComposerState();
      ta.addEventListener('input', function () { S.draft = ta.value; LS.set('an_sess_draft', ta.value); ssAutosize(ta); if (S.sendErr && ta.value.trim()) ssSetErr(null); });
      ta.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); ssSend('message'); }
      });
      $('#ss-send').addEventListener('click', function () { ssSend('message'); });
      $('#ss-model').addEventListener('change', function (e) { S.model = e.target.value; LS.set('an_sess_model', S.model); ssComposerState(); });
      $('#ss-effort').addEventListener('change', function (e) { S.effort = e.target.value; LS.set('an_sess_effort', S.effort); });
      $('#ss-think').addEventListener('change', function (e) { S.showThink = e.target.checked; LS.set('an_sess_think', S.showThink); ssRenderFeed(true); });
      $('#ss-bottom').addEventListener('click', function () { feed.scrollTop = feed.scrollHeight; S.unseen = 0; ssPill(); });
      $('#ss-pill').addEventListener('click', function () { feed.scrollTop = feed.scrollHeight; S.unseen = 0; ssPill(); });
      feed.addEventListener('scroll', function () { if (S.unseen && ssAtBottom(feed)) { S.unseen = 0; ssPill(); } });
      $('#ss-composer').addEventListener('click', function (e) {
        var q = e.target.closest('[data-ss-q]');
        if (!q) return;
        var ins = t(q.getAttribute('data-ss-q')), v = ta.value, a = ta.selectionStart, b = ta.selectionEnd;
        if (typeof a !== 'number' || document.activeElement !== ta) { a = b = v.length; if (v && !/\s$/.test(v)) ins = (v ? ' ' : '') + ins; }
        ta.value = v.slice(0, a) + ins + v.slice(b);
        ta.focus();
        try { ta.setSelectionRange(a + ins.length, a + ins.length); } catch (er) { /* ignore */ }
        S.draft = ta.value; LS.set('an_sess_draft', ta.value); ssAutosize(ta);
      });
      $('#ss-rc').addEventListener('click', function () {
        if (S.rcArm && Date.now() - S.rcArm < 5000) { S.rcArm = 0; ssSend('control'); return; }
        S.rcArm = Date.now();
        ssComposerState();
        setTimeout(ssComposerState, 5100);
      });
      feed.addEventListener('click', function (e) {
        var x = e.target.closest('[data-expand]');
        if (x) {
          var box = x.closest('.result'), sh = box && box.querySelector('.r-short'), fu = box && box.querySelector('.r-full');
          if (sh && fu) { var op = fu.classList.contains('hidden'); fu.classList.toggle('hidden', !op); sh.classList.toggle('hidden', op); x.textContent = op ? t('collapse') : t('expand'); }
          return;
        }
        if (e.target.closest('[data-ss-earlier]')) { ssEarlier(); return; }
        var dm = e.target.closest('[data-ss-dismiss]');
        if (dm) { var id = +dm.getAttribute('data-ss-dismiss'); S.pending = S.pending.filter(function (p) { return p.tmp !== id; }); ssRenderFeed(true); return; }
        var o = e.target.closest('[data-ss-o]');
        if (!o) return;
        var k = o.getAttribute('data-ss-o');
        if (S.open[k]) delete S.open[k]; else S.open[k] = 1;
        var top = feed.scrollTop;
        ssRenderFeed(true);
        feed.scrollTop = top;
      });
    },
    load: function () {
      var self = this;
      var p1 = api('/api/session').then(function (d) {
        if (d && d.ok === true) {
          // a session switch is detected by ssFetch from the stream's own `id` (this response may be up to 2 s older)
          var sid = d.session && (d.session.id || d.session.file);
          if (sid) S.sessId = sid;
          S.info = d; S.infoErr = null;
        } else { S.infoErr = (d && (d.error || d.detail)) || 'bad response'; }
      }, function (e) { S.infoErr = String((e && e.message) || e || 'error'); });
      return Promise.all([p1, ssFetch(0)]).then(function () { self.data = S; });
    },
    update: function () {
      var info = S.info;
      if (info) {
        var sst = info.status && typeof info.status === 'object' ? info.status : {};
        frNote('session_status', sst.updated || sst.ts);
        frNote('session', info.session && info.session.last_ts);
      }
      $('#ss-listen').innerHTML = ssListenHtml() + (S.infoErr && info ? ' <span class="chip lv-warn" title="' + esc(S.infoErr) + '">' + esc(t('ss_sync_err')) + '</span>' : '');
      var sh, se = $('#ss-status');
      try { sh = ssStatusHtml(); } catch (er) {
        if (window.console) console.warn('[an-dashboard] session status render failed', er);
        sh = emptyBox('ss_status_bad', 'ss_status_bad_hint');
      }
      if (se.getAttribute('data-h') !== sh) { se.innerHTML = sh; se.setAttribute('data-h', sh); }
      var cm = $('#ss-conv-meta'), parts = [];
      if (info && info.session && isNum(info.session.n_messages)) parts.push(t('ss_counts', { n: info.session.n_messages, k: info.session.n_tool_calls || 0 }));
      if (S.streamErr && S.msgs.length) parts.push(t('ss_sync_err'));
      cm.textContent = parts.join(' · ');
      cm.classList.toggle('ss-stale', !!(S.streamErr && S.msgs.length));
      ssRenderFeed(false);
      ssComposerState();
    }
  };

  // ------------------------------------------------------------------ Literature
  var LIT = { q: '', themes: [], venue: '', sort: LS.get('an_lit_sort', 'tier'), open: {} };
  var VENUE_COLOR = { CVPR: '#60a5fa', ICCV: '#2dd4bf', ECCV: '#22d3ee', NEURIPS: '#a78bfa', ICML: '#fbbf24', ICLR: '#34d399', AAAI: '#f472b6', ACL: '#fb923c', MICCAI: '#94a3b8' };
  function tierKey(a) {
    var s = String(a || '').toLowerCase().replace(/[\s-]+/g, '_');
    if (/best|outstanding|award/.test(s)) return 'best';
    if (/spotlight/.test(s)) return 'spotlight';
    if (/oral/.test(s)) return 'oral';
    if (/highlight/.test(s)) return 'highlight';
    if (/poster|main|accepted/.test(s)) return 'poster';
    return 'unknown';
  }
  var TIER_RANK = { best: 0, spotlight: 1, oral: 2, highlight: 3, poster: 4, unknown: 5 };
  function venueKey(v) { var s = String(v || '').toUpperCase(); var m = s.match(/CVPR|ICCV|ECCV|NEURIPS|ICML|ICLR|AAAI|ACL|MICCAI/); return m ? m[0] : s.split(/[\s(]/)[0]; }
  VIEWS.literature = {
    src: 'literature',
    mount: function () {
      return '<div class="grid"><div class="card s12"><h2>' + esc(t('lit_title')) + '<span class="grow"></span><span class="tag muted small" id="lit-stats"></span></h2>' +
        '<div class="controls"><input type="search" id="lit-q" placeholder="' + esc(t('lit_search_ph')) + '" style="min-width:16rem">' +
        '<label>' + esc(t('lit_venue')) + ' <select id="lit-venue"></select></label>' +
        '<label>' + esc(t('lit_sort')) + ' <select id="lit-sort"><option value="tier">' + esc(t('lit_sort_tier')) + '</option><option value="year">' + esc(t('lit_sort_year')) + '</option><option value="venue">' + esc(t('lit_sort_venue')) + '</option><option value="verified">' + esc(t('lit_sort_verified')) + '</option></select></label></div>' +
        '<div class="chips" id="lit-themes" style="margin-bottom:.7rem"></div><div class="tbl-wrap scroll" id="lit-table"></div></div></div>';
    },
    bind: function () {
      var self = this;
      $('#lit-q').value = LIT.q;
      $('#lit-sort').value = LIT.sort;
      $('#lit-q').addEventListener('input', function (e) { LIT.q = e.target.value; if (self.data) self.update(self.data); });
      $('#lit-venue').addEventListener('change', function (e) { LIT.venue = e.target.value; if (self.data) self.update(self.data); });
      $('#lit-sort').addEventListener('change', function (e) { LIT.sort = e.target.value; LS.set('an_lit_sort', LIT.sort); if (self.data) self.update(self.data); });
      $('#lit-themes').addEventListener('click', function (e) {
        var c = e.target.closest('[data-theme]');
        if (!c) return;
        var th = c.getAttribute('data-theme'), i = LIT.themes.indexOf(th);
        if (th === '') LIT.themes = []; else if (i >= 0) LIT.themes.splice(i, 1); else LIT.themes.push(th);
        if (self.data) self.update(self.data);
      });
      $('#lit-table').addEventListener('click', function (e) {
        if (e.target.closest('a')) return;
        var r = e.target.closest('tr.lit-row');
        if (!r) return;
        var k = r.getAttribute('data-k');
        LIT.open[k] = !LIT.open[k];
        if (self.data) self.update(self.data);
      });
    },
    load: function () { var self = this; return api('/api/literature').then(function (d) { self.data = d; }); },
    update: function (d) {
      var papers = (d && d.papers) || [];
      frNote('literature', d && d.updated);
      if (!papers.length) {
        $('#lit-table').innerHTML = emptyBox('lit_waiting', 'lit_waiting_hint');
        $('#lit-themes').innerHTML = ''; $('#lit-stats').textContent = ''; setOpts('#lit-venue', [['', t('all')]], '');
        return;
      }
      var themes = {}, venues = {};
      papers.forEach(function (p) { (Array.isArray(p.themes) ? p.themes : []).forEach(function (th) { themes[th] = (themes[th] || 0) + 1; }); var v = venueKey(p.venue); venues[v] = (venues[v] || 0) + 1; });
      var v3 = papers.filter(function (p) { return (p.verified_count || 0) >= 3; }).length;
      $('#lit-stats').textContent = t('lit_stats', { n: papers.length, v: v3 });
      setOpts('#lit-venue', [['', t('all')]].concat(Object.keys(venues).sort().map(function (v) { return [v, v + ' (' + venues[v] + ')']; })), LIT.venue);
      $('#lit-themes').innerHTML = '<span class="chip clickable' + (LIT.themes.length ? '' : ' sel') + '" data-theme="">' + esc(t('all')) + '</span>' +
        Object.keys(themes).sort(function (a, b) { return themes[b] - themes[a]; }).map(function (th) { return '<span class="chip clickable' + (LIT.themes.indexOf(th) >= 0 ? ' sel' : '') + '" data-theme="' + esc(th) + '">' + esc(th) + ' · ' + themes[th] + '</span>'; }).join('');
      var q = LIT.q.trim().toLowerCase();
      var rows = papers.map(function (p, i) { return { p: p, k: String(i) + ':' + String(p.title || '').slice(0, 40) }; }).filter(function (o) {
        var p = o.p;
        if (LIT.venue && venueKey(p.venue) !== LIT.venue) return false;
        if (LIT.themes.length && !(Array.isArray(p.themes) && LIT.themes.every(function (th) { return p.themes.indexOf(th) >= 0; }))) return false;
        if (q && [p.title, p.first_author, p.venue, p.key_idea, p.relevance_to_vs, p.transferable_component, (p.themes || []).join(' ')].join(' ').toLowerCase().indexOf(q) < 0) return false;
        return true;
      });
      rows.sort(function (a, b) {
        var pa = a.p, pb = b.p;
        if (LIT.sort === 'year') return (pb.year || 0) - (pa.year || 0);
        if (LIT.sort === 'venue') return venueKey(pa.venue).localeCompare(venueKey(pb.venue));
        if (LIT.sort === 'verified') return (pb.verified_count || 0) - (pa.verified_count || 0);
        return (TIER_RANK[tierKey(pa.award_tier)] - TIER_RANK[tierKey(pb.award_tier)]) || ((pb.year || 0) - (pa.year || 0));
      });
      var head = '<tr><th>#</th><th>' + esc(t('lit_col_title')) + '</th><th>' + esc(t('lit_col_author')) + '</th><th>' + esc(t('lit_venue')) + '</th><th>' + esc(t('lit_col_year')) + '</th><th>' + esc(t('lit_col_tier')) + '</th><th>' + esc(t('lit_col_verified')) + '</th><th>' + esc(t('lit_col_idea')) + '</th></tr>';
      var body = rows.map(function (o, i) {
        var p = o.p, vk = venueKey(p.venue), tkk = tierKey(p.award_tier), vc = Math.max(0, Math.min(3, p.verified_count || 0));
        var u = safeUrl(p.url), cu = safeUrl(p.code_url);
        var h = '<tr class="lit-row" data-k="' + esc(o.k) + '"><td class="mono dim">' + (i + 1) + '</td><td><span class="lit-title">' + esc(p.title || '—') + '</span>' +
          (u ? ' <a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">↗</a>' : '') + (cu ? ' <a class="small" href="' + esc(cu) + '" target="_blank" rel="noopener noreferrer">' + esc(t('code')) + '</a>' : '') +
          '<div class="chips" style="margin-top:.2rem">' + (Array.isArray(p.themes) ? p.themes : []).map(function (th) { return '<span class="chip tiny">' + esc(th) + '</span>'; }).join('') + '</div></td>' +
          '<td class="small">' + esc(p.first_author || '—') + '</td><td><span class="venue" style="background:' + (VENUE_COLOR[vk] || '#8296b3') + '">' + esc(p.venue || '—') + '</span></td>' +
          '<td class="mono">' + esc(p.year || '—') + '</td><td><span class="tier t-' + tkk + '">' + esc(tk('tier_', tkk)) + '</span>' + (p.award_tier && tkk !== 'unknown' ? '' : '') + '</td>' +
          '<td class="nowrap"><span class="verif">' + [0, 1, 2].map(function (j) { return '<i class="' + (j < vc ? 'on' : '') + '"></i>'; }).join('') + '</span> <span class="mono small">' + (p.verified_count || 0) + '/3</span></td>' +
          '<td class="small muted">' + esc(clip(p.key_idea || '', 140)) + '</td></tr>';
        if (LIT.open[o.k]) {
          h += '<tr class="lit-detail"><td></td><td colspan="7"><dl class="kv"><dt>' + esc(t('lit_key_idea')) + '</dt><dd>' + esc(p.key_idea || '—') + '</dd><dt>' + esc(t('lit_relevance')) + '</dt><dd>' + esc(p.relevance_to_vs || '—') + '</dd><dt>' + esc(t('lit_transfer')) + '</dt><dd>' + esc(p.transferable_component || '—') + '</dd>' +
            '<dt>' + esc(t('lit_award_raw')) + '</dt><dd>' + esc(p.award_tier || '—') + '</dd><dt>URL</dt><dd>' + (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(u) + '</a>' : '—') + '</dd><dt>' + esc(t('code')) + '</dt><dd>' + (cu ? '<a href="' + esc(cu) + '" target="_blank" rel="noopener noreferrer">' + esc(cu) + '</a>' : '—') + '</dd></dl></td></tr>';
        }
        return h;
      }).join('');
      $('#lit-table').innerHTML = rows.length ? '<table class="tbl"><thead>' + head + '</thead><tbody>' + body + '</tbody></table>' : emptyBox('lit_no_match', null);
    }
  };

  // ------------------------------------------------------------------ Paper
  var PP = { pdf: LS.get('an_pp_pdf', false) === true };
  VIEWS.paper = {
    src: 'paper',
    mount: function () {
      return '<div class="kpis" id="pp-kpis"></div><div class="kpi-asof" data-srcs="paper" hidden></div><div class="grid">' +
        '<div class="card s7"><h2>' + esc(t('pp_sections')) + '</h2><div id="pp-sections"></div></div>' +
        '<div class="card s5"><h2>' + esc(t('pp_refs')) + '</h2><div id="pp-refs"></div></div>' +
        '<div class="card s12"><h2>' + esc(t('pp_figures')) + '</h2><div id="pp-figs"></div></div>' +
        '<div class="card s12"><h2>' + esc(t('pp_pdf_preview')) + '<span class="grow"></span><button class="btn" type="button" id="pp-pdf-btn"></button>' +
        '<a class="tag small" href="/api/paper/pdf" target="_blank" rel="noopener" id="pp-pdf-link">' + esc(t('open')) + ' main.pdf ↗</a></h2><div id="pp-pdf"></div></div></div>';
    },
    load: function () { var self = this; return api('/api/paper').then(function (d) { self.data = d; }); },
    bind: function () {
      var self = this;
      $('#pp-pdf-btn').addEventListener('click', function () { PP.pdf = !PP.pdf; LS.set('an_pp_pdf', PP.pdf); self.pdf(self.data); });
    },
    /** lazy PDF preview: the iframe exists only while the toggle is on (and main.pdf exists) */
    pdf: function (d) {
      var has = !!(d && d.pdf), box = $('#pp-pdf'), btn = $('#pp-pdf-btn');
      if (!box || !btn) return;
      btn.textContent = PP.pdf ? t('pp_pdf_hide') : t('pp_pdf_show');
      btn.classList.toggle('on', PP.pdf);
      btn.disabled = !has;
      $('#pp-pdf-link').style.display = has ? '' : 'none';
      var want = !has ? 'none' : PP.pdf ? 'on' : 'off';
      if (box.getAttribute('data-s') === want) return;
      box.setAttribute('data-s', want);
      if (want === 'on') box.innerHTML = '<iframe class="pdf-frame" title="main.pdf" src="/api/paper/pdf#view=FitH" loading="lazy"></iframe>';
      else box.innerHTML = want === 'none' ? emptyBox('pdf_none', null) : '<div class="muted small">' + esc(t('pp_pdf_off_hint')) + '</div>';
    },
    update: function (d) {
      frNote('paper', d && d.updated);
      this.pdf(d);
      var secs = (d && d.sections) || [], figs = (d && d.figures) || [], rf = (d && d.references) || {};
      var done = secs.filter(function (s) { return /^(done|final|complete|completed)$/i.test(String(s.status)); }).length;
      var words = secs.reduce(function (a, s) { return a + (isNum(s.words) ? s.words : 0); }, 0);
      var maxW = Math.max.apply(null, [1].concat(secs.map(function (s) { return isNum(s.words) ? s.words : 0; })));
      $('#pp-kpis').innerHTML =
        '<div class="card kpi"><div class="lbl">' + esc(t('pp_journal')) + '</div><div class="val txt">' + esc(d && d.target_journal || '—') + '</div><div class="subl">' + (d && d.updated ? esc(t('updated_at', { t: fmtTime(d.updated) })) : '') + '</div></div>' +
        '<div class="card kpi accent-cyan"><div class="lbl">' + esc(t('kpi_sections')) + '</div><div class="val">' + done + '<span class="unit">/ ' + secs.length + '</span></div>' + bar(secs.length ? done / secs.length : 0) + '</div>' +
        '<div class="card kpi"><div class="lbl">' + esc(t('pp_words')) + '</div><div class="val">' + words.toLocaleString() + '</div></div>' +
        '<div class="card kpi accent-amber"><div class="lbl">' + esc(t('kpi_refs')) + '</div><div class="val">' + (rf.verified_3x || 0) + '<span class="unit">/ ' + (rf.total || 0) + '</span></div>' + bar(rf.total ? (rf.verified_3x || 0) / rf.total : 0, 'amber') + '</div>' +
        '<div class="card kpi"><div class="lbl">' + esc(t('pp_pdf')) + '</div><div class="val txt">' + (d && d.pdf ? '<a href="/api/paper/pdf" target="_blank" rel="noopener">main.pdf ↗</a>' : '—') + '</div><div class="subl">' + (d && d.pdf ? esc(fmtBytes(d.pdf.size)) + ' · ' + esc(fmtTime(d.pdf.mtime)) : esc(t('pdf_none'))) + '</div></div>';
      $('#pp-sections').innerHTML = secs.length ? secs.map(function (s) {
        var st = String(s.status || 'pending').toLowerCase();
        return '<div class="sec-row"><span>' + esc(s.name) + '</span>' + stChip(st) + bar(isNum(s.words) ? s.words / maxW : 0, st === 'done' ? '' : 'violet') + '<span class="w">' + esc(isNum(s.words) ? s.words.toLocaleString() : '—') + '</span></div>';
      }).join('') : emptyBox('pp_no_sections', null);
      var tot = rf.total || 0;
      $('#pp-refs').innerHTML = tot ? '<div class="funnel">' + [['pp_ref_total', tot, ''], ['pp_ref_1x', rf.verified_1x || 0, 'violet'], ['pp_ref_2x', rf.verified_2x || 0, ''], ['pp_ref_3x', rf.verified_3x || 0, 'amber']].map(function (r) {
        return '<div class="fr"><span class="small">' + esc(t(r[0])) + '</span>' + bar(r[1] / tot, 'thick ' + r[2]) + '<span class="n">' + r[1] + ' <span class="dim">(' + fmtPct(r[1] / tot) + ')</span></span></div>';
      }).join('') + '</div>' : emptyBox('pp_no_refs', 'pp_no_refs_hint');
      var fh = figs.length ? '<div class="gallery">' + figs.map(function (f) {
        var src = '/api/paper/figures/' + encPath(f.file), cap = bi(f, 'caption') || f.file;
        var thumb = f.exists && f.is_image ? '<img loading="lazy" alt="' + esc(f.file) + '" src="' + esc(src) + '">' : '<div class="empty" style="min-height:0;aspect-ratio:1/1;border:0">' + esc(f.exists ? t('pp_not_image') : t('pp_missing')) + '</div>';
        return '<figure' + (f.exists && f.is_image ? ' data-src="' + esc(src) + '" data-cap="' + esc(cap) + '"' : '') + '>' + thumb + '<figcaption>' + stChip(String(f.status || 'pending').toLowerCase()) + ' <span class="mono">' + esc(f.file) + '</span><br>' + esc(cap) + (f.exists && !f.is_image ? ' · <a href="' + esc(src) + '" target="_blank" rel="noopener">' + esc(t('open')) + '</a>' : '') + '</figcaption></figure>';
      }).join('') + '</div>' : emptyBox('pp_no_figs', 'pp_no_figs_hint');
      var fe = $('#pp-figs');
      if (fe.getAttribute('data-h') !== fh) { fe.innerHTML = fh; fe.setAttribute('data-h', fh); }
    }
  };

  // ------------------------------------------------------------------ System
  var HIST = { t: [], cpu: [], gpu: {} };
  VIEWS.system = {
    src: 'system',
    mount: function () {
      return '<div class="grid" id="sys-gpus"></div>' +
        '<div class="grid"><div class="card s12 fr-card" data-src="freshness"><h2>' + esc(t('fr_title')) + '<span class="tag muted small">' + esc(t('fr_title_hint')) + '</span><span class="grow"></span><span id="sys-fr-n"></span></h2><div class="tbl-wrap scroll" id="sys-fr"></div></div></div>' +
        '<div class="grid"><div class="card s12"><h2>' + esc(t('sys_history')) + '<span class="grow"></span><span class="tag muted small">' + esc(t('sys_history_hint')) + '</span></h2><div id="sys-hist" class="chart short"></div></div></div>' +
        '<div class="kpis" id="sys-host" style="margin-top:var(--gap)"></div><div class="kpi-asof" data-srcs="system" hidden></div>' +
        '<div class="grid">' +
        '<div class="card s6"><h2>' + esc(t('sys_extract')) + '</h2><div id="sys-extract"></div></div>' +
        '<div class="card s6"><h2>' + esc(t('sys_services')) + '</h2><div id="sys-sv"></div></div>' +
        '<div class="card s12"><h2>' + esc(t('sys_train_procs')) + '</h2><div id="sys-procs"></div></div></div>';
    },
    load: function () {
      var self = this;
      return api('/api/system').then(function (d) {
        self.data = d;
        if (d && d.ok !== false) {
          HIST.t.push(Date.now());
          HIST.cpu.push(d.host ? d.host.cpu_percent : null);
          (d.gpus || []).forEach(function (g) { (HIST.gpu[g.index] = HIST.gpu[g.index] || []); });
          Object.keys(HIST.gpu).forEach(function (k) { var g = (d.gpus || []).filter(function (x) { return String(x.index) === k; })[0]; HIST.gpu[k].push(g ? g.util : null); });
          var keep = 300;
          if (HIST.t.length > keep) { HIST.t = HIST.t.slice(-keep); HIST.cpu = HIST.cpu.slice(-keep); Object.keys(HIST.gpu).forEach(function (k) { HIST.gpu[k] = HIST.gpu[k].slice(-keep); }); }
        }
      });
    },
    update: function (d) {
      this.fresh();
      if (!d || d.ok === false) { $('#sys-gpus').innerHTML = '<div class="card s12">' + emptyBox('load_error', null) + '</div>'; return; }
      frNote('system', d.ts || d.now);
      var gpus = d.gpus || [];
      var span = gpus.length >= 4 ? 's3' : gpus.length === 3 ? 's4' : 's6';
      $('#sys-gpus').innerHTML = gpus.length ? gpus.map(function (g) {
        var mem = g.mem_total ? g.mem_used / g.mem_total : null, pw = g.power_limit_w ? g.power_w / g.power_limit_w : null;
        return '<div class="card ' + span + ' gpu-card"><h2>GPU ' + esc(g.index) + ' · <span class="tag">' + esc(g.name || '') + '</span><span class="grow"></span><span class="tag muted small">' + esc(d.gpu_source || '') + '</span></h2>' +
          '<div style="display:flex;align-items:baseline;gap:.6rem"><span class="big">' + (isNum(g.util) ? g.util : '—') + '<span class="unit" style="font-size:.5em;color:var(--muted)">%</span></span><span class="muted small">' + esc(t('sys_util')) + '</span></div>' +
          '<div class="row"><span class="muted">' + esc(t('sys_util')) + '</span>' + bar((g.util || 0) / 100, (g.util || 0) > 85 ? 'amber' : '') + '<span class="v">' + (isNum(g.util) ? g.util + '%' : '—') + '</span></div>' +
          '<div class="row"><span class="muted">' + esc(t('sys_mem')) + '</span>' + bar(mem, 'violet') + '<span class="v">' + fmtBytes(g.mem_used) + ' / ' + fmtBytes(g.mem_total) + '</span></div>' +
          '<div class="row"><span class="muted">' + esc(t('sys_power')) + '</span>' + bar(pw, 'amber') + '<span class="v">' + fmt(g.power_w, 0) + ' / ' + fmt(g.power_limit_w, 0) + ' W</span></div>' +
          '<div class="row"><span class="muted">' + esc(t('sys_temp')) + '</span>' + bar(isNum(g.temp) ? g.temp / 90 : 0, (g.temp || 0) > 80 ? 'red' : '') + '<span class="v">' + (isNum(g.temp) ? g.temp + ' °C' : '—') + '</span></div></div>';
      }).join('') : '<div class="card s12">' + emptyBox('no_gpu', null) + '</div>';
      var c = chart('sys-hist');
      if (c) {
        var ser = [{ name: 'CPU', type: 'line', showSymbol: false, data: HIST.t.map(function (x, i) { return [x, HIST.cpu[i]]; }), color: '#a78bfa', lineStyle: { width: 1.5 }, areaStyle: { opacity: 0.06 } }];
        Object.keys(HIST.gpu).forEach(function (k) { ser.push({ name: 'GPU' + k, type: 'line', showSymbol: false, data: HIST.t.map(function (x, i) { return [x, HIST.gpu[k][i]]; }), color: PALETTE[Number(k) % PALETTE.length], lineStyle: { width: 1.5 }, areaStyle: { opacity: 0.06 } }); });
        c.setOption({ backgroundColor: 'transparent', animation: false, grid: { left: 40, right: 16, top: 30, bottom: 24 }, legend: Object.assign({}, LEG), tooltip: Object.assign({ trigger: 'axis', valueFormatter: function (v) { return isNum(v) ? v.toFixed(0) + '%' : '—'; } }, TT),
          xAxis: ax({ type: 'time', min: HIST.t.length > 1 ? HIST.t[0] : Date.now() - 60000, max: HIST.t.length ? Math.max(HIST.t[HIST.t.length - 1], HIST.t[0] + 60000) : Date.now() }), yAxis: ax({ type: 'value', min: 0, max: 100 }), series: ser }, true);
      }
      var h = d.host || {}, ram = h.ram || {}, dk = h.disk_workspace || {}, pids = h.pids;
      var pidsFrac = pids && isNum(Number(pids.max)) && Number(pids.max) > 0 ? pids.current / Number(pids.max) : null;
      $('#sys-host').innerHTML =
        '<div class="card kpi accent-cyan"><div class="lbl">CPU</div><div class="val">' + fmt(h.cpu_percent, 0) + '<span class="unit">%</span></div>' + bar((h.cpu_percent || 0) / 100) + '<div class="subl">' + esc(t('sys_cores', { n: h.cpu_count || '—' })) + (h.load ? ' · load ' + h.load.map(function (x) { return x.toFixed(1); }).join(' / ') : '') + '</div></div>' +
        '<div class="card kpi"><div class="lbl">' + esc(t('sys_ram')) + '</div><div class="val">' + fmt(ram.percent, 0) + '<span class="unit">%</span></div>' + bar((ram.percent || 0) / 100, 'violet') + '<div class="subl">' + fmtBytes(ram.used) + ' / ' + fmtBytes(ram.total) + '</div></div>' +
        '<div class="card kpi"><div class="lbl">' + esc(t('sys_disk')) + '</div><div class="val">' + fmtBytes(dk.free) + '</div>' + bar(dk.total ? dk.used / dk.total : 0, dk.total && dk.free / dk.total < 0.1 ? 'red' : 'amber') + '<div class="subl">' + esc(t('sys_disk_free', { u: fmtBytes(dk.used), tot: fmtBytes(dk.total), path: dk.path || d.disk_path || '—' })) + '</div></div>' +
        (pids ? '<div class="card kpi' + (pidsFrac > 0.9 ? ' accent-amber' : '') + '"><div class="lbl">' + esc(t('sys_pids')) + '</div><div class="val">' + esc(pids.current) + '<span class="unit">/ ' + esc(pids.max) + '</span></div>' + bar(pidsFrac, pidsFrac > 0.9 ? 'red' : '') + '<div class="subl">' + esc(t('sys_pids_hint')) + '</div></div>' : '');
      var ex = d.extraction || {};
      var running = ex.unzip_running;
      if (ex.configured === false) $('#sys-extract').innerHTML = emptyBox('sys_extract_off', 'sys_extract_off_hint');   // AN_RAW not set
      else $('#sys-extract').innerHTML = '<div class="controls" style="margin-bottom:.4rem">' + (running ? '<span class="chip st-running"><span class="dot run"></span>' + esc(t('sys_unzip_running')) + '</span>' : '<span class="chip">' + esc(t('sys_unzip_idle')) + '</span>') +
        '<span class="muted small">' + esc(t('sys_extract_measured', { t: ex.measured_at ? fmtTime(ex.measured_at) : '—' })) + (ex.measuring ? ' · ' + esc(t('sys_measuring')) : '') + '</span></div>' +
        '<div style="display:flex;align-items:baseline;gap:.6rem;margin:.3rem 0"><span class="mono" style="font-size:1.8rem;color:var(--cyan)">' + fmtPct(ex.frac, 1) + '</span><span class="muted mono small">' + fmtBytes(ex.bytes) + ' / ' + fmtBytes(ex.total) + '</span></div>' +
        bar(ex.frac, 'thick') + (d.unzip_procs && d.unzip_procs.length ? '<div class="muted tiny mono" style="margin-top:.4rem">' + d.unzip_procs.map(function (p) { return 'pid ' + esc(p.pid) + ' · ' + esc(clip(p.cmd, 140)); }).join('<br>') + '</div>' : '');
      var sv = d.supervisor || [];
      $('#sys-sv').innerHTML = sv.length ? '<table class="tbl"><thead><tr><th>' + esc(t('sys_service')) + '</th><th>' + esc(t('sys_state')) + '</th><th>' + esc(t('sys_info')) + '</th></tr></thead><tbody>' + sv.map(function (s) {
        return '<tr><td class="mono">' + esc(s.name) + '</td><td><span class="chip st-' + esc(s.state) + '">' + esc(s.state) + '</span></td><td class="small muted mono">' + esc(s.info) + '</td></tr>';
      }).join('') + '</tbody></table>' : emptyBox(d.demo ? 'sys_demo_hidden' : 'sys_no_sv', d.demo ? 'sys_demo_hidden_hint' : null);
      var pr = d.train_procs || [];
      $('#sys-procs').innerHTML = pr.length ? '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>PID</th><th>GPU</th><th>' + esc(t('sys_elapsed')) + '</th><th>' + esc(t('sys_cmd')) + '</th></tr></thead><tbody>' + pr.map(function (p) {
        return '<tr><td class="mono">' + esc(p.pid) + '</td><td class="mono">' + esc(p.gpu === null || p.gpu === undefined ? '—' : (Array.isArray(p.gpu) ? p.gpu.join(',') : p.gpu)) + '</td><td class="mono">' + esc(fmtDur(p.elapsed_s)) + '</td><td class="mono small">' + esc(p.cmd) + '</td></tr>';
      }).join('') + '</tbody></table></div>' : d.demo ? emptyBox('sys_demo_hidden', 'sys_demo_hidden_hint') : emptyBox('sys_no_procs', 'sys_no_procs_hint');
    }
  };

  VIEWS.system.fresh = function () {
    var el = $('#sys-fr');
    if (!el) return;
    var h = frTableHtml();
    if (el.getAttribute('data-h') !== h) { el.innerHTML = h; el.setAttribute('data-h', h); }
    var n = (FR.sources || []).filter(function (s) { return s.stale === true; }).length;
    $('#sys-fr-n').innerHTML = FR.sources ? (n ? '<span class="chip lv-warn">⚠ ' + esc(t('fr_n_stale', { n: n })) + '</span>' : '<span class="chip st-done">' + esc(t('fr_all_ok', { n: FR.sources.length })) + '</span>') : '';
  };

  // ------------------------------------------------------------------ Events
  var EV = { level: '', actor: '', type: '', q: '' };
  VIEWS.events = {
    src: 'events',
    mount: function () {
      return '<div class="grid"><div class="card s12"><h2>' + esc(t('ev_title')) + '<span class="grow"></span><span class="tag muted small" id="ev-count"></span></h2>' +
        '<div class="controls"><span class="seg" id="ev-level"><button type="button" data-v="">' + esc(t('all')) + '</button><button type="button" data-v="info">' + esc(t('lv_info')) + '</button><button type="button" data-v="warn">' + esc(t('lv_warn')) + '</button><button type="button" data-v="error">' + esc(t('lv_error')) + '</button></span>' +
        '<label>' + esc(t('ev_type')) + ' <select id="ev-type"></select></label><label>' + esc(t('ev_actor')) + ' <select id="ev-actor"></select></label>' +
        '<input type="search" id="ev-q" placeholder="' + esc(t('ev_search_ph')) + '" style="min-width:14rem"></div>' +
        '<div class="feed full" id="ev-list"></div></div></div>';
    },
    bind: function () {
      var self = this;
      $('#ev-q').value = EV.q;
      $('#ev-level').addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) { EV.level = b.getAttribute('data-v'); if (self.data) self.update(self.data); } });
      $('#ev-type').addEventListener('change', function (e) { EV.type = e.target.value; if (self.data) self.update(self.data); });
      $('#ev-actor').addEventListener('change', function (e) { EV.actor = e.target.value; if (self.data) self.update(self.data); });
      $('#ev-q').addEventListener('input', function (e) { EV.q = e.target.value; if (self.data) self.update(self.data); });
    },
    load: function () { var self = this; return api('/api/events?limit=2000').then(function (d) { self.data = d; }); },
    update: function (d) {
      var evs = (d && d.events) || [];
      if (evs.length) frNote('events', evs[0].ts);
      $$('#ev-level button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-v') === EV.level); });
      setOpts('#ev-type', [['', t('all')]].concat(((d && d.types) || []).map(function (x) { return [x, tk('type_', x)]; })), EV.type);
      setOpts('#ev-actor', [['', t('all')]].concat(((d && d.actors) || []).map(function (x) { return [x, x]; })), EV.actor);
      var q = EV.q.trim().toLowerCase();
      var f = evs.filter(function (e) {
        return (!EV.level || e.level === EV.level) && (!EV.type || e.type === EV.type) && (!EV.actor || e.actor === EV.actor) &&
          (!q || (e.msg_zh + ' ' + e.msg_en + ' ' + e.actor).toLowerCase().indexOf(q) >= 0);
      });
      $('#ev-count').textContent = t('ev_count', { n: f.length, total: (d && d.total) || 0 }) + (d && d.bad_lines ? ' · ' + t('ev_bad', { n: d.bad_lines }) : '');
      $('#ev-list').innerHTML = f.length ? f.map(evRow).join('') : emptyBox(evs.length ? 'ev_no_match' : 'no_events', null);
    }
  };

  // ======================================================================== shell
  Object.keys(VIEWS).forEach(function (k) { VIEWS[k].el = document.getElementById('view-' + k); VIEWS[k].mounted = false; });
  var current = null, timer = null, busy = false, again = false;

  function applyStatic() {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    $$('[data-i18n]').forEach(function (el) { el.textContent = t(el.getAttribute('data-i18n')); });
    $$('[data-i18n-title]').forEach(function (el) { el.title = t(el.getAttribute('data-i18n-title')); });
    $('#lang-label').textContent = t('lang_switch_to');
    renderConn();
    var libs = [];
    if (!window.echarts) libs.push('ECharts');
    if (!window.marked) libs.push('marked');
    if (!window.DOMPurify) libs.push('DOMPurify');
    $('#lib-status').textContent = libs.length ? t('libs_missing', { l: libs.join(', ') }) : '';
  }
  function safeUpdate(V) {
    try { V.update(V.data); } catch (e) { if (window.console) console.warn('[an-dashboard] render failed', e); }
    try { paintAsOf(V); } catch (e) { if (window.console) console.warn('[an-dashboard] freshness badges failed', e); }
  }
  function mountView(V) {
    V.el.innerHTML = V.mount();
    V.mounted = true;
    if (V.bind) V.bind();
    gcCharts();
  }
  function show(v) {
    current = v;
    $$('nav.tabs a').forEach(function (a) { a.classList.toggle('active', a.getAttribute('data-view') === v); });
    var nav = $('#tabs'), act = nav && nav.querySelector('a.active');
    if (act && nav.scrollWidth > nav.clientWidth + 1) {
      var nr = nav.getBoundingClientRect(), ar = act.getBoundingClientRect();
      if (ar.left < nr.left) nav.scrollLeft += ar.left - nr.left - 16; else if (ar.right > nr.right) nav.scrollLeft += ar.right - nr.right + 16;
    }
    $$('.view').forEach(function (s) { s.classList.toggle('active', s.id === 'view-' + v); });
    var V = VIEWS[v];
    if (!V.mounted) mountView(V);
    if (V.data !== undefined) safeUpdate(V);
    requestAnimationFrame(resizeCharts);
    refreshNow();
  }
  /** query part of the hash, e.g. #/results?ds=x&metric=dice&stat=median -> {ds, metric, stat} */
  function hashQuery() {
    var h = location.hash, i = h.indexOf('?'), o = {};
    if (i < 0) return o;
    h.slice(i + 1).split('&').forEach(function (kv) {
      if (!kv) return;
      var j = kv.indexOf('='), k = j < 0 ? kv : kv.slice(0, j), v = j < 0 ? '' : kv.slice(j + 1);
      try { o[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, ' ')); } catch (e) { /* ignore malformed */ }
    });
    return o;
  }
  function route() {
    var v = (location.hash.replace(/^#\/?/, '').split(/[/?]/)[0]) || 'overview';
    if (!VIEWS[v]) v = 'overview';
    var q = hashQuery();
    if ((q.lang === 'zh' || q.lang === 'en') && q.lang !== lang) setLang(q.lang, true);
    if (q.kiosk !== undefined) kioskFromQuery(q.kiosk);
    if (v === 'events') { if (q.type !== undefined) { EV.type = q.type; EV.fromQuery = true; } else if (EV.fromQuery) { EV.type = ''; EV.fromQuery = false; } }
    if (v === 'leaderboard') {
      if (q.scope === 'live' || q.scope === 'final') LB.scope = q.scope;
      if (q.metric) { if (LB.scope === 'final') LB.fmetric = q.metric; else LB.metric = q.metric; }
      if (q.ds) LB.ds = q.ds;
      if (q.stat === 'mean' || q.stat === 'median') LB.stat = q.stat;
      if (q.tol !== undefined && isFinite(parseFloat(q.tol))) LB.tol[lbTolKind()] = lbClampTol(parseFloat(q.tol));
    }
    if (v === 'training' && q.run) {
      if (T.sel.indexOf(q.run) < 0) T.sel.push(q.run);
      T.focus = q.run; T.init = true; LS.set('an_runs_sel', T.sel);
    }
    if (v === 'results') {
      if (q.ds) R.ds = q.ds;
      if (q.metric) R.metric = q.metric;
      if (q.stat === 'mean' || q.stat === 'median') R.stat = q.stat;
    }
    show(v);
    if (q.help === '1') toggleHelp(true);
  }
  function setLang(l, noSave) {
    lang = l;
    if (!noSave) LS.set('an_lang', l);
    applyStatic();
    renderAlerts(null);
    if ($('#help-ov')) { toggleHelp(false); toggleHelp(true); }
    Object.keys(VIEWS).forEach(function (k) { VIEWS[k].mounted = false; VIEWS[k].el.innerHTML = ''; });
    A.renderedFor = null;
    if (current) {
      var V = VIEWS[current];
      mountView(V);
      if (V.data !== undefined) safeUpdate(V);
      requestAnimationFrame(resizeCharts);
    }
    if (lastHealth) setHeader(lastHealth);
  }

  var conn = { lastOk: 0, fails: 0 };
  function renderConn() {
    var dot = $('#conn-dot'), tx = $('#conn-text');
    var cls = 'warn', key = 'conn_connecting';
    if (conn.lastOk) {
      if (conn.fails === 0) { cls = 'ok'; key = 'conn_online'; } else if (conn.fails < 3) { cls = 'warn'; key = 'conn_retrying'; } else { cls = 'err'; key = 'conn_offline'; }
    } else if (conn.fails) { cls = 'err'; key = 'conn_offline'; }
    dot.className = 'conn-dot ' + cls;
    tx.textContent = t(key);
    $('#last-update').textContent = conn.lastOk ? fmtTime(conn.lastOk, false) : '—';
  }
  var lastHealth = null;
  function setHeader(h) {
    lastHealth = h;
    var ph = h && h.phase;
    $('#phase-name').textContent = ph ? t('phase_prefix') + ' · ' + bi(ph, 'name') : t('phase_unknown');
    $('#phase-pill').title = $('#phase-name').textContent;
    updateTitle();
  }

  // ------------------------------------------------------------------ global alert strip + tab title
  var AL = { list: [], nRunning: null };
  function updateTitle() {
    var ph = lastHealth && lastHealth.phase;
    var err = AL.list.some(function (a) { return a.level === 'error'; });
    document.title = (err ? '⚠ ' : '') + t('title_fmt', { n: AL.nRunning === null ? '—' : AL.nRunning, p: ph ? bi(ph, 'name') : t('phase_unknown') });
  }
  function alertHref(a) { return a.view === 'events' && String(a.id).indexOf('ms:') === 0 ? '#/events?type=milestone' : '#/' + (VIEWS[a.view] ? a.view : 'overview'); }
  var AL_ICON = { error: '⛔', warn: '⚠', info: '◆' };
  function renderAlerts(res) {
    if (res && res.ok !== false && Array.isArray(res.alerts)) { AL.list = res.alerts; AL.nRunning = isNum(res.n_running) ? res.n_running : AL.nRunning; }
    var strip = $('#alert-strip'), list = AL.list;
    var h = list.map(function (a, i) {
      var lv = a.level === 'error' || a.level === 'warn' ? a.level : 'info', msg = lang === 'zh' ? (a.msg_zh || a.msg_en) : (a.msg_en || a.msg_zh);
      return '<button type="button" class="al al-' + lv + '" data-i="' + i + '" title="' + esc(msg + (a.ts ? '\n' + fmtTime(a.ts) : '') + '\n→ ' + tk('tab_', a.view)) + '"><span class="al-ic">' + AL_ICON[lv] + '</span><span class="al-msg">' + esc(clip(msg, 110)) + '</span></button>';
    }).join('');
    if (strip.getAttribute('data-h') !== h) { strip.innerHTML = h; strip.setAttribute('data-h', h); }
    strip.hidden = !list.length;
    var pill = $('#alert-pill'), worst = list.some(function (a) { return a.level === 'error'; }) ? 'error' : list.some(function (a) { return a.level === 'warn'; }) ? 'warn' : 'info';
    pill.hidden = !list.length;
    pill.className = 'pill pill-btn alert-pill al-' + worst;
    $('#alert-n').textContent = String(list.length);
    pill.hidden = list.length === 0;  // no badge when there is nothing to report
    pill.title = t('alerts_title', { n: list.length });
    updateTitle();
  }

  // ------------------------------------------------------------------ kiosk (large-screen auto-rotation), zoom, help
  var KIOSK_VIEWS = ['overview', 'training', 'results', 'leaderboard', 'agents', 'workflow'], KIOSK_INTS = [30, 45, 60, 120], KIOSK_PAUSE_MS = 60000;
  var K = { on: LS.get('an_kiosk', false) === true, int: LS.get('an_kiosk_int', 45), next: 0, pausedUntil: 0, frac: 0 };
  if (KIOSK_INTS.indexOf(K.int) < 0) K.int = 45;
  function kioskSet(on, persist) {
    K.on = !!on; K.next = Date.now() + K.int * 1000; K.pausedUntil = 0;
    if (persist !== false) LS.set('an_kiosk', K.on);
    var b = $('#kiosk-btn'), sel = $('#kiosk-int');
    b.classList.toggle('on', K.on);
    b.setAttribute('aria-pressed', K.on ? 'true' : 'false');
    sel.hidden = !K.on;
    sel.value = String(K.int);
    kioskTick();
  }
  function kioskFromQuery(v) {
    var n = parseInt(v, 10);
    if (!isFinite(n) || n <= 0) { kioskSet(false, false); return; }
    K.int = KIOSK_INTS.reduce(function (a, b) { return Math.abs(b - n) < Math.abs(a - n) ? b : a; }, KIOSK_INTS[0]);
    kioskSet(true, false);
  }
  function kioskPause() { if (K.on) K.pausedUntil = Date.now() + KIOSK_PAUSE_MS; }
  /** driven by the existing 1 s clock interval (no extra timer) */
  function kioskTick() {
    var bar = $('#kiosk-bar'), fill = bar.firstElementChild, now = Date.now();
    bar.hidden = !K.on;
    if (!K.on) return;
    var frac, paused = now < K.pausedUntil;
    if (paused) frac = (K.pausedUntil - now) / KIOSK_PAUSE_MS;
    else {
      if (K.pausedUntil) { K.pausedUntil = 0; K.next = now + K.int * 1000; }
      if (now >= K.next) {
        var i = KIOSK_VIEWS.indexOf(current);
        K.next = now + K.int * 1000;
        location.hash = '#/' + KIOSK_VIEWS[(i + 1) % KIOSK_VIEWS.length];
      }
      frac = 1 - (K.next - now) / (K.int * 1000);
    }
    frac = Math.max(0, Math.min(1, frac));
    fill.style.transition = frac < K.frac || paused !== bar.classList.contains('paused') ? 'none' : '';
    fill.style.width = (frac * 100).toFixed(2) + '%';
    K.frac = frac;
    bar.classList.toggle('paused', paused);
    bar.title = paused ? t('kiosk_paused', { s: Math.ceil((K.pausedUntil - now) / 1000) }) : t('kiosk_next', { s: Math.max(0, Math.ceil((K.next - now) / 1000)) });
  }
  var ZM = { z: LS.get('an_zoom', 1) };
  function zoomSet(z) {
    z = Math.round(Math.max(0.8, Math.min(1.6, isNum(z) ? z : 1)) * 10) / 10;
    ZM.z = z;
    LS.set('an_zoom', z);
    document.body.style.zoom = z === 1 ? '' : String(z);
    var p = $('#zoom-pill');
    p.textContent = Math.round(z * 100) + '%';
    p.classList.toggle('on', z !== 1);
    p.hidden = z === 1;  // the pill only carries information when the zoom is not 100 %
    requestAnimationFrame(resizeCharts);
  }
  function toggleFull() {
    var d = document, el = d.documentElement;
    try {
      if (!d.fullscreenElement) { if (el.requestFullscreen) { var pr = el.requestFullscreen(); if (pr && pr.catch) pr.catch(function () { /* denied */ }); } }
      else if (d.exitFullscreen) { var px = d.exitFullscreen(); if (px && px.catch) px.catch(function () { /* ignore */ }); }
    } catch (e) { /* unsupported */ }
  }
  function toggleHelp(force) {
    var el = $('#help-ov');
    if (el && force !== true) { el.remove(); return; }
    if (el || force === false) return;
    var keys = [['L', 'kb_lang'], ['K', 'kb_kiosk'], ['F', 'kb_full'], ['+ / =', 'kb_zoom_in'], ['-', 'kb_zoom_out'], ['0', 'kb_zoom_reset'], ['1 – 9', 'kb_tabs'], ['G S', 'kb_session'], ['G B', 'kb_board'], ['?', 'kb_help'], ['Esc', 'kb_esc']];
    var links = [['#/overview?kiosk=45', 'kb_q_kiosk'], ['#/results?lang=en', 'kb_q_lang'], ['#/results?ds=…&metric=dice&stat=median', 'kb_q_results'], ['#/events?type=milestone', 'kb_q_events'], ['#/session?lang=en', 'kb_q_session'], ['#/leaderboard?scope=final&metric=dice', 'kb_q_board'], ['#/overview?help=1', 'kb_q_help']];
    el = document.createElement('div');
    el.id = 'help-ov'; el.className = 'help-ov'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true');
    el.innerHTML = '<div class="help-box card"><h2>' + esc(t('kb_title')) + '<span class="grow"></span><button class="btn" type="button" data-close="1">Esc</button></h2>' +
      '<table class="tbl"><tbody>' + keys.map(function (k) { return '<tr><td class="nowrap">' + k[0].split(' ').map(function (x) { return /^[\/–]$/.test(x) ? '<span class="dim">' + esc(x) + '</span>' : '<kbd>' + esc(x) + '</kbd>'; }).join(' ') + '</td><td>' + esc(t(k[1])) + '</td></tr>'; }).join('') + '</tbody></table>' +
      '<div class="card-h" style="margin-top:.8rem">' + esc(t('kb_links')) + '</div><table class="tbl"><tbody>' + links.map(function (k) { return '<tr><td class="mono small">' + esc(k[0]) + '</td><td>' + esc(t(k[1])) + '</td></tr>'; }).join('') + '</tbody></table>' +
      '<div class="muted small" style="margin-top:.6rem">' + esc(t('kb_note')) + '</div></div>';
    el.addEventListener('click', function (e) { if (e.target === el || e.target.closest('[data-close]')) el.remove(); });
    document.body.appendChild(el);
  }

  function refreshNow() {
    clearTimeout(timer);
    tick();
  }
  function tick() {
    if (busy) { again = true; return; }
    busy = true;
    clearTimeout(timer);
    var name = current, V = VIEWS[name];
    Promise.all([api('/api/health'), api('/api/alerts').catch(function () { return null; }), V.load(), frFetch()]).then(function (r) {
      setHeader(r[0]);
      renderAlerts(r[1]);
      conn.lastOk = Date.now(); conn.fails = 0;
      if (name === current) safeUpdate(V);
    }).catch(function (e) {
      conn.fails++;
      if (window.console) console.warn('[an-dashboard] poll failed:', e && e.message ? e.message : e);
    }).then(function () {
      renderConn();
      busy = false;
      if (again) { again = false; tick(); return; }
      timer = setTimeout(tick, POLL_MS);
    });
  }

  var gKey = 0;
  function dropUrlToken() {
    // a `?token=` access link (Vast / Caddy edge) has already set the auth cookie; keep the token out of the address
    // bar, the browser history, bookmarks and photos of the big screen (the app's own parameters live in the hash)
    try {
      if (!/[?&]token=/.test(location.search) || !window.history || !history.replaceState) return;
      var q = location.search.slice(1).split('&').filter(function (p) { return p && p.split('=')[0] !== 'token'; }).join('&');
      history.replaceState(history.state, '', location.pathname + (q ? '?' + q : '') + location.hash);
    } catch (e) { /* ignore */ }
  }
  function boot() {
    dropUrlToken();
    setupMd();
    var q0 = hashQuery();
    if (q0.lang === 'zh' || q0.lang === 'en') lang = q0.lang;  // forced by the link, not persisted
    applyStatic();
    $('#lang-btn').addEventListener('click', function () { setLang(lang === 'zh' ? 'en' : 'zh'); });
    $('#kiosk-btn').addEventListener('click', function () { kioskSet(!K.on); });
    $('#kiosk-int').addEventListener('change', function (e) { var n = parseInt(e.target.value, 10); if (KIOSK_INTS.indexOf(n) >= 0) { K.int = n; LS.set('an_kiosk_int', n); kioskSet(true); } });
    $('#zoom-pill').addEventListener('click', function () { zoomSet(1); });
    $('#help-btn').addEventListener('click', function () { toggleHelp(); });
    $('#alert-pill').addEventListener('click', function () { if (AL.list.length) location.hash = alertHref(AL.list[0]); });
    $('#alert-strip').addEventListener('click', function (e) { var b = e.target.closest('[data-i]'); var a = b && AL.list[+b.getAttribute('data-i')]; if (a) location.hash = alertHref(a); });
    // any interaction pauses the kiosk rotation for 60 s (capture phase: runs before the toggle handlers)
    document.addEventListener('click', kioskPause, true);
    document.addEventListener('keydown', kioskPause, true);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { if ($('#help-ov')) { e.preventDefault(); toggleHelp(false); } return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      var tg = e.target && e.target.tagName;
      if (tg === 'INPUT' || tg === 'TEXTAREA' || tg === 'SELECT' || (e.target && e.target.isContentEditable)) return;
      var k = e.key, gWas = gKey && Date.now() - gKey < 1500;
      gKey = 0;
      if (gWas && (k === 's' || k === 'S')) { location.hash = '#/session'; e.preventDefault(); return; }
      if (gWas && (k === 'b' || k === 'B')) { location.hash = '#/leaderboard'; e.preventDefault(); return; }
      if (k === 'g' || k === 'G') { gKey = Date.now(); e.preventDefault(); return; }
      if (k === 'l' || k === 'L') setLang(lang === 'zh' ? 'en' : 'zh');
      else if (k === 'k' || k === 'K') kioskSet(!K.on);
      else if (k === 'f' || k === 'F') toggleFull();
      else if (k === '+' || k === '=') zoomSet(ZM.z + 0.1);
      else if (k === '-' || k === '_') zoomSet(ZM.z - 0.1);
      else if (k === '0') zoomSet(1);
      else if (/^[1-9]$/.test(k)) { var a = $$('nav.tabs a').filter(function (x) { return x.getAttribute('data-view') !== 'leaderboard'; })[Number(k) - 1]; if (a) location.hash = a.getAttribute('href'); }
      else if (k === '?') toggleHelp();
      else return;
      e.preventDefault();
    });
    zoomSet(ZM.z);
    kioskSet(K.on, false);
    var rt = null;
    window.addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(resizeCharts, 120); });
    window.addEventListener('hashchange', route);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refreshNow(); });
    setInterval(function () { var d = new Date(); $('#clock').textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); if (conn.lastOk && Date.now() - conn.lastOk > POLL_MS * 4 && conn.fails === 0) { conn.fails = 1; renderConn(); } kioskTick(); if (d.getSeconds() % 10 === 0 && current) { try { paintAsOf(VIEWS[current]); } catch (e) { /* ignore */ } } }, 1000);
    route();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
