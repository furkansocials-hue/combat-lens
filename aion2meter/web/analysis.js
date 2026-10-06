'use strict';
/* Analysis window: history on the left, one fight in depth on the right. */

const $ = id => document.getElementById(id);
const Q = new URLSearchParams(location.search);
let hist = [];
let filter = 'all';
let selId = Q.get('id') || null;
let follow = !selId;       // keep showing the newest fight until the user picks one
let D = null;              // /api/encounter
let builtFor = null;
let selKey = null;         // selected player
let mode = null;
let sortKey = 'total', sortAsc = false;
const hiddenSeries = new Set();
let langShown = null;

const PCT_COLS = ['crit', 'back', 'front', 'perfect', 'double', 'parry', 'smite', 'multi'];
const COLS = [
  { k: 'name', l: () => t('skill') },
  { k: 'total', l: () => t('total') },
  { k: 'dps', l: () => 'DPS' },
  { k: 'hits', l: () => t('hits') },
  { k: 'crit', l: () => t('crit') },
  { k: 'back', l: () => t('back') },
  { k: 'front', l: () => t('front') },
  { k: 'perfect', l: () => t('perfect') },
  { k: 'double', l: () => t('double') },
  { k: 'parry', l: () => t('parry') },
  { k: 'smite', l: () => t('smite') },
  { k: 'multi', l: () => t('multi') },
  { k: 'max', l: () => t('max') },
  { k: 'avg', l: () => t('avg') },
];

function histTitle(it) {
  const m = /^(\d+) hedef$/.exec(it.title || '');
  return m ? t('targets', m[1]) : it.title;
}
function dayName(d) { return d === 'today' ? t('today') : d === 'yesterday' ? t('yesterday') : d; }

function staticTexts() {
  $('tb-name').textContent = APP_NAME;
  $('tb-sub').textContent = t('a_title');
  document.title = APP_NAME + ' · ' + t('a_title');
  $('h-title').textContent = t('history');
  $('h-all').textContent = t('h_all');
  $('h-fav').textContent = t('h_fav');
  $('w-min').title = t('minimize');
  $('w-max').title = t('maximize');
  $('w-close').title = t('close');
}

function init() {
  $('logo').innerHTML = logo();
  $('w-min').innerHTML = ic('minus');
  $('w-max').innerHTML = ic('square');
  $('w-close').innerHTML = ic('x');
  $('w-min').onclick = () => act('minimize', { win: 'analysis' });
  $('w-max').onclick = () => act('maximize', { win: 'analysis' });
  $('tb-drag').addEventListener('dblclick', () => act('maximize', { win: 'analysis' }));
  $('w-close').onclick = () => act('close', { win: 'analysis' });
  $('h-tabs').addEventListener('click', e => {
    const b = e.target.closest('button[data-f]');
    if (!b) return;
    filter = b.dataset.f;
    document.querySelectorAll('#h-tabs button').forEach(x => x.classList.toggle('on', x === b));
    renderHist();
  });
  makeGrip($('grip'), 'analysis');
  window.addEventListener('resize', () => { if (D) renderCurve(); });
  loop();
}

window.openFight = id => { follow = false; select(id); };

async function loadMeta() {
  try {
    const s = await api('settings');
    if (mode === null) mode = s.mode;
    if (langShown !== s.lang) {
      setLang(s.lang); langShown = s.lang; staticTexts(); builtFor = null;
      if (D) renderAll();
      renderHist();
    }
  } catch (e) { /* server going away */ }
}

async function loadHist() {
  try { hist = (await api('history')).items; } catch (e) { return; }
  if (follow && hist.length && hist[0].id !== selId) select(hist[0].id);
  else if (!selId && hist.length) select(hist[0].id);
  renderHist();
}

async function loadDetail() {
  if (!selId) { D = null; renderAll(); return; }
  const id = selId;
  try {
    const d = await api('encounter', { id, mode });
    if (id !== selId) return;
    D = d;
  } catch (e) { D = null; }
  renderAll();
}

function select(id) {
  if (id === selId && D) return;
  selId = id;
  selKey = null;
  hiddenSeries.clear();
  builtFor = null;
  renderHist();
  loadDetail();
}

let tick = 0;
async function loop() {
  if (tick % 6 === 0) { await loadMeta(); await loadHist(); }
  if (D && D.live) await loadDetail();
  else if (!D && selId) await loadDetail();
  tick++;
  setTimeout(loop, 500);
}

/* ───────── history ───────── */

function renderHist() {
  const items = filter === 'fav' ? hist.filter(i => i.favorite) : hist;
  const box = $('hist');
  if (!items.length) {
    box.innerHTML = `<div class="side-empty">${filter === 'fav' ? t('h_fav_empty') : t('h_empty')}</div>`;
    box.dataset.h = '';  // so the list is drawn again when there is something to show
    return;
  }
  // consecutive fights in the same zone on the same day make one run (a dungeon visit)
  const runs = [];
  for (const it of items) {
    const zone = it.zone || t('open_world');
    const last = runs[runs.length - 1];
    if (last && last.day === it.day && last.zone === zone) last.items.push(it);
    else runs.push({ day: it.day, zone, items: [it] });
  }
  let html = '', day = null;
  for (const r of runs) {
    if (r.day !== day) { day = r.day; html += `<div class="day">${esc(dayName(day))}</div>`; }
    const n = Math.max(...r.items.map(it => (it.players || []).length));
    const first = r.items[r.items.length - 1];  // newest first, so the last is where the run began
    const total = r.items.reduce((s, it) => s + (it.duration_ms || 0), 0);
    html += `<div class="run"><div class="run-h"><span class="z">${esc(r.zone)}</span>
      <span class="meta">${ic('users')}${n} · ${fmtClock(first.start)} · ${ic('clock')}${fmtTime(total)}</span></div>`;
    for (const it of r.items) html += fightRow(it);
    html += '</div>';
  }
  if (box.dataset.h === html) return;
  box.dataset.h = html;
  box.innerHTML = html;
  box.querySelectorAll('.fight').forEach(el => el.addEventListener('click', e => {
    const star = e.target.closest('[data-star]');
    if (star) {
      e.stopPropagation();
      const it = hist.find(i => i.id === star.dataset.star);
      act('favorite', { id: star.dataset.star, on: !(it && it.favorite) }).then(loadHist);
      return;
    }
    follow = hist.length > 0 && el.dataset.id === hist[0].id;
    select(el.dataset.id);
  }));
}

function fightRow(it) {
  const sel = it.id === selId ? ' sel' : '';
  return `<div class="fight${it.has_boss ? ' boss' : ''}${sel}" data-id="${esc(it.id)}">
    <span class="fi">${ic(it.has_boss ? 'skull' : 'sword')}</span>
    <span class="fn">${esc(histTitle(it))}</span>
    <span class="fc num">${fmtClock(it.start)}</span>
    ${it.live ? `<span class="pill live">${t('live')}</span>` : `<span class="fd num">${fmtTime(it.duration_ms)}</span>`}
    ${it.live ? '' : `<button class="ib star${it.favorite ? ' on' : ''}" data-star="${esc(it.id)}" title="${it.favorite ? t('unstar') : t('star')}">${ic('star')}</button>`}
  </div>`;
}

/* ───────── fight ───────── */

function renderAll() {
  const main = $('main');
  if (!D) {
    builtFor = null;
    main.innerHTML = `<div class="blank"><div class="big">${ic('chart')}</div><b>${t('no_fight')}</b><div>${t('no_fight_sub')}</div></div>`;
    return;
  }
  if (builtFor !== D.id) {
    builtFor = D.id;
    main.innerHTML = `
      <div class="fh" id="fh"></div>
      <div class="content">
        <div class="card"><div class="card-h"><h2>${ic('users')}${t('party_dmg')}</h2><span class="sp"></span><span class="sub" id="pt-sub"></span></div><div id="pt"></div></div>
        <div class="card"><div class="card-h"><h2 id="sum-h"></h2></div><div class="sum" id="sum"></div></div>
        <div class="card full"><div class="card-h"><h2>${ic('sword')}${t('skills')}</h2><span class="sp"></span><span class="sub" id="sk-sub"></span></div><div class="sk-wrap" id="sk"></div></div>
        <div class="card full"><div class="card-h"><h2>${ic('chart')}${t('curve')}</h2><span class="sub">${t('curve_sub')}</span><span class="sp"></span><div class="legend" id="legend"></div></div>
          <div class="curve"><div class="chart" id="chart"></div></div></div>
        <div class="card"><div class="card-h"><h2>${ic('target')}${t('targets_t')}</h2></div><div class="list" id="tg"></div></div>
        <div class="card"><div class="card-h"><h2>${ic('heart')}${t('heals_t')}</h2><span class="sp"></span><span class="sub" id="hl-sub"></span></div><div class="list" id="hl"></div></div>
      </div>`;
  }
  if (!selKey || !D.players.find(p => p.key === selKey)) {
    const me = D.players.find(p => p.is_local);
    selKey = (me || D.players[0] || {}).key || null;
  }
  renderHead();
  renderParty();
  renderSummary();
  renderSkills();
  renderCurve();
  renderTargets();
  renderHeals();
}

function player() { return D.players.find(p => p.key === selKey) || null; }
function entry() { return hist.find(i => i.id === D.id) || null; }

function renderHead() {
  const e = entry();
  const saved = e && !e.live;
  const title = D.multi ? t('targets', D.multi) : D.title;
  const meta = [];
  if (D.zone) meta.push(`<span>${ic('target')}${esc(D.zone)}</span>`);
  meta.push(`<span>${ic('clock')}${fmtTime(D.duration_ms)}</span>`);
  meta.push(`<span>${fmtDate(D.start)}</span>`);
  meta.push(`<span>${ic('users')}${t('players_n', D.players.length)}</span>`);
  meta.push(`<span>${D.shared_time ? t('shared_time') : t('own_time')}</span>`);
  if (!D.live && D.end_reason) meta.push(`<span class="dim">${t('end_' + D.end_reason)}</span>`);
  const html = `<div class="ft"><h1><span class="t">${esc(title)}</span>
      ${D.has_boss ? `<span class="pill boss">${t('boss')}</span>` : ''}${D.live ? `<span class="pill live">${t('live')}</span>` : ''}</h1>
      <div class="fm">${meta.join('')}</div></div>
    <div class="acts">
      <div class="seg" id="mode"><button data-v="all" class="${mode === 'all' ? 'on' : ''}">${t('all_targets')}</button><button data-v="target" class="${mode === 'target' ? 'on' : ''}">${t('main_target')}</button></div>
      <button class="btn" id="cp-text">${ic('copy')}${t('copy_text')}</button>
      <button class="btn primary" id="cp-img">${ic('image')}${t('copy_image')}</button>
      ${saved ? `<button class="ib${e.favorite ? ' on' : ''}" id="fav" title="${e.favorite ? t('unstar') : t('star')}">${ic('star')}</button>
      <button class="ib danger" id="del" title="${t('del')}">${ic('trash')}</button>` : ''}
    </div>`;
  const box = $('fh');
  if (box.dataset.h === html) return;
  box.dataset.h = html;
  box.innerHTML = html;
  $('mode').addEventListener('click', ev => {
    const b = ev.target.closest('button[data-v]');
    if (!b || b.dataset.v === mode) return;
    mode = b.dataset.v;
    act('settings', { values: { mode } });
    loadDetail();
  });
  $('cp-text').onclick = () => copyShareText(D);
  $('cp-img').onclick = () => copyShareImage(D);
  if (saved) {
    $('fav').onclick = () => act('favorite', { id: D.id, on: !e.favorite }).then(loadHist).then(renderHead);
    $('del').onclick = () => {
      if (!confirm(t('del_confirm'))) return;
      act('delete', { id: D.id }).then(() => { selId = null; D = null; follow = true; loadHist(); renderAll(); });
    };
  }
}

function renderParty() {
  const top = Math.max(1, ...D.players.map(p => p.total));
  $('pt-sub').textContent = `${fmtNum(D.total_dps)} DPS · ${fmtNum(D.total)}`;
  const rows = D.players.map((p, i) => {
    const c = cls(p.job);
    return `<tr class="p${p.key === selKey ? ' sel' : ''}" data-k="${esc(p.key)}">
      <td class="num">${i + 1}</td>
      <td><div class="who">${emblem(p.job)}<div><div class="n"><span>${esc(p.name)}</span>${p.is_local ? `<span class="pill me">${t('you')}</span>` : ''}</div>
        <small>${c.name}${p.combat_power ? ' · CP ' + fmtNum(p.combat_power) : ''}</small></div></div></td>
      <td class="bar num"><span>${fmtNum(p.total)}</span><i style="width:${(p.total / top * 100).toFixed(1)}%;right:auto;background:linear-gradient(90deg,${c.color},${c.color}55)"></i></td>
      <td class="dps num">${fmtNum(p.dps)}</td>
      <td class="num" style="color:${c.color};font-weight:700">${fmtPct(p.pct)}</td>
      <td class="num muted">${fmtPct((p.crit_rate || 0) * 100)}</td></tr>`;
  }).join('');
  const html = `<table class="pt"><thead><tr><th></th><th>${t('player')}</th><th>${t('total')}</th><th>DPS</th><th>${t('share')}</th><th>${t('crit')}</th></tr></thead><tbody>${rows}</tbody></table>`;
  const box = $('pt');
  if (box.dataset.h === html) return;
  box.dataset.h = html;
  box.innerHTML = html;
  box.querySelectorAll('tr.p').forEach(tr => tr.onclick = () => { selKey = tr.dataset.k; renderAll(); });
}

function tile(k, v, s, hero) {
  return `<div class="tile${hero ? ' hero' : ''}"><div class="k">${k}</div><div class="v num">${v}</div>${s ? `<div class="s">${s}</div>` : ''}</div>`;
}

function renderSummary() {
  const p = player();
  if (!p) { $('sum').innerHTML = ''; $('sum-h').innerHTML = ''; return; }
  const c = cls(p.job), s = p.summary;
  $('sum-h').innerHTML = `<span class="sel-who">${emblem(p.job, 22)}<b>${esc(p.name)}</b><span class="dim" style="font-weight:600">${c.name}</span></span>`;
  const secs = p.dps ? p.total / p.dps : 0;
  const html = [
    tile('DPS', fmtNum(p.dps), (D.shared_time ? t('shared_time') : t('own_time')) + ' · ' + fmtTime(secs * 1000), true),
    tile(t('total'), fmtNum(p.total), fmtFull(p.total), true),
    tile(t('share'), fmtPct(p.pct), t('of_party'), true),
    tile(t('hits'), fmtFull(s.direct_hits), s.dot_ticks ? `+ ${fmtFull(s.dot_ticks)} ${t('dot_tag')} ${t('ticks')}` : ''),
    tile(t('crit'), fmtPct(s.crit)),
    tile(t('max_hit'), fmtNum(s.max_hit), esc(s.max_hit_skill)),
    tile(t('back'), fmtPct(s.back)),
    tile(t('front'), fmtPct(s.front)),
    tile(t('perfect'), fmtPct(s.perfect)),
    tile(t('double'), fmtPct(s.double)),
    tile(t('parry'), fmtPct(s.parry)),
    tile(t('smite'), fmtPct(s.smite)),
    tile(t('dot'), fmtNum(s.dot_total), p.total ? fmtPct(s.dot_total / p.total * 100) : ''),
    tile(t('heal'), fmtNum(p.heal_total), ''),
    tile(t('skills'), String(s.skills), ''),
  ].join('');
  const box = $('sum');
  if (box.dataset.h !== html) { box.dataset.h = html; box.innerHTML = html; }
}

function skillVal(s, k) {
  if (k === 'multi') return s.hits ? s.mh_events / s.hits * 100 : 0;
  if (k === 'name') return s.name.toLowerCase();
  return s[k] || 0;
}

function renderSkills() {
  const p = player();
  const box = $('sk');
  if (!p) { box.innerHTML = ''; return; }
  const skills = p.skills.slice().sort((a, b) => {
    const x = skillVal(a, sortKey), y = skillVal(b, sortKey);
    const r = x < y ? -1 : x > y ? 1 : 0;
    return sortAsc ? r : -r;
  });
  const topTotal = Math.max(1, ...p.skills.map(s => s.total));
  const color = cls(p.job).color;
  $('sk-sub').textContent = `${p.skills.length} · ${p.name}`;
  // a hit tag nobody's skill shows in this fight only takes room
  const cols = COLS.filter(c => !PCT_COLS.includes(c.k) || p.skills.some(s => skillVal(s, c.k) > 0));
  const head = cols.map(c => `<th data-k="${c.k}" class="${c.k === sortKey ? 'on' + (sortAsc ? ' asc' : '') : ''}">${c.l()}</th>`).join('');
  const body = skills.map(s => {
    const cells = cols.slice(1).map(c => {
      if (c.k === 'total') {
        return `<td class="tt num"><div class="l"><b>${fmtNum(s.total)}</b><small>${fmtPct(s.pct)}</small></div>
          <div class="b"><i style="width:${(s.total / topTotal * 100).toFixed(1)}%;background:linear-gradient(90deg,${color},${color}66)"></i></div></td>`;
      }
      const v = skillVal(s, c.k);
      if (PCT_COLS.includes(c.k)) return `<td class="num${v ? '' : ' z'}">${fmtPct(v)}</td>`;
      if (c.k === 'hits') return `<td class="num">${fmtFull(v)}</td>`;
      return `<td class="num">${fmtNum(v)}</td>`;
    }).join('');
    return `<tr><td><div class="nm">${skillIcon(s.icon)}<span title="${esc(s.name)}">${esc(s.name.replace(/ \(DoT\)$/, ''))}</span>
      ${s.is_dot ? `<span class="pill">${t('dot_tag')}</span>` : ''}</div></td>${cells}</tr>`;
  }).join('');
  const html = `<table class="sk"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  if (box.dataset.h === html) return;
  box.dataset.h = html;
  box.innerHTML = html;
  box.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => {
    const k = th.dataset.k;
    if (sortKey === k) sortAsc = !sortAsc;
    else { sortKey = k; sortAsc = k === 'name'; }
    renderSkills();
  });
}

/* ───────── DPS curve ───────── */

function series() {
  let n = 1;
  for (const p of D.players) for (const [sec] of p.timeline) n = Math.max(n, sec + 1);
  const bin = Math.max(1, Math.ceil(n / 400));
  const bins = Math.ceil(n / bin);
  const win = Math.max(1, Math.round(5 / bin));
  return {
    bin, bins, list: D.players.map(p => {
      const raw = new Array(bins).fill(0);
      for (const [sec, d] of p.timeline) raw[Math.floor(sec / bin)] += d;
      const out = raw.map((_, i) => {
        let sum = 0, cnt = 0;
        for (let j = Math.max(0, i - win + 1); j <= i; j++) { sum += raw[j]; cnt++; }
        return sum / (cnt * bin);
      });
      return { key: p.key, name: p.name, color: cls(p.job).color, vals: out };
    }),
  };
}

function niceMax(v) {
  if (v <= 0) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * e >= v) return m * e;
  return 10 * e;
}

function renderCurve() {
  const box = $('chart');
  if (!box) return;
  const leg = $('legend');
  const legHtml = D.players.map(p => `<button data-k="${esc(p.key)}" class="${hiddenSeries.has(p.key) ? 'off' : ''}"><i style="background:${cls(p.job).color}"></i>${esc(p.name)}</button>`).join('');
  if (leg.dataset.h !== legHtml) {
    leg.dataset.h = legHtml;
    leg.innerHTML = legHtml;
    leg.querySelectorAll('button').forEach(b => b.onclick = () => {
      const k = b.dataset.k;
      hiddenSeries.has(k) ? hiddenSeries.delete(k) : hiddenSeries.add(k);
      renderCurve();
    });
  }
  const W = box.clientWidth || 800, H = box.clientHeight || 230;
  const sig = [D.id, W, H, selKey, LANG, [...hiddenSeries].join(','), D.players.map(p => p.total).join(',')].join('|');
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  const L = 52, R = 12, T = 10, B = 24;
  const S = series();
  const vis = S.list.filter(s => !hiddenSeries.has(s.key));
  const maxV = niceMax(Math.max(1, ...vis.flatMap(s => s.vals)) * 1.05);
  const n = Math.max(2, S.bins);
  const x = i => L + (W - L - R) * i / (n - 1);
  const y = v => T + (H - T - B) * (1 - v / maxV);
  let g = '';
  for (let k = 0; k <= 4; k++) {
    const v = maxV * k / 4, yy = y(v);
    g += `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" stroke="#ffffff" stroke-opacity="${k ? .05 : .12}"/>`;
    g += `<text class="ax" x="${L - 8}" y="${yy + 3}" text-anchor="end">${fmtNum(v)}</text>`;
  }
  const ticks = Math.min(7, Math.max(2, Math.floor((W - L - R) / 90)));
  for (let k = 0; k <= ticks; k++) {
    const i = (n - 1) * k / ticks;
    g += `<text class="ax" x="${x(i)}" y="${H - 6}" text-anchor="${k === 0 ? 'start' : k === ticks ? 'end' : 'middle'}">${fmtTime(i * S.bin * 1000)}</text>`;
  }
  const order = vis.slice().sort((a, b) => (a.key === selKey) - (b.key === selKey));
  let paths = '';
  for (const s of order) {
    const pts = s.vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`);
    const d = 'M' + pts.join('L');
    const me = s.key === selKey;
    if (me) {
      paths += `<defs><linearGradient id="ga" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".35"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient></defs>`;
      paths += `<path d="${d}L${x(s.vals.length - 1)},${y(0)}L${x(0)},${y(0)}Z" fill="url(#ga)"/>`;
    }
    paths += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${me ? 2.4 : 1.4}" stroke-opacity="${me ? 1 : .7}" stroke-linejoin="round"/>`;
  }
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}${paths}<line id="hv" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#fff" stroke-opacity=".25" class="hidden"/></svg><div class="tip hidden" id="tip"></div>`;
  const svg = box.querySelector('svg'), tip = $('tip'), hv = $('hv');
  svg.onmousemove = ev => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * W / r.width;
    const i = Math.round((px - L) / (W - L - R) * (n - 1));
    if (i < 0 || i >= n) { tip.classList.add('hidden'); hv.classList.add('hidden'); return; }
    hv.setAttribute('x1', x(i)); hv.setAttribute('x2', x(i)); hv.classList.remove('hidden');
    const rows = vis.slice().sort((a, b) => b.vals[i] - a.vals[i])
      .map(s => `<div><span><i style="background:${s.color}"></i>${esc(s.name)}</span><b class="num">${fmtNum(s.vals[i])}</b></div>`).join('');
    tip.innerHTML = `<div class="h">${fmtTime(i * S.bin * 1000)}</div>${rows}`;
    tip.classList.remove('hidden');
    const tx = x(i) * r.width / W;
    tip.style.left = (tx + 14 + tip.offsetWidth > r.width ? tx - 14 - tip.offsetWidth : tx + 14) + 'px';
    tip.style.top = '8px';
  };
  svg.onmouseleave = () => { tip.classList.add('hidden'); hv.classList.add('hidden'); };
}

/* ───────── targets & heals ───────── */

function renderTargets() {
  const top = Math.max(1, ...D.targets.map(x => x.total));
  const html = D.targets.length ? D.targets.slice(0, 14).map(x => `<div class="li"><div class="bg" style="width:${(x.total / top * 100).toFixed(1)}%"></div>
      <span class="n">${x.boss ? `<span class="pill boss">${t('boss')}</span>` : ''}${esc(x.name)}${x.dead ? ` <small>· ${t('dead')}</small>` : ''}</span>
      <span class="v num">${fmtNum(x.total)}${x.max_hp ? `<small>${t('hp')} ${fmtNum(x.max_hp)}</small>` : ''}</span></div>`).join('')
    : `<div class="none">—</div>`;
  const box = $('tg');
  if (box.dataset.h !== html) { box.dataset.h = html; box.innerHTML = html; }
}

function renderHeals() {
  const p = player();
  const box = $('hl');
  $('hl-sub').textContent = p && p.heal_total ? fmtNum(p.heal_total) : '';
  let html;
  if (!p || !p.heals.length) html = `<div class="none">${t('no_heals')}</div>`;
  else {
    const top = Math.max(1, ...p.heals.map(h => h.total));
    html = p.heals.slice(0, 12).map(h => `<div class="li heal"><div class="bg" style="width:${(h.total / top * 100).toFixed(1)}%"></div>
      ${skillIcon(h.icon)}<span class="n">${esc(h.name)} <small>×${h.hits}</small></span>
      <span class="v num">${fmtNum(h.total)}<small>${t('max')} ${fmtNum(h.max)}</small></span></div>`).join('');
  }
  if (box.dataset.h !== html) { box.dataset.h = html; box.innerHTML = html; }
}

init();
