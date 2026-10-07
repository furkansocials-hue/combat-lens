'use strict';
/* The overlay's timers screen: field boss respawns and the Spacetime Rift clock.
   A boss the game's own list covers shows the game's time; the others count from their kill.
   Server times are turned into the player's own time with Intl, so daylight saving stays right. */

let TM = null;        // /api/timers
let tmAt = 0;         // when it was fetched
let tmEdit = null;    // boss code whose respawn cycle is being edited
let tmFaction = null; // faction shown while the saved setting catches up

async function loadTimers(force) {
  if (!force && TM && Date.now() - tmAt < 5000) return;
  try { TM = await api('timers'); tmAt = Date.now(); } catch (e) { /* keep the last one */ }
}

const WEEKDAY = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
const _tzFmt = {};
function tzParts(ms, tz) {
  const f = _tzFmt[tz] || (_tzFmt[tz] = new Intl.DateTimeFormat('en-US', {
    timeZone: tz, hourCycle: 'h23', weekday: 'short', year: 'numeric', month: 'numeric', day: 'numeric',
    hour: 'numeric', minute: 'numeric', second: 'numeric' }));
  const p = {};
  for (const x of f.formatToParts(new Date(ms))) p[x.type] = x.value;
  return p;
}
// a wall-clock time in `tz` -> epoch ms (the second pass settles daylight-saving edges)
function zonedMs(y, mo, d, h, mi, tz) {
  const want = Date.UTC(y, mo - 1, d, h, mi);
  let at = want;
  for (let k = 0; k < 2; k++) {
    const p = tzParts(at, tz);
    at += want - Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  }
  return at;
}
// the next `n` rift openings, the one whose entrance is still open included
function riftTimes(rift, tz, now, n) {
  const p = tzParts(now, tz), out = [];
  for (let dd = -1; dd <= 2; dd++) {
    const day = new Date(Date.UTC(+p.year, +p.month - 1, +p.day + dd));
    for (const h of rift.hours) {
      const at = zonedMs(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), h, 0, tz);
      if (at + rift.open_min * 60000 > now) out.push(at);
    }
  }
  return out.sort((a, b) => a - b).slice(0, n);
}
function isDomination(rift, at, tz) {
  const p = tzParts(at, tz);
  return rift.domination.weekdays.includes(WEEKDAY[p.weekday]) && rift.domination.hours.includes(+p.hour % 24);
}
function serverTz() { return (TM && TM.regions[(S && S.ui.region) || 'eu']) || 'Europe/Berlin'; }
function riftNow() {
  if (!TM) return null;
  const now = Date.now(), at = riftTimes(TM.rift, serverTz(), now, 1)[0];
  if (!at) return null;
  const open = now >= at;
  return { at, open, left: open ? at + TM.rift.open_min * 60000 - now : at - now };
}
function clockIn(ms, tz) {
  return new Intl.DateTimeFormat(LANG === 'tr' ? 'tr-TR' : 'en-GB',
    { hour: '2-digit', minute: '2-digit', timeZone: tz || undefined }).format(new Date(ms));
}
function dur(ms) {
  const s = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s % 60).padStart(2, '0');
}
function cycleText(min) {
  const h = Math.floor(min / 60), m = min % 60;
  return [h ? h + ' ' + t('h_short') : '', m ? m + ' ' + t('min_short') : ''].filter(Boolean).join(' ');
}

const WINDOW_MS = 10 * 60000;  // a boss comes back inside about ten minutes after its cycle ends
function bossState(b, now) {
  if (b.live && b.live.up) return 'on';  // the game says it is up
  if (b.due == null) return 'unk';
  if (now < b.due) return 'cd';
  return now < b.due + WINDOW_MS ? 'due' : 'up';
}
const STATE_ORDER = { due: 0, cd: 1, on: 2, up: 3, unk: 4 };

/* rows screen: a line while a rift is about to open or open */
function renderRiftNote() {
  const box = $('rnote');
  const r = riftNow();
  const show = r && screen === 'rows' && (r.open || r.left < 10 * 60000);
  box.classList.toggle('hidden', !show);
  if (!show) return;
  if (!box.firstChild) box.innerHTML = `<div class="note info">${ic('clock')}<span class="grow"></span></div>`;
  txt(box.querySelector('.grow'), r.open ? t('rift_open_note', dur(r.left)) : t('rift_soon_note', dur(r.left)));
}

function renderTimers() {
  loadTimers();
  const box = $('timers');
  if (!TM) { html(box, `<div class="empty"><div class="big">${ic('clock')}</div></div>`); return; }
  const now = Date.now(), tz = serverTz(), fac = tmFaction || S.ui.faction || 'Elyos';
  const bosses = TM.bosses.filter(b => b.faction === fac).map(b => Object.assign({ st: bossState(b, now) }, b));
  bosses.sort((a, b) => STATE_ORDER[a.st] - STATE_ORDER[b.st] || (a.due || 0) - (b.due || 0)
    || a.cycle_min - b.cycle_min || a.name.localeCompare(b.name));
  const rifts = riftTimes(TM.rift, tz, now, 4);
  // the parts that change only now and then are drawn once; the countdowns are updated in place below
  const seen = TM.live_seen && TM.live_seen[fac];
  const key = JSON.stringify([LANG, fac, S.ui.region, tmEdit, rifts[0], seen && Math.floor(seen / 60000),
    bosses.map(b => [b.code, b.st, b.due, b.cycle_min, b.live && b.live.at])]);
  if (box.dataset.key !== key) {
    box.dataset.key = key;
    const regions = Object.keys(TM.regions).map(r => `<option value="${r}"${r === S.ui.region ? ' selected' : ''}>${t('reg_' + r)}</option>`).join('');
    const nextList = rifts.slice(1).map(at => `<span>${clockIn(at)}${isDomination(TM.rift, at, tz) ? ` <b>${t('domination')}</b>` : ''}</span>`).join('');
    const rows = bosses.map(b => {
      const cyc = tmEdit === b.code
        ? `<input class="tb-in num" type="number" min="1" max="10080" value="${b.cycle_min}" data-in="${b.code}"> ${t('min_short')}`
        : `<button class="tb-cyc${b.custom ? ' custom' : ''}" data-cyc="${b.code}" title="${t('b_cycle')}">${cycleText(b.cycle_min)}</button>`;
      const status = b.st === 'cd'
        ? `<div class="tb-cd num" data-cd="${b.due}"></div><div class="tb-at">${clockIn(b.due)}${b.live ? ' · ' + t('b_game') : ''}</div>`
        : b.st === 'on'
          ? `<div class="tb-cd">${t('b_on')}</div><div class="tb-at">${t('b_on_at', clockIn(b.live.at))}</div>`
          : `<div class="tb-cd">${t('b_' + b.st)}</div>${b.killed != null ? `<div class="tb-at">${t('b_died', clockIn(b.killed))}</div>` : ''}`;
      return `<div class="tb-row ${b.st}">
        <div class="tb-who"><div class="tb-n">${esc(b.name)}</div><div class="tb-s">${esc(b.zone)} · Lv ${b.level} · ${cyc}</div></div>
        <div class="tb-st">${status}</div>
        <button class="ib" data-kill="${b.code}" title="${t('b_killed_btn')}">${ic('skull')}</button>
        ${b.killed != null ? `<button class="ib" data-clear="${b.code}" title="${t('b_clear')}">${ic('x')}</button>` : '<span class="tb-gap"></span>'}
      </div>`;
    }).join('');
    box.innerHTML = `
      <div class="rift-card">
        <div class="rc-h">${ic('clock')}<b>${t('rift')}</b><span class="sp"></span><span class="rc-state" id="rc-state"></span></div>
        <div class="rc-big num" id="rc-big"></div>
        <div class="rc-sub" id="rc-sub"></div>
        <div class="rc-next">${t('rift_later')}: ${nextList}</div>
      </div>
      <div class="tb-bar">
        <div class="seg" id="tb-fac"><button data-v="Elyos" class="${fac === 'Elyos' ? 'on' : ''}">Elyos</button><button data-v="Asmodian" class="${fac === 'Asmodian' ? 'on' : ''}">Asmodian</button></div>
        <span class="sp"></span>
        <select id="tb-reg" title="${t('region')}">${regions}</select>
      </div>
      <div class="tb-list">${rows}</div>
      <div class="tb-note">${seen ? t('b_live_seen', clockIn(seen)) + ' ' : ''}${t('b_source')}</div>`;
    box.querySelector('#tb-fac').onclick = e => {
      const b = e.target.closest('button[data-v]');
      if (!b) return;
      tmFaction = b.dataset.v;
      act('settings', { values: { faction: b.dataset.v } });
      renderTimers();
    };
    box.querySelector('#tb-reg').onchange = e => act('settings', { values: { region: e.target.value } }).then(refresh);
    box.querySelectorAll('[data-kill]').forEach(el => el.onclick = () =>
      act('boss_kill', { code: +el.dataset.kill }).then(() => loadTimers(true)).then(renderTimers));
    box.querySelectorAll('[data-clear]').forEach(el => el.onclick = () =>
      act('boss_clear', { code: +el.dataset.clear }).then(() => loadTimers(true)).then(renderTimers));
    box.querySelectorAll('[data-cyc]').forEach(el => el.onclick = () => { tmEdit = +el.dataset.cyc; renderTimers(); });
    const input = box.querySelector('[data-in]');
    if (input) {
      input.focus();
      input.select();
      const save = () => {
        const code = +input.dataset.in, minutes = Math.round(+input.value);
        tmEdit = null;
        if (minutes > 0) act('boss_cycle', { code, minutes }).then(() => loadTimers(true)).then(renderTimers);
        else renderTimers();
      };
      input.onkeydown = e => { if (e.key === 'Enter') save(); else if (e.key === 'Escape') { tmEdit = null; renderTimers(); } };
      input.onblur = save;
    }
  }
  // every tick: countdowns and the rift card
  box.querySelectorAll('[data-cd]').forEach(el => txt(el, dur(+el.dataset.cd - now)));
  const r = riftNow();
  if (r) {
    txt($('rc-big'), dur(r.left));
    txt($('rc-state'), r.open ? t('rift_open') : t('rift_next'));
    $('rc-state').classList.toggle('open', r.open);
    const dom = isDomination(TM.rift, r.at, tz) ? ' · ' + t('domination') : '';
    txt($('rc-sub'), t('rift_at', clockIn(r.at), clockIn(r.at, tz)) + dom);
  }
}
