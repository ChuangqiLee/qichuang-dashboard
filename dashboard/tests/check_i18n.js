// Asserts zh/en dictionaries have identical key sets and that every key referenced
// by app.js / index.html exists.  Run:  node dashboard/tests/check_i18n.js
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const dir = path.join(__dirname, '..', 'static');
const ctx = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(dir, 'i18n.js'), 'utf8'), ctx);
const I = ctx.window.I18N;
assert(I && I.zh && I.en, 'I18N.zh / I18N.en missing');
const zh = Object.keys(I.zh).sort(), en = Object.keys(I.en).sort();
const onlyZh = zh.filter(k => !(k in I.en)), onlyEn = en.filter(k => !(k in I.zh));
assert.deepStrictEqual(onlyZh, [], 'keys only in zh: ' + onlyZh.join(', '));
assert.deepStrictEqual(onlyEn, [], 'keys only in en: ' + onlyEn.join(', '));
for (const l of ['zh', 'en']) for (const [k, v] of Object.entries(I[l])) assert(typeof v === 'string' && v.length, `${l}.${k} empty`);
// placeholders must match between languages
for (const k of zh) {
  const ph = s => (s.match(/\{(\w+)\}/g) || []).sort().join();
  assert.strictEqual(ph(I.zh[k]), ph(I.en[k]), 'placeholder mismatch in ' + k);
}
const src = fs.readFileSync(path.join(dir, 'app.js'), 'utf8') + fs.readFileSync(path.join(dir, 'index.html'), 'utf8');
const used = new Set();
const pats = [/\bt\(\s*'([A-Za-z0-9_]+)'/g, /emptyBox\(\s*'([A-Za-z0-9_]+)'/g, /emptyBox\([^;]*?,\s*'([A-Za-z0-9_]+)'/g,
  /data-i18n(?:-title)?="([A-Za-z0-9_]+)"/g, /kpi\(\s*'([A-Za-z0-9_]+)'/g, /\['(pp_ref_[a-z0-9]+)'/g,
  /cc\('[^']+',\s*'[^']+',\s*'([a-z0-9_]+)'/g, /key = '([a-z_]+)'/g, /U\('(u_[dhms])'/g, /\? '([a-z]+_[a-z_]+)' : '([a-z]+_[a-z_]+)'/g];
for (const re of pats) { let m; while ((m = re.exec(src))) { for (const g of m.slice(1)) if (g) used.add(g); } }
// dynamic prefixes used via tk(prefix, value) -- the values the app knows about
const dyn = { st_: ['pending', 'running', 'done', 'failed', 'skipped', 'queued', 'pruned', 'unknown'], fam_: ['baseline', 'novel', 'ablation', 'ours'],
  role_: ['user', 'assistant', 'tool'], type_: ['milestone', 'info', 'warn', 'error'], tier_: ['best', 'spotlight', 'oral', 'highlight', 'poster', 'unknown'],
  split_: ['train', 'val', 'test'], route_: ['orchestrator', 'subagents', 'escalation', 'model', 'effort', 'trigger'], lv_: ['info', 'warn', 'error'],
  ss_st_: ['delivered', 'read', 'replied', 'sending', 'failed'], ss_perm_: ['auto', 'default', 'acceptEdits', 'plan', 'bypassPermissions'], ss_onoff_: ['on', 'off', 'unknown'],
  vd_: ['sota', 'ahead', 'tie', 'behind'], tr_trend_: ['up', 'flat', 'final'], lb_m_: ['val_dice', 'val_hd95', 'val_dice_aux', 'val_dice_mean', 'val_hd95_aux'],
  fr_cad_: ['live', 'periodic', 'event', 'manual'], fr_cad_tipx_: ['live', 'periodic', 'event', 'manual'], fr_cad_tip_: ['live', 'periodic'],
  fr_use_: ['alerts', 'briefing', 'curves', 'events', 'kpi_best_dice', 'kpi_best_dice_live', 'kpi_elapsed', 'kpi_experiments', 'kpi_gpu', 'kpi_papers', 'kpi_phase', 'kpi_queue_eta', 'kpi_refs', 'kpi_sections', 'milestones', 'phases', 'race', 'routing', 'final', 'live', 'timeline', 'gallery', 'status', 'lineage', 'queue'],
  fr_src_: ['workflow', 'experiments', 'results', 'cases', 'runs', 'events', 'system', 'briefing', 'session_status', 'session', 'routing', 'literature', 'paper', 'agents', 'leaderboard', 'freshness'],
  fr_tip_: ['workflow', 'experiments', 'results', 'cases', 'runs', 'events', 'system', 'briefing', 'session_status', 'session', 'routing', 'literature', 'paper', 'agents', 'leaderboard', 'freshness'],
  ss_err_c_: ['rate_limited', 'too_large', 'text_too_long', 'empty_text', 'bad_host', 'no_header', 'bad_content_type', 'bad_json', 'bad_model', 'bad_effort', 'bad_kind', 'bad_text', 'bad_control', 'bad_value'] };
for (const [p, vs] of Object.entries(dyn)) for (const v of vs) used.add(p + v);
const missing = [...used].filter(k => !(k in I.en) && !/^(an_|tr-|rs-|ov-|wf-|ag-|ev-|lit-|pp-|sys-)/.test(k) && k.length > 1 && !['ok', 'warn', 'err'].includes(k));
assert.deepStrictEqual(missing, [], 'keys used but not defined: ' + missing.join(', '));
console.log(`OK: ${zh.length} keys in both zh and en; ${used.size} referenced keys all defined`);
