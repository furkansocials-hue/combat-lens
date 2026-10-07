'use strict';
/* The overlay: live rows over the game, folded strip, settings and first-run screens. */

const $ = id => document.getElementById(id);
let S = null;            // last /api/state
let tab = null;          // 'me' | 'party' (null until the server tells us)
let pin = null;          // encounter id being looked at (null: follow the newest)
let screen = 'rows';     // rows | settings | timers | welcome (an update in progress covers them all)
let updatedShown = false;
let langShown = null;
let info = null;         // /api/settings (version, failed hotkeys)
let welcomed = false;    // dismissed in this session (the saved flag may lag a poll behind)
const rowEls = new Map();

function hk(name) { return (S && S.ui.hotkeys[name]) || ''; }

function staticTexts() {
  $('tab-me').textContent = t('me');
  $('tab-party').textContent = t('party');
  $('b-reset').title = t('reset');
  $('b-analysis').title = t('analysis');
  $('b-settings').title = t('settings');
  $('b-timers').title = t('timers');
  $('b-fold').title = t('fold');
  $('b-close').title = t('close');
  $('s-open').title = t('unfold');
  $('s-close').title = t('close');
  $('n-prev').title = t('prev');
  $('n-next').title = t('next');
}

function init() {
  $('logo').innerHTML = logo();
  $('s-logo').innerHTML = logo();
  $('b-reset').innerHTML = ic('reset');
  $('b-analysis').innerHTML = ic('chart');
  $('b-settings').innerHTML = ic('gear');
  $('b-timers').innerHTML = ic('clock');
  $('b-fold').innerHTML = ic('minus');
  $('b-close').innerHTML = ic('x');
  $('s-open').innerHTML = ic('down');
  $('s-close').innerHTML = ic('x');
  $('n-prev').innerHTML = ic('left');
  $('n-next').innerHTML = ic('right');

  $('tabs').addEventListener('click', e => {
    const b = e.target.closest('button[data-tab]');
    if (!b) return;
    tab = b.dataset.tab;
    act('settings', { values: { tab } });
    render();
  });
  const togglePause = () => act('pause').then(refresh);
  $('b-pause').onclick = togglePause;
  $('s-pause').onclick = togglePause;
  $('b-reset').onclick = () => { pin = null; act('reset').then(refresh); };
  $('b-analysis').onclick = () => act('analysis', { id: S && S.view ? S.view.id : '' });
  $('b-settings').onclick = () => { screen = screen === 'settings' ? 'rows' : 'settings'; if (screen === 'settings') loadInfo(); render(); };
  $('b-timers').onclick = () => { screen = screen === 'timers' ? 'rows' : 'timers'; loadTimers(true).then(render); };
  $('b-fold').onclick = () => act('fold', { on: true }).then(refresh);
  $('s-open').onclick = () => act('fold', { on: false }).then(refresh);
  document.querySelector('.hdr .drag').addEventListener('dblclick', () => act('fold', { on: true }).then(refresh));
  $('s-title').addEventListener('dblclick', () => act('fold', { on: false }).then(refresh));
  $('b-close').onclick = () => act('close');
  $('s-close').onclick = () => act('close');
  $('n-prev').onclick = () => step(+1);
  $('n-next').onclick = () => step(-1);
  $('f-upd').onclick = () => {
    const u = S && S.status.update;
    if (!u) return;
    if (u.can_install) act('install_update').then(refresh);
    else act('open_url', { url: u.url });
  };
  loadTimers(true);
  makeGrip($('grip'), 'overlay');
  makeGrip($('s-grip'), 'overlay', { fixedHeight: true });
  poll();
}

function step(d) {
  if (!S || !S.nav) return;
  const nc = S.nav.newest_cleared;  // index -1: the cleared panel, 0: the newest fight
  const i = Math.min(S.nav.count - 1, Math.max(nc ? -1 : 0, S.nav.index + d));
  pin = i < 0 || (i === 0 && !nc) ? null : S.nav.ids[i];
  refresh();
}

async function loadInfo() {
  try { info = await api('settings'); } catch (e) { info = null; }
  render();
}

let polling = false;
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    S = await api('state', { tab, pin });
    if (tab === null) tab = S.ui.tab;
    if (pin && S.nav && !S.nav.ids.includes(pin)) pin = null;
    render();
  } catch (e) {
    $('f-dot').className = 'dot';
    $('f-st').textContent = '…';
  }
  polling = false;
}
function poll() { refresh().finally(() => setTimeout(poll, 400)); }

/* ───────── render ───────── */

function render() {
  if (!S) return;
  if (langShown !== S.ui.lang) { setLang(S.ui.lang); langShown = S.ui.lang; staticTexts(); rowEls.clear(); $('rows').innerHTML = ''; }
  if (!S.ui.welcomed && !welcomed && screen === 'rows') screen = 'welcome';
  const folded = S.ui.folded;
  $('panel').classList.toggle('hidden', folded);
  $('strip').classList.toggle('hidden', !folded);
  const st = S.status, v = S.view;
  const paused = st.paused;
  html($('b-pause'), ic(paused ? 'play' : 'pause'));
  $('b-pause').title = paused ? t('resume') : t('pause');
  $('b-pause').classList.toggle('on', paused);
  html($('s-pause'), ic(paused ? 'play' : 'pause'));
  $('s-pause').title = $('b-pause').title;
  $('b-settings').classList.toggle('on', screen === 'settings');
  $('b-timers').classList.toggle('on', screen === 'timers');
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  if (S.ui.just_updated && !updatedShown) { updatedShown = true; toast(t('updated_to', S.ui.just_updated)); }
  if (folded) return renderStrip();

  const updating = st.updating;
  $('update').classList.toggle('hidden', !updating);
  if (updating) {
    ['target', 'notices', 'rnote', 'rows', 'settings', 'timers', 'welcome'].forEach(id => $(id).classList.add('hidden'));
    renderUpdate(updating);
    renderFooter(st, v);
    return;
  }

  renderTarget(v);
  renderNotices(st);
  renderRiftNote();
  $('rows').classList.toggle('hidden', screen !== 'rows');
  $('settings').classList.toggle('hidden', screen !== 'settings');
  $('timers').classList.toggle('hidden', screen !== 'timers');
  $('welcome').classList.toggle('hidden', screen !== 'welcome');
  if (screen === 'rows') renderRows(st, v);
  else if (screen === 'settings') renderSettings();
  else if (screen === 'timers') renderTimers();
  else renderWelcome();
  renderFooter(st, v);
}

function titleOf(v) { return v.multi ? t('targets', v.multi) : v.title; }

function renderTarget(v) {
  const box = $('target');
  if (!v || screen !== 'rows') { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  box.classList.toggle('boss', !!v.has_boss);
  html($('t-ic'), ic(v.has_boss ? 'boss' : 'target'));
  $('t-name').textContent = titleOf(v);
  $('t-name').title = [titleOf(v), v.zone].filter(Boolean).join(' · ');
  let time = fmtTime(v.duration_ms);
  if (!v.live && v.end_reason) time += ' · ' + t('end_' + v.end_reason);
  $('t-time').textContent = time;
  const hp = v.hp;
  box.classList.toggle('has-hp', !!hp);
  if (hp) {
    const pct = hp[1] ? hp[0] / hp[1] * 100 : 0;
    html($('t-hp'), `<b>${fmtFull(hp[0])}</b> / ${fmtFull(hp[1])}`);
    txt($('t-pct'), fmtPct(pct));
    $('t-bar').style.width = pct.toFixed(2) + '%';
  } else {
    $('t-hp').innerHTML = v.live ? `<span class="pill live">${t('live')}</span>` : '';
  }
}

function renderNotices(st) {
  const out = [];
  if (st.clickthrough) out.push(`<div class="note info">${ic('pointer')}<span class="grow">${esc(t('clickthrough_on', hk('clickthrough')))}</span></div>`);
  if (st.paused) out.push(`<div class="note">${ic('pause')}<span class="grow">${t('paused')}</span><button data-op="pause">${t('resume')}</button></div>`);
  // you are known (by your entity) but not by name: the game sends it only on a loading screen
  if (st.local && st.local.startsWith('#') && !S.ui.label) out.push(`<div class="note info">${ic('user')}<span class="grow">${t('name_unknown')}</span></div>`);
  const html = out.join('');
  const box = $('notices');
  if (box.dataset.h !== html) {
    box.innerHTML = html;
    box.dataset.h = html;
    box.querySelectorAll('button[data-op]').forEach(b => {
      b.onclick = () => act(b.dataset.op).then(refresh);
    });
  }
}

function setEmpty(key, html) {
  const box = $('rows');
  if (box.dataset.empty === key) return;
  rowEls.clear();
  box.innerHTML = `<div class="empty">${html}</div>`;
  box.dataset.empty = key;
  box.querySelectorAll('[data-op]').forEach(b => { b.onclick = () => act(b.dataset.op, b.dataset.url ? { url: b.dataset.url } : {}).then(refresh); });
}

function renderRows(st, v) {
  if (!st.npcap) {
    return setEmpty('npcap', `<div class="big">${ic('wifi')}</div><b>${t('npcap_title')}</b><p>${t('npcap_body')}</p>
      <div class="acts"><button class="btn primary" data-op="open_url" data-url="https://npcap.com/#download">${ic('link')}${t('npcap_get')}</button>
      <button class="btn" data-op="retry_npcap">${ic('sync')}${t('retry')}</button></div>`);
  }
  if (!v) {
    if (!st.locked && !S.ui.label) return setEmpty('game', `<div class="big">${ic('sync', 'class="spin"')}</div><b>${t('waiting_game')}</b><p>${t('waiting_game_sub')}</p>`);
    return setEmpty('fight', `<div class="big">${ic('sword')}</div><b>${t('waiting_fight')}</b><p>${t('waiting_fight_sub')}</p>`);
  }
  if (!v.rows.length) return setEmpty('me', `<div class="big">${ic('user')}</div><b>${t('me_empty')}</b><p>${t('me_empty_sub')}</p>`);

  const box = $('rows');
  if (box.dataset.empty) { box.innerHTML = ''; box.dataset.empty = ''; }
  const top = Math.max(1, ...v.rows.map(r => r.total));
  const seen = new Set();
  v.rows.forEach((r, i) => {
    let el = rowEls.get(r.key);
    if (!el) {
      el = document.createElement('div');
      el.className = 'row';
      el.innerHTML = `<div class="fill"></div><span class="rk num"></span><span class="em"></span>
        <div class="who"><div class="nm"><span></span></div><div class="sub"></div></div>
        <div class="val"><div class="amt num"></div><div class="rate num"></div></div><div class="pct num"></div>`;
      el.onclick = () => act('analysis', { id: S.view ? S.view.id : '' });
      rowEls.set(r.key, el);
    }
    seen.add(r.key);
    const c = cls(r.job);
    set(el, 'job', r.job || '', () => {
      el.querySelector('.em').innerHTML = emblem(r.job);
      el.querySelector('.fill').style.background = `linear-gradient(90deg, ${c.color}80, ${c.color}26 75%, ${c.color}10)`;
      el.querySelector('.pct').style.color = c.color;
    });
    el.classList.toggle('local', !!r.is_local);
    el.querySelector('.fill').style.width = (r.total / top * 100).toFixed(2) + '%';
    el.querySelector('.rk').textContent = i + 1;
    set(el, 'nm', r.name + (r.is_local ? '*' : ''), () => {
      el.querySelector('.nm').innerHTML = `<span>${esc(r.name)}</span>` + (r.is_local ? `<span class="pill me">${t('you')}</span>` : '');
    });
    const heal = r.heal ? `<span class="hl">♥ ${fmtNum(r.heal)} · ${fmtNum(r.hps)}/s</span>` : null;
    const sub = [c.name !== '?' ? esc(c.name) : null, heal, r.total ? t('crit') + ' ' + fmtPct((r.crit_rate || 0) * 100, 0) : null,
      r.combat_power ? 'CP ' + fmtNum(r.combat_power) : null].filter(Boolean).join(' · ');
    html(el.querySelector('.sub'), sub);
    txt(el.querySelector('.amt'), fmtNum(r.total));  // total damage leads, DPS under it
    const rateEl = el.querySelector('.rate');
    set(el, 'rate', r.dps, () => { rateEl.innerHTML = `${fmtNum(r.dps)}<small>/s</small>`; });
    txt(el.querySelector('.pct'), fmtPct(r.pct));
    if (box.children[i] !== el) box.insertBefore(el, box.children[i] || null);
  });
  for (const [k, el] of rowEls) if (!seen.has(k)) { el.remove(); rowEls.delete(k); }
}

function txt(el, s) { if (el.textContent !== String(s)) el.textContent = s; }
// only when it changed: rewriting a button under the pointer swallows the click
function html(el, s) { if (el.dataset.h !== s) { el.dataset.h = s; el.innerHTML = s; } }
function set(el, key, val, fn) { const k = 'v_' + key; if (el.dataset[k] !== String(val)) { el.dataset[k] = String(val); fn(); } }

function renderFooter(st, v) {
  const dot = $('f-dot');
  let status;
  if (S.ui.label) { dot.className = 'dot ok'; status = t(S.ui.label === 'demo' ? 'demo' : 'replay'); }
  else if (!st.npcap) { dot.className = 'dot'; status = t('not_connected'); }
  else if (st.locked) { dot.className = 'dot ok'; status = t('connected'); }
  else { dot.className = 'dot wait'; status = t('waiting_game'); }
  const bits = [status];
  if (v && v.zone) bits.push(v.zone);
  if (st.local) bits.push(st.local + (st.guess ? ' ?' : ''));
  txt($('f-st'), bits.join(' · '));
  const tips = [];
  if (st.guess) tips.push(t('guess'));
  if (v && !v.party_known) tips.push(t('party_unknown'));
  $('f-st').title = tips.join('\n');
  const upd = $('f-upd');
  upd.classList.toggle('hidden', !st.update || !!st.updating);
  if (st.update) txt(upd, t('update_avail', st.update.version) + (st.update.can_install ? ' · ' + t('update_now') : ''));
  const nav = S.nav;
  $('f-nav').classList.toggle('hidden', !nav || (nav.count < 2 && !nav.newest_cleared) || screen !== 'rows');
  if (nav) {
    txt($('n-pos'), `${nav.index < 0 ? '–' : nav.count - nav.index}/${nav.count}`);
    $('n-prev').disabled = nav.index >= nav.count - 1;
    $('n-next').disabled = nav.index <= (nav.newest_cleared ? -1 : 0);
  }
}

function renderStrip() {
  const v = S.view;
  const up = S.status.updating;
  if (up) {
    txt($('s-name'), t('updating') + (up.stage === 'download' ? ' %' + (up.pct || 0) : ''));
    txt($('s-time'), '');
    return;
  }
  txt($('s-name'), v ? titleOf(v) : (S.status.locked ? t('waiting_fight') : t('waiting_game')));
  txt($('s-time'), v ? fmtTime(v.duration_ms) : '');
  let val = '';
  if (v) {
    const me = v.rows.find(r => r.is_local);
    const total = tab === 'me' ? (me ? me.total : 0) : v.total;
    const dps = tab === 'me' ? (me ? me.dps : 0) : v.total_dps;
    val = `${fmtNum(total)}<small>${fmtNum(dps)}/s</small>`;
  }
  if ($('s-val').dataset.h !== val) { $('s-val').innerHTML = val; $('s-val').dataset.h = val; }
  const hp = v && v.hp;
  $('s-hp').classList.toggle('hidden', !hp);
  if (hp) $('s-hpbar').style.width = (hp[1] ? hp[0] / hp[1] * 100 : 0).toFixed(1) + '%';
}

/* ───────── self-update ───────── */

function renderUpdate(up) {
  const box = $('update');
  const stage = up.stage;
  const err = stage === 'error';
  const key = [LANG, stage, up.error || ''].join('|');
  if (box.dataset.key !== key) {
    box.dataset.key = key;
    box.innerHTML = `
      <div class="up-logo">${logo()}</div>
      <div class="up-title">${err ? t('up_failed') : t('updating')}</div>
      <div class="up-ver num">v${esc(S.ui.version)} → v${esc(up.version || '')}</div>
      <div class="up-bar${err ? ' err' : ''}${stage === 'download' ? '' : ' busy'}"><i id="up-fill"></i></div>
      <div class="up-stage" id="up-stage"></div>
      ${err ? `<div class="up-err">${esc(up.error || '')}</div>
        <div class="up-acts"><button class="btn primary" id="up-retry">${ic('sync')}${t('retry')}</button>
        <button class="btn" id="up-page">${ic('link')}${t('up_page')}</button><button class="btn" id="up-close">${t('close')}</button></div>`
      : `<div class="up-note">${t('up_note')}</div>`}`;
    if (err) {
      $('up-retry').onclick = () => act('install_update').then(refresh);
      $('up-page').onclick = () => S.status.update && act('open_url', { url: S.status.update.url });
      $('up-close').onclick = () => act('update_dismiss').then(refresh);
    }
  }
  const mb = n => dec((n / 1048576).toFixed(1));
  const label = stage === 'download'
    ? `${t('up_download')} ${fmtPct(up.pct || 0, 0)}${up.total ? `  ·  ${mb(up.done)} / ${mb(up.total)} MB` : ''}`
    : err ? '' : t('up_' + stage);
  txt($('up-stage'), label);
  $('up-fill').style.width = (stage === 'download' ? (up.pct || 0) : 100) + '%';
}

/* ───────── settings & welcome ───────── */

function renderSettings() {
  const ui = S.ui;
  const failed = (info && info.hotkeys_failed) || [];
  const keyRows = Object.entries(ui.hotkeys).map(([k, v]) =>
    `<div class="hk${failed.includes(k) ? ' bad' : ''}"><span>${t('hk_' + k)}${failed.includes(k) ? ' · ' + t('s_hotkey_failed') : ''}</span><kbd>${esc(v)}</kbd></div>`).join('');
  const html = `
    <h3>${ic('gear', 'width="13" height="13" style="stroke:currentColor;fill:none;stroke-width:2"')}${t('settings')}</h3>
    <div class="set"><div class="lb"><div>${t('s_language')}</div></div>
      <div class="seg" data-key="lang"><button data-v="tr" class="${ui.lang === 'tr' ? 'on' : ''}">Türkçe</button><button data-v="en" class="${ui.lang === 'en' ? 'on' : ''}">English</button></div></div>
    <div class="set"><div class="lb"><div>${t('s_opacity')}</div><small class="num" id="op-v">${Math.round(ui.opacity * 100)}%</small></div>
      <input type="range" id="op" min="35" max="100" value="${Math.round(ui.opacity * 100)}"></div>
    <div class="set"><div class="lb"><div>${t('s_mode')}</div></div>
      <div class="seg" data-key="mode"><button data-v="all" class="${ui.mode === 'all' ? 'on' : ''}">${t('all_targets')}</button><button data-v="target" class="${ui.mode === 'target' ? 'on' : ''}">${t('main_target')}</button></div></div>
    <div class="set"><div class="lb"><div>${t('s_clear_after')}</div><small>${t('s_clear_after_sub')}</small></div>
      <div class="seg" data-key="keep_fight">${[60, 120, 300, 600, 0].map(v => `<button data-v="${v}" class="${ui.keep_fight === v ? 'on' : ''}">${v ? t('s_min', v / 60) : t('s_off')}</button>`).join('')}</div></div>
    <div class="set"><div class="lb"><div>${t('s_clickthrough')}</div><small>${t('s_clickthrough_sub')}</small></div>
      <label class="switch"><input type="checkbox" id="ct" ${S.status.clickthrough ? 'checked' : ''}><span></span></label></div>
    <div class="set" style="display:block"><div class="lb" style="margin-bottom:4px"><div>${t('s_hotkeys')}</div></div>${keyRows}</div>
    <div class="set"><div class="lb"><div>${t('s_data')}</div></div><button class="btn" id="upd-data">${ic('sync')}${t('update_data')}</button></div>
    <div class="set-foot"><button class="btn" id="open-dir">${ic('folder')}${t('s_folder')}</button>
      <button class="btn" id="chk-upd">${ic('sync')}${t('check_updates')}</button>
      <span class="dim">${info ? esc(t('s_version', info.version)) : ''}</span></div>`;
  const box = $('settings');
  if (box.dataset.h === html) return;
  box.dataset.h = html;
  box.innerHTML = html;
  box.querySelectorAll('.seg[data-key]').forEach(seg => seg.addEventListener('click', e => {
    const b = e.target.closest('button[data-v]');
    if (b) act('settings', { values: { [seg.dataset.key]: seg.dataset.key === 'keep_fight' ? +b.dataset.v : b.dataset.v } }).then(refresh);
  }));
  let opTimer = null;
  $('op').addEventListener('input', e => {
    $('op-v').textContent = e.target.value + '%';
    clearTimeout(opTimer);
    opTimer = setTimeout(() => act('settings', { values: { opacity: e.target.value / 100 } }).then(refresh), 120);
  });
  $('ct').onchange = e => act('clickthrough', { on: e.target.checked }).then(refresh);
  $('upd-data').onclick = () => { act('update_data'); toast(t('s_data_started')); };
  $('open-dir').onclick = () => act('open_folder');
  $('chk-upd').onclick = async () => {
    const r = await act('check_update');
    if (!r.ok) toast(t('update_check_failed'));
    else if (r.update) toast(t('update_avail', r.update.version) + (r.update.can_install ? '' : ' · ' + t('up_source')));
    else toast(t('up_to_date', r.version));
    refresh();
  };
}

function renderWelcome() {
  const html = `<h2>${t('welcome_title')}</h2><ul>
    <li>${t('welcome_1')}</li><li>${t('welcome_2')}</li>
    <li>${esc(t('welcome_3', hk('reset'), hk('fold'), hk('clickthrough')))}</li></ul>
    <div class="risk">${t('welcome_risk')}</div>
    <button class="btn primary" id="w-ok">${t('welcome_ok')}</button>`;
  const box = $('welcome');
  if (box.dataset.h === html) return;
  box.dataset.h = html;
  box.innerHTML = html;
  $('w-ok').onclick = () => { welcomed = true; screen = 'rows'; act('settings', { values: { welcomed: true } }).then(refresh); };
}

init();
