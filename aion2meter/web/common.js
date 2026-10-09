/* Shared by the overlay and the analysis window: API, language, number formats, icons. */
'use strict';

const TOKEN = new URLSearchParams(location.search).get('t') || '';
const APP_NAME = 'Combat Lens';

async function api(route, params) {
  const u = new URL('/api/' + route, location.origin);
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== '') u.searchParams.set(k, v);
  const r = await fetch(u, { headers: { 'X-Token': TOKEN }, cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

async function act(op, extra) {
  const r = await fetch('/api/action', {
    method: 'POST', headers: { 'X-Token': TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.assign({ op }, extra || {})),
  });
  return r.json();
}

/* ───────── language ───────── */

const STR = {
  tr: {
    me: 'Ben', party: 'Parti', all_targets: 'Tüm hedefler', main_target: 'Ana hedef',
    pause: 'Durdur', resume: 'Başlat', reset: 'Sıfırla', analysis: 'Savaş analizi',
    settings: 'Ayarlar', fold: 'Şeride küçült', unfold: 'Genişlet', close: 'Kapat', minimize: 'Simge durumuna küçült',
    maximize: 'Büyüt', you: 'SEN', live: 'CANLI', boss: 'BOSS', paused: 'Duraklatıldı — hasar sayılmıyor',
    waiting_game: 'Oyun bekleniyor…', waiting_game_sub: 'AION 2 açıkken bağlantı birkaç saniyede bulunur.',
    waiting_fight: 'Savaş bekleniyor', waiting_fight_sub: 'Bir hedefe vurduğunda sayılar burada belirir.',
    me_empty: 'Bu savaşta senin hasarın yok', me_empty_sub: 'Karakterin henüz tanınmadıysa birkaç vuruş yeterli.',
    targets: '{0} hedef', fights: 'Savaş {0}/{1}', prev: 'Önceki savaş', next: 'Sonraki savaş',
    npcap_title: 'Npcap gerekli', npcap_body: 'Hasarı okumak için ücretsiz Npcap sürücüsü gerekiyor. Kurulumda “WinPcap API-compatible Mode” kutusu işaretli kalsın.',
    npcap_get: 'Npcap’i indir', retry: 'Tekrar dene',
    update_data: 'Veriyi güncelle',
    update_avail: 'Yeni sürüm: v{0}', guess: 'Karakterin tahmini — birkaç vuruşta kesinleşir',
    name_unknown: 'Adın henüz bilinmiyor: meter açıkken bir kez teleport ol ya da bölge değiştir. Sonra hep hatırlanır.',
    update_now: 'Güncelle', updating: 'Güncelleniyor', up_failed: 'Güncelleme tamamlanamadı',
    up_download: 'İndiriliyor', up_verify: 'Doğrulanıyor…', up_install: 'Kuruluyor…', up_restart: 'Yeniden başlatılıyor…',
    up_note: 'Bitince uygulama kendiliğinden yeniden açılır. Ayarların ve geçmişin olduğu gibi kalır.',
    up_page: 'İndirme sayfası', updated_to: 'Combat Lens v{0} sürümüne güncellendi',
    check_updates: 'Güncellemeleri denetle', up_to_date: 'Güncelsin (v{0})',
    update_check_failed: 'Güncelleme denetlenemedi: internet bağlantını kontrol et',
    up_source: 'kaynak koddan çalışıyor, indirme sayfasından al',
    clickthrough_on: 'Tıklama geçirgen — kapatmak için {0}', party_unknown: 'Parti listesi yok: etraftaki herkes',
    connected: 'Bağlı', not_connected: 'Bağlantı yok', replay: 'Kayıt', demo: 'Demo',
    welcome_title: 'Hoş geldin!', welcome_1: 'Oyuna hiçbir şekilde dokunmaz: yalnızca bilgisayarına gelen ağ trafiğini okur.',
    welcome_2: 'Her boss bitince sayılar kendiliğinden sıfırlanır; geçmiş savaşlar Analiz’de saklanır.',
    welcome_3: 'Kısayollar: {0} sıfırla · {1} küçült · {2} tıklama geçirgen.', welcome_ok: 'Anladım',
    welcome_risk: 'Üçüncü parti araçlar oyunun kurallarına aykırı sayılabilir; kullanım riski sana aittir.',
    s_language: 'Dil', s_scale: 'Boyut', s_opacity: 'Saydamlık', s_mode: 'Sayım', s_clickthrough: 'Tıklama geçirgen mod',
    s_clickthrough_sub: 'Tıklamalar oyuna geçer. Kısayolla geri alınır.', s_hotkeys: 'Kısayollar',
    s_updates: 'Güncellemeleri denetle', s_data: 'Oyun verisi (skill / NPC adları)', s_folder: 'Veri klasörünü aç',
    s_back: 'Geri', s_version: 'Sürüm {0}', s_hotkey_failed: 'kullanımda', s_data_started: 'Veri güncelleniyor…',
    hk_reset: 'Sıfırla', hk_pause: 'Durdur / başlat', hk_fold: 'Küçült / genişlet', hk_hide: 'Gizle / göster',
    hk_clickthrough: 'Tıklama geçirgen', hk_analysis: 'Analiz penceresi',
    a_title: 'Savaş Analizi', history: 'Geçmiş', h_all: 'Tümü', h_fav: 'Favoriler', today: 'Bugün', yesterday: 'Dün',
    h_empty: 'Henüz kayıtlı savaş yok', h_fav_empty: 'Yıldızladığın savaşlar burada durur',
    no_fight: 'Bir savaş seç', no_fight_sub: 'Soldaki listeden bir savaş seç ya da bir hedefe vur.',
    party_dmg: 'Parti hasarı', player: 'Oyuncu', total: 'Toplam', dps: 'DPS', share: 'Pay', crit: 'Kritik',
    battle_time: 'Savaş süresi', hits: 'Vuruş', back: 'Arka', front: 'Ön', perfect: 'Mükemmel', double: 'Çift',
    parry: 'Savuşturma', smite: 'Smite', max_hit: 'Maks vuruş', dot: 'DoT hasarı', heal: 'İyileştirme',
    skills: 'Yetenekler', skill: 'Yetenek', multi: 'Çoklu', max: 'Maks', avg: 'Ort.', min: 'Min',
    curve: 'DPS eğrisi', curve_sub: '5 sn ortalama', targets_t: 'Hedefler', heals_t: 'İyileştirme',
    no_heals: 'Bu savaşta iyileştirme yok', copy_text: 'Metni kopyala', copy_image: 'Görseli kopyala',
    heal_skills: 'İyileştirme yetenekleri', hot_tag: 'HoT', heal_note: 'Sadece sınıf yetenekleri sayılır; iksirler ve eşyalar sayılmaz. HoT: zamanla iyileştiren etki, her tiki ayrı sayılır.',
    copied: 'Panoya kopyalandı — Discord’a yapıştırabilirsin', saved: 'Görsel kaydedildi: {0}',
    star: 'Favorilere ekle', unstar: 'Favorilerden çıkar', del: 'Sil', del_confirm: 'Bu savaş geçmişten silinsin mi?',
    shared_time: 'Parti süresi', own_time: 'Kişisel süre', dead: 'öldü', hp: 'Can',
    end_boss: 'boss öldü', end_idle: 'zaman aşımı', end_reset: 'sıfırlandı', end_zone: 'bölge değişti', end_paused: 'durduruldu',
    heal_col: 'Heal', dot_tag: 'DoT', ticks: 'tik', of_party: 'partinin', players_n: '{0} oyuncu', open_world: 'Açık dünya',
    timers: 'Boss ve Rift sayaçları', rift: 'Space Rift', rift_next: 'sonraki', rift_open: 'açık',
    rift_at: 'Saat {0} (sunucu {1})', rift_later: 'Sonra', domination: 'Domination',
    rift_soon_note: 'Space Rift {0} sonra açılıyor', rift_open_note: 'Space Rift açık: girişin kapanmasına {0}',
    region: 'Sunucu', reg_eu: 'Avrupa', reg_naw: 'K. Amerika Batı', reg_nae: 'K. Amerika Doğu', reg_jp: 'Japonya',
    reg_kr: 'Kore', reg_tw: 'Tayvan', h_short: 'sa', min_short: 'dk',
    b_unk: 'Bilinmiyor', b_due: 'Çıkıyor', b_up: 'Çıkmış olmalı', b_died: 'Öldü: {0}',
    b_on: 'Çıktı', b_on_at: 'Çıkış {0}', b_game: 'oyundan', b_live_seen: 'Süreler oyundan alındı (son: {0}).',
    b_open_map: 'Süreler için oyunda haritayı aç ve Field Boss listesine bak; birkaç saniyede burada görünür.',
    apps: 'Başvurular ({0})', apps_hint: 'kabul / red oyunda', apps_dismiss: 'Listeden kaldır',
    b_killed_btn: 'Şimdi öldü olarak işaretle', b_clear: 'Sayacı sıfırla', b_cycle: 'Çıkma süresi: değiştirmek için tıkla (dakika)',
    b_source: 'Oyunda haritadan Field Boss listesini açınca süreler doğrudan oyundan gelir. Diğerleri öldükten sonra sayılır (kaynak: AION 2 Guides); meter yanında ölen bossu kendisi görür, görmediklerini kurukafa ile işaretle.',
    s_clear_after: 'Biten savaş panelde kalsın', s_clear_after_sub: 'Süre dolunca panel temizlenir; savaş geçmişte kayıtlı kalır. Kapalı: bir sonraki savaşa kadar kalır.',
    s_off: 'Kapalı', s_sec: '{0} sn', s_min: '{0} dk',
  },
  en: {
    me: 'Me', party: 'Party', all_targets: 'All targets', main_target: 'Main target',
    pause: 'Pause', resume: 'Resume', reset: 'Reset', analysis: 'Fight analysis',
    settings: 'Settings', fold: 'Fold to strip', unfold: 'Expand', close: 'Close', minimize: 'Minimize',
    maximize: 'Maximize', you: 'YOU', live: 'LIVE', boss: 'BOSS', paused: 'Paused — damage is not counted',
    waiting_game: 'Waiting for the game…', waiting_game_sub: 'With AION 2 running the connection is found in seconds.',
    waiting_fight: 'Waiting for a fight', waiting_fight_sub: 'Hit something and the numbers show up here.',
    me_empty: 'No damage from you in this fight', me_empty_sub: 'If your character is not known yet, a few hits will do.',
    targets: '{0} targets', fights: 'Fight {0}/{1}', prev: 'Previous fight', next: 'Next fight',
    npcap_title: 'Npcap required', npcap_body: 'Reading damage needs the free Npcap driver. Keep “WinPcap API-compatible Mode” ticked while installing.',
    npcap_get: 'Get Npcap', retry: 'Try again',
    update_data: 'Update data',
    update_avail: 'New version: v{0}', guess: 'Character guessed — confirmed after a few hits',
    name_unknown: 'Your name is not known yet: teleport or change zone once with the meter open. It is remembered after that.',
    update_now: 'Update', updating: 'Updating', up_failed: 'The update did not finish',
    up_download: 'Downloading', up_verify: 'Verifying…', up_install: 'Installing…', up_restart: 'Restarting…',
    up_note: 'The app reopens by itself when done. Your settings and history stay as they are.',
    up_page: 'Download page', updated_to: 'Combat Lens updated to v{0}',
    check_updates: 'Check for updates', up_to_date: 'Up to date (v{0})',
    update_check_failed: 'Could not check for updates: check your connection',
    up_source: 'running from source, get it from the download page',
    clickthrough_on: 'Click-through — {0} to turn off', party_unknown: 'No party list: everyone around',
    connected: 'Connected', not_connected: 'Not connected', replay: 'Replay', demo: 'Demo',
    welcome_title: 'Welcome!', welcome_1: 'Never touches the game: it only reads network traffic arriving at your PC.',
    welcome_2: 'Numbers reset by themselves after each boss; past fights are kept in Analysis.',
    welcome_3: 'Hotkeys: {0} reset · {1} fold · {2} click-through.', welcome_ok: 'Got it',
    welcome_risk: 'Third-party tools may break the game’s rules; use at your own risk.',
    s_language: 'Language', s_scale: 'Size', s_opacity: 'Opacity', s_mode: 'Counting', s_clickthrough: 'Click-through mode',
    s_clickthrough_sub: 'Clicks go to the game. Undo with the hotkey.', s_hotkeys: 'Hotkeys',
    s_updates: 'Check for updates', s_data: 'Game data (skill / NPC names)', s_folder: 'Open data folder',
    s_back: 'Back', s_version: 'Version {0}', s_hotkey_failed: 'in use', s_data_started: 'Updating data…',
    hk_reset: 'Reset', hk_pause: 'Pause / resume', hk_fold: 'Fold / expand', hk_hide: 'Hide / show',
    hk_clickthrough: 'Click-through', hk_analysis: 'Analysis window',
    a_title: 'Fight Analysis', history: 'History', h_all: 'All', h_fav: 'Favorites', today: 'Today', yesterday: 'Yesterday',
    h_empty: 'No fights saved yet', h_fav_empty: 'Fights you star stay here',
    no_fight: 'Pick a fight', no_fight_sub: 'Choose one on the left, or go hit something.',
    party_dmg: 'Party damage', player: 'Player', total: 'Total', dps: 'DPS', share: 'Share', crit: 'Critical',
    battle_time: 'Battle time', hits: 'Hits', back: 'Back', front: 'Front', perfect: 'Perfect', double: 'Double',
    parry: 'Parried', smite: 'Smite', max_hit: 'Max hit', dot: 'DoT damage', heal: 'Healing',
    skills: 'Skills', skill: 'Skill', multi: 'Multi', max: 'Max', avg: 'Avg', min: 'Min',
    curve: 'DPS curve', curve_sub: '5 s average', targets_t: 'Targets', heals_t: 'Healing',
    no_heals: 'No healing in this fight', copy_text: 'Copy text', copy_image: 'Copy image',
    heal_skills: 'Healing skills', hot_tag: 'HoT', heal_note: 'Class skills only; potions and items are not counted. HoT: healing over time, each tick counted.',
    copied: 'Copied — paste it into Discord', saved: 'Image saved: {0}',
    star: 'Add to favorites', unstar: 'Remove from favorites', del: 'Delete', del_confirm: 'Delete this fight from history?',
    shared_time: 'Party time', own_time: 'Own time', dead: 'dead', hp: 'HP',
    end_boss: 'boss down', end_idle: 'idle', end_reset: 'reset', end_zone: 'zone change', end_paused: 'paused',
    heal_col: 'Heal', dot_tag: 'DoT', ticks: 'ticks', of_party: 'of party', players_n: '{0} players', open_world: 'Open world',
    timers: 'Boss and Rift timers', rift: 'Spacetime Rift', rift_next: 'next', rift_open: 'open',
    rift_at: 'At {0} (server {1})', rift_later: 'Later', domination: 'Domination',
    rift_soon_note: 'Spacetime Rift opens in {0}', rift_open_note: 'Spacetime Rift is open: entrance closes in {0}',
    region: 'Server', reg_eu: 'Europe', reg_naw: 'NA West', reg_nae: 'NA East', reg_jp: 'Japan',
    reg_kr: 'Korea', reg_tw: 'Taiwan', h_short: 'h', min_short: 'min',
    b_unk: 'Unknown', b_due: 'Spawning', b_up: 'Should be up', b_died: 'died {0}',
    b_on: 'Up', b_on_at: 'since {0}', b_game: 'from the game', b_live_seen: 'Times from the game (last: {0}).',
    b_open_map: 'For the times, open the map in game and look at the Field Boss list; they show up here within seconds.',
    apps: 'Applicants ({0})', apps_hint: 'accept / decline in game', apps_dismiss: 'Remove from the list',
    b_killed_btn: 'Mark as killed now', b_clear: 'Clear the timer', b_cycle: 'Respawn time: click to change (minutes)',
    b_source: 'Open the Field Boss list on the in-game map and the times come straight from the game. The others are counted from the kill (source: AION 2 Guides); the meter sees a boss die near you by itself, mark the others with the skull.',
    s_clear_after: 'Keep a finished fight on the panel', s_clear_after_sub: 'Then the panel clears; the fight stays in history. Off: it stays until the next fight.',
    s_off: 'Off', s_sec: '{0} s', s_min: '{0} min',
  },
};

// the interface size from the settings; the window's own size follows it on the app side
function applyScale(z) {
  z = Math.min(1.1, Math.max(0.8, +z || 1));
  if (document.documentElement.style.zoom !== String(z)) document.documentElement.style.zoom = z;
}
applyScale(new URLSearchParams(location.search).get('z') || 1);

let LANG = 'tr';
function setLang(l) { LANG = STR[l] ? l : 'tr'; document.documentElement.lang = LANG; }
function t(key, ...args) {
  let s = (STR[LANG] && STR[LANG][key]) || STR.tr[key] || key;
  args.forEach((a, i) => { s = s.replace('{' + i + '}', a); });
  return s;
}

/* ───────── numbers ───────── */

function dec(s) { return LANG === 'tr' ? s.replace('.', ',') : s; }
function fmtNum(v) {
  v = Number(v) || 0;
  const a = Math.abs(v);
  if (a >= 1e9) return dec((v / 1e9).toFixed(2)) + 'B';
  if (a >= 1e6) return dec((v / 1e6).toFixed(2)) + 'M';
  if (a >= 1e4) return dec((v / 1e3).toFixed(1)) + 'K';
  if (a >= 1e3) return dec((v / 1e3).toFixed(2)) + 'K';
  return String(Math.round(v));
}
function fmtFull(v) {
  return Math.round(Number(v) || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, LANG === 'tr' ? '.' : ',');
}
function fmtPct(v, d = 1) {
  const s = dec((Number(v) || 0).toFixed(d));
  return LANG === 'tr' ? '%' + s : s + '%';
}
function fmtTime(ms) {
  const s = Math.floor((ms || 0) / 1000);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
function fmtDate(ms) {
  const d = new Date(ms);
  return d.toLocaleDateString(LANG === 'tr' ? 'tr-TR' : 'en-GB') + ' ' +
    d.toLocaleTimeString(LANG === 'tr' ? 'tr-TR' : 'en-GB', { hour: '2-digit', minute: '2-digit' });
}
function fmtClock(ms) {
  return new Date(ms).toLocaleTimeString(LANG === 'tr' ? 'tr-TR' : 'en-GB', { hour: '2-digit', minute: '2-digit' });
}

/* ───────── classes ───────── */

const CLASS = {
  GL: { name: 'Gladiator', color: '#f0a54a' },
  TE: { name: 'Templar', color: '#5ea8ff' },
  AS: { name: 'Assassin', color: '#b77bff' },
  RA: { name: 'Ranger', color: '#62d36f' },
  SO: { name: 'Sorcerer', color: '#ff6b81' },
  EL: { name: 'Spiritmaster', color: '#f27ad6' },
  CL: { name: 'Cleric', color: '#f5d36b' },
  CH: { name: 'Chanter', color: '#3fd8c8' },
  GT: { name: 'Brawler', color: '#ff8a4c' },
};
const NO_CLASS = { name: '?', color: '#8c87a6' };
function cls(job) { return CLASS[job] || NO_CLASS; }

function emblem(job, size) {
  const c = cls(job);
  const st = `background:linear-gradient(145deg, ${c.color}55, ${c.color}18);box-shadow:inset 0 0 0 1px ${c.color}66` +
    (size ? `;width:${size}px;height:${size}px` : '');
  if (!CLASS[job]) return `<div class="emblem unk" style="${size ? `width:${size}px;height:${size}px` : ''}">?</div>`;
  return `<div class="emblem" style="${st}"><img src="/classes/${job}.png" alt=""></div>`;
}

/* ───────── icons ───────── */

const ICON = {
  pause: '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
  play: '<path d="M7 5v14l11-7z"/>',
  reset: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  chart: '<path d="M4 20V11M10 20V5M16 20v-6M21 20H3"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  minus: '<path d="M5 12h14"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  left: '<path d="m15 18-6-6 6-6"/>',
  right: '<path d="m9 18 6-6-6-6"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  square: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
  star: '<path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
  // the boss mark on the overlay's target card: a horned skull, filled
  boss: '<path d="M5 3.5c-.3 3.4.9 6 3.4 7.3" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>' +
    '<path d="M19 3.5c.3 3.4-.9 6-3.4 7.3" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>' +
    '<path d="M12 7c-3.9 0-6.4 2.7-6.4 6.3 0 2.2 1 3.8 2.6 4.8V21h7.6v-2.9c1.6-1 2.6-2.6 2.6-4.8C18.4 9.7 15.9 7 12 7z" fill="currentColor"/>' +
    '<path d="M8.4 12.8l2.7 1.1v1.3H8.9zM15.6 12.8l-2.7 1.1v1.3h2.2z" fill="#2a0a10"/>' +
    '<path d="M10.6 21v-1.8M13.4 21v-1.8" stroke="#2a0a10" stroke-width="1.2"/>',
  skull: '<path d="M12 3a8 8 0 0 0-8 8c0 2.8 1.5 4.6 3 5.6V20h10v-3.4c1.5-1 3-2.8 3-5.6a8 8 0 0 0-8-8z"/><circle cx="9" cy="11.5" r="1.5"/><circle cx="15" cy="11.5" r="1.5"/>',
  sword: '<path d="M14.5 17.5 3 6V3h3l11.5 11.5M13 19l6-6M16 16l4 4M19 21l2-2"/>',
  pointer: '<path d="M5 3l6.5 17 2.4-7.1L21 10.5z"/>',
  link: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  heart: '<path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  sync: '<path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
  alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
  wifi: '<path d="M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  question: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17h.01"/>',
};
function ic(name, extra) { return `<svg viewBox="0 0 24 24"${extra ? ' ' + extra : ''}>${ICON[name] || ''}</svg>`; }

// The mark: a meter dial whose needle is a blade. Each copy gets its own gradient id
// (a gradient inside a hidden copy would not paint the others).
let _logoN = 0;
const logo = () => {
  const id = 'lgD' + (++_logoN);
  return `<svg viewBox="0 0 32 32" class="logo"><defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="0">
<stop offset="0" stop-color="#ffd27a"/><stop offset=".5" stop-color="#f5a524"/><stop offset="1" stop-color="#ff6b3d"/></linearGradient></defs>
<path d="M6.99 25.31A11 11 0 1 1 25.01 25.31" fill="none" stroke="url(#${id})" stroke-width="3.6" stroke-linecap="round"/>
<path d="M17.07 19.9 21.14 12.87 14.93 18.1z" fill="#fff"/>
<circle cx="16" cy="19" r="2.7" fill="#fff"/><circle cx="16" cy="19" r="1" fill="#17171c"/></svg>`;
};

function skillIcon(icon) {
  if (icon && icon.startsWith('/icon/')) return `<img class="skill-ic" src="${icon}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'skill-ic',innerHTML:'${ic('question').replace(/"/g, '&quot;')}'}))">`;
  return `<div class="skill-ic">${ic(icon === 'basic' ? 'sword' : 'question')}</div>`;
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ───────── small helpers ───────── */

let _toastTimer = null;
function toast(msg) {
  let el = document.querySelector('.toast');
  if (!el) { el = document.createElement('div'); el.className = 'toast'; document.body.appendChild(el); }
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

/* Bottom-right grip: resizes the native (frameless) window. */
function makeGrip(el, win, opts) {
  opts = opts || {};
  let start = null, pending = null, busy = false;
  const flush = async () => {
    if (busy || !pending) return;
    busy = true;
    const p = pending; pending = null;
    try { await act('resize', { win, w: p.w, h: p.h }); } catch (e) { /* ignore */ }
    busy = false;
    if (pending) flush();
  };
  el.addEventListener('pointerdown', e => {
    e.preventDefault(); e.stopPropagation();
    el.setPointerCapture(e.pointerId);
    start = { x: e.screenX, y: e.screenY, w: window.innerWidth, h: window.innerHeight };
  });
  el.addEventListener('pointermove', e => {
    if (!start) return;
    const w = Math.round(start.w + e.screenX - start.x);
    const h = opts.fixedHeight ? window.innerHeight : Math.round(start.h + e.screenY - start.y);
    pending = { w, h };
    flush();
  });
  const end = () => { start = null; };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
}

document.addEventListener('contextmenu', e => e.preventDefault());

/* ───────── share card (Discord) ───────── */

function _img(src) {
  return new Promise(res => { const i = new Image(); i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
}
function _rr(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
function _fit(g, text, w) {
  if (g.measureText(text).width <= w) return text;
  while (text.length > 1 && g.measureText(text + '…').width > w) text = text.slice(0, -1);
  return text + '…';
}

async function renderShareCard(d) {
  const players = d.players.slice(0, 12);
  const W = 680, RH = 40, HEAD = 92, FOOT = 34, S = 2;
  const H = HEAD + players.length * RH + FOOT + 14;
  const c = document.createElement('canvas');
  c.width = W * S; c.height = H * S;
  const g = c.getContext('2d');
  g.scale(S, S);
  const F = '"Segoe UI Variable Text","Segoe UI",sans-serif';

  _rr(g, 0, 0, W, H, 16); g.fillStyle = '#121119'; g.fill();
  const bg = g.createLinearGradient(0, 0, W, HEAD);
  bg.addColorStop(0, 'rgba(155, 107, 255,.30)'); bg.addColorStop(.6, 'rgba(91, 124, 255,.12)'); bg.addColorStop(1, 'rgba(46, 230, 197,.10)');
  g.save(); _rr(g, 0, 0, W, H, 16); g.clip(); g.fillStyle = bg; g.fillRect(0, 0, W, HEAD); g.restore();
  g.strokeStyle = '#2c2840'; g.lineWidth = 1; _rr(g, .5, .5, W - 1, H - 1, 16); g.stroke();

  const title = d.multi ? t('targets', d.multi) : d.title;
  g.fillStyle = '#fff'; g.font = `700 22px ${F}`; g.textBaseline = 'alphabetic';
  g.fillText(_fit(g, title, W - 260), 22, 40);
  g.fillStyle = '#b9b5cc'; g.font = `500 13px ${F}`;
  const sub = [d.zone, fmtTime(d.duration_ms), fmtDate(d.start)].filter(Boolean).join('  ·  ');
  g.fillText(_fit(g, sub, W - 260), 22, 64);
  g.textAlign = 'right';
  g.fillStyle = '#fff'; g.font = `800 24px ${F}`;
  g.fillText(fmtNum(d.total_dps), W - 22, 40);
  g.fillStyle = '#b9b5cc'; g.font = `600 12px ${F}`;
  g.fillText(t('party') + ' DPS  ·  ' + fmtNum(d.total), W - 22, 62);
  g.textAlign = 'left';

  const top = Math.max(1, ...players.map(p => p.dps));
  const imgs = await Promise.all(players.map(p => CLASS[p.job] ? _img(`/classes/${p.job}.png`) : null));
  players.forEach((p, i) => {
    const y = HEAD + i * RH + 4, c0 = cls(p.job).color;
    _rr(g, 14, y, W - 28, RH - 6, 9); g.fillStyle = '#1a1824'; g.fill();
    const bw = (W - 28) * p.dps / top;
    const gr = g.createLinearGradient(14, 0, 14 + bw, 0);
    gr.addColorStop(0, c0 + '66'); gr.addColorStop(1, c0 + '1c');
    g.save(); _rr(g, 14, y, W - 28, RH - 6, 9); g.clip(); g.fillStyle = gr; g.fillRect(14, y, bw, RH - 6); g.restore();
    g.fillStyle = '#8f8aa8'; g.font = `700 12px ${F}`; g.fillText(String(i + 1), 26, y + 22);
    if (imgs[i]) g.drawImage(imgs[i], 44, y + 5, 24, 24);
    g.fillStyle = '#fff'; g.font = `700 14px ${F}`;
    g.fillText(_fit(g, p.name, 240), 78, y + 16);
    g.fillStyle = '#b3aec8'; g.font = `500 11px ${F}`;
    g.fillText(cls(p.job).name + (p.is_local ? '  ·  ' + t('you') : ''), 78, y + 29);
    if (p.heal) {
      const cx = 78 + g.measureText(cls(p.job).name + (p.is_local ? '  ·  ' + t('you') : '') + '  ').width;
      g.fillStyle = '#7ff0b4'; g.font = `700 11px ${F}`;
      g.fillText('♥ ' + fmtNum(p.heal), cx, y + 29);
    }
    g.textAlign = 'right';
    g.fillStyle = '#fff'; g.font = `800 15px ${F}`; g.fillText(fmtNum(p.dps), W - 150, y + 22);
    g.fillStyle = '#c9c5da'; g.font = `600 12px ${F}`; g.fillText(fmtNum(p.total), W - 84, y + 22);
    g.fillStyle = c0; g.font = `800 13px ${F}`; g.fillText(fmtPct(p.pct), W - 26, y + 22);
    g.textAlign = 'left';
  });
  const fy = H - FOOT + 10;
  g.fillStyle = '#7d7895'; g.font = `600 11.5px ${F}`;
  g.fillText(APP_NAME, 22, fy + 8);
  g.textAlign = 'right';
  g.fillText(d.shared_time ? t('shared_time') : t('own_time'), W - 22, fy + 8);
  g.textAlign = 'left';
  return c;
}

async function copyShareImage(d) {
  const canvas = await renderShareCard(d);
  try {
    const blob = await new Promise(r => canvas.toBlob(r, 'image/png'));
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
    toast(t('copied'));
    return;
  } catch (e) { /* fall back to the native clipboard */ }
  const png = canvas.toDataURL('image/png');
  const r = await act('copy_image', { png });
  if (r && r.ok) { toast(t('copied')); return; }
  const s = await act('save_image', { png });
  if (s && s.path) toast(t('saved', s.path));
}

function shareText(d) {
  const title = d.multi ? t('targets', d.multi) : d.title;
  const head = `**${title}**` + [d.zone, fmtTime(d.duration_ms)].filter(Boolean).map(s => ' · ' + s).join('');
  const ps = d.players.slice(0, 12);
  const nw = Math.max(4, ...ps.map(p => p.name.length));
  const lines = ps.map((p, i) => [
    String(i + 1).padStart(2) + '.', p.name.padEnd(nw), cls(p.job).name.padEnd(12),
    (fmtNum(p.dps) + ' DPS').padStart(12), fmtNum(p.total).padStart(8), fmtPct(p.pct).padStart(7),
  ].join(' ') + (p.heal ? `  heal ${fmtNum(p.heal)}` : ''));
  return head + '\n```\n' + lines.join('\n') + '\n```\n' + `${t('party')} DPS ${fmtNum(d.total_dps)} · ${fmtNum(d.total)} — ${APP_NAME}`;
}

async function copyShareText(d) {
  const text = shareText(d);
  try { await navigator.clipboard.writeText(text); toast(t('copied')); return; } catch (e) { /* native */ }
  const r = await act('copy_text', { text });
  if (r && r.ok) toast(t('copied'));
}
