"""Who is who, and who hit what for how much.

Identity and attribution rules follow the A2Tools DataStorage/DpsCalculator
(GPL-3.0): players are recognised by class-band skills, summons fold into their
owner, player-on-player "damage" is a heal and is dropped, and a character that
comes back as a new entity keeps their damage.

Fights are split into encounters: one ends after IDLE_MS without damage from
you or your party, when a boss is pulled after trash, when the boss dies, or on
a zone change.
"""
import json
import os
from collections import deque
import threading
import time
from collections import Counter, defaultdict

from .paths import user_path
from .gamedata import is_player_skill, job_from_skill, job_from_skill_loose
from .protocol import BACK, CRIT, DOUBLE, FRONT, PARRY, PERFECT, POWERSHARD, SMITE

IDLE_MS = 20_000
ZONE_RESET_LULL_MS = 1_500
ZONE_RESET_DEBOUNCE_MS = 4_000
HISTORY_MAX = 30
ROSTER_BIND_EVERY = 64
NEVER = -(1 << 62)


class SkillAgg:
    __slots__ = ("hits", "total", "min", "max", "crit", "back", "front", "parry", "perfect",
                 "double", "smite", "powershard", "mh_events", "mh_hits", "mh_damage")

    def __init__(self):
        self.hits = 0
        self.total = 0
        self.min = None
        self.max = 0
        self.crit = self.back = self.front = self.parry = 0
        self.perfect = self.double = self.smite = self.powershard = 0
        self.mh_events = self.mh_hits = self.mh_damage = 0

    def absorb(self, o):
        self.hits += o.hits
        self.total += o.total
        if o.min is not None and (self.min is None or o.min < self.min):
            self.min = o.min
        self.max = max(self.max, o.max)
        for f in ("crit", "back", "front", "parry", "perfect", "double", "smite", "powershard",
                  "mh_events", "mh_hits", "mh_damage"):
            setattr(self, f, getattr(self, f) + getattr(o, f))


class ActorAgg:
    __slots__ = ("total", "first", "last", "skills", "buckets")

    def __init__(self, ts):
        self.total = 0
        self.first = ts
        self.last = ts
        self.skills = {}
        self.buckets = {}  # epoch second -> damage, for the DPS curve


class TargetAgg:
    __slots__ = ("id", "first", "last", "total", "actors")

    def __init__(self, tid, ts):
        self.id = tid
        self.first = ts
        self.last = ts
        self.total = 0
        self.actors = {}


class Encounter:
    _next_id = 1

    def __init__(self, ts, zone=None):
        # Unique across runs too, since fights are kept on disk (history).
        self.id = f"{ts}-{Encounter._next_id}"
        Encounter._next_id += 1
        self.start = ts
        self.last = ts
        self.targets = {}
        self.heals = {}  # healer actor -> {(skill, is_hot): SkillAgg}
        self.has_boss = False
        self.end_reason = None
        self.zone = zone  # dungeon name when the party roster told us
        self.frozen = None  # resolved view, taken when the encounter ends


def _resolve_chain(eid, links):
    seen = set()
    hops = 0
    while hops < 16 and eid not in seen:
        seen.add(eid)
        nxt = links.get(eid)
        if nxt is None or nxt <= 0:
            break
        eid = nxt
        hops += 1
    return eid


PROFILE_PATH = user_path("son_karakter.json")
NAMES_PATH = user_path("isim_onbellek.json")
NAMES_MAX_AGE_S = 3 * 3600
ACCOUNTS_PATH = user_path("oyuncu_hesaplari.json")
ACCOUNTS_MAX = 50_000
PARTY_MARKER_FRESH_MS = 120_000
SCOPE_MIN_RECORDS = 10
SCOPE_LEAD = 3
NAMES_SAVE_EVERY_S = 20
SELF_MARK_MIN = 3
SELF_MARK_LEAD = 3
POSITION_MIN_VOTES = 5
POSITION_LEAD = 4
BOSS_MIN_HP = 1_000_000
BOSS_HP_RATIO = 40
BOSS_MIN_SAMPLES = 8
BOSS_SWITCH_MS = 15_000  # a boss not hit for this long no longer holds the fight together
APPLICANT_TTL_MS = 10 * 60_000  # a join request nobody answered is gone from the game by then
AMBIGUOUS = object()  # a position key seen for two different members / entities


def _load_name_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - float(data.get("saved", 0)) > NAMES_MAX_AGE_S:
            return None
        return {"local_id": int(data["local_id"]),
                "names": {int(k): str(v) for k, v in data.get("names", {}).items()}}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _load_accounts(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {int(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _load_profile(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("name") else None
    except (OSError, ValueError):
        return None


class Store:
    def __init__(self, gamedata, profile_path=PROFILE_PATH, names_path=None, accounts_path=None):
        self.gd = gamedata
        # Account id (dbid) -> character name, from spawns and party rosters.
        # Account ids never change, so this book is kept for good: a party
        # member seen once is named from then on, even when the roster is not
        # re-sent and their spawn came before the meter was started.
        self.accounts_path = accounts_path
        self.dbid_names = _load_accounts(accounts_path) if accounts_path else {}
        self._accounts_dirty = False
        self._accounts_saved_at = 0.0
        self.entity_dbid = {}
        self.dbid_entity = {}
        self.party_dbids = {}  # dbid -> last time its party map marker was seen
        # Names seen by an earlier run, reused while you are still in the same
        # zone instance (your entity id is the same). Off unless asked for:
        # the window passes NAMES_PATH, replays and tests do not.
        self.names_path = names_path
        self.name_cache = _load_name_cache(names_path) if names_path else None
        self._names_saved_at = 0.0
        self._names_saved_count = -1
        self.lock = threading.RLock()
        self.now = 0  # packet clock (ms), set by the dispatcher

        # identity
        self.nicknames = {}
        self.authoritative = set()
        self.spawn_named = set()  # named by the game's own spawn / self record
        self.aliases = {}  # stale entity id -> the id the same character has now
        self.local_id = None
        self.local_name = None
        self.local_from_game = False
        self.self_profile = None  # (name, job, level, server)
        self.profile_path = profile_path
        # The character the game last named as you, from an earlier session.
        self.saved_profile = _load_profile(profile_path) if profile_path else None
        self.party_scope = Counter()
        # Local-player HP-feed records (`8D <id> 01 01 01`) since the last
        # zone load: they name only you, so they say who you are until the
        # game's self record does.
        self.self_marks = Counter()
        # `06 38` records since the last zone load. They name you and things
        # around you (a nearby Spiritmaster's spirit got them too), so they are
        # only a fallback, counted for players with a class.
        self.scope_recent = Counter()
        self.loot_owners = {}  # name -> [entity id, set(mob ids)]
        self.loot_applied = False
        self.roster = {}
        self.roster_by_dbid = {}  # account id -> character name
        self.party_pos = {}  # 8-byte (x, y) of a party map marker -> account id
        self.entity_pos = {}  # 8-byte window from a movement record -> entity
        self.position_votes = Counter()
        self.roster_ts = 0
        self.dungeon_id = 0

        # entities
        self.known_players = set()
        self.summons = {}
        self.confirmed_summons = set()
        self.summon_spawns = set()
        self.mobs = {}
        self.mob_max_hp = {}
        self.mob_cur_hp = {}
        self.mob_spawn_hp = {}
        self.bosses = set()
        self.dummies = set()
        self.dead = set()
        self.boss_like = set()  # bosses found by HP, see _check_boss_like
        self.zone_hps = deque(maxlen=300)  # max HP of the zone's mobs
        self.low_ids = set()
        self.actor_jobs = {}
        self.power_scalars = defaultdict(set)
        self.hostile_targets = set()

        # combat
        self.current = None
        self.history = []
        self.paused = False  # "Durdur": damage is not counted; names are still learned
        self.on_end = None  # called with each finished fight (the app keeps them on disk)
        self.on_kill = None  # called with the NPC code of each mob seen dying (field boss timers)
        self.on_field_bosses = None  # called with (world, entries, ms) for each field boss list the game sends
        self.applicants = {}  # character id -> a request to join your listed party, until it is answered
        self.last_damage_ts = NEVER
        self.last_zone_reset = NEVER
        self.generation = 0
        self._since_roster_bind = 0
        self.records = 0

    # ───────── entity facts reported by the parser ─────────

    def note_low_id_entity(self, eid):
        if 1 <= eid < 100:
            self.low_ids.add(eid)

    def is_plausible_entity_id(self, eid):
        return eid >= 100 or (eid >= 1 and eid in self.low_ids)

    def note_summon_spawn(self, eid):
        with self.lock:
            self.summon_spawns.add(eid)
            self.dead.discard(eid)

    def is_mob(self, eid):
        return eid in self.mobs

    def is_confirmed_summon(self, eid):
        return eid in self.confirmed_summons

    def is_known_player(self, eid):
        return eid in self.known_players

    def is_damage_target(self, eid):
        cur = self.current
        return bool(cur and eid in cur.targets)

    def note_power_scalar(self, actor, scalar):
        s = self.power_scalars[actor]
        if len(s) < 16:
            s.add(scalar)

    def append_mob(self, eid, code):
        with self.lock:
            self.mobs[eid] = code
            self.aliases.pop(eid, None)
            self.dead.discard(eid)
            self.boss_like.discard(eid)
            if self.gd.is_boss(code):
                self.bosses.add(eid)
            if self.gd.is_dummy(code):
                self.dummies.add(eid)
            self._check_boss_like(eid)
            # Damage that arrived before the spawn may have filed this NPC as a player.
            if eid in self.known_players:
                self.known_players.discard(eid)
                cur = self.current
                if cur:
                    for t in cur.targets.values():
                        a = t.actors.pop(eid, None)
                        if a:
                            t.total -= a.total

    def append_mob_hp(self, eid, hp, cur=None):
        if hp > 0:
            self.mob_max_hp[eid] = hp
            self._note_zone_hp(eid, hp)
        if cur is not None:
            self.mob_spawn_hp[eid] = cur

    def set_mob_current_hp(self, eid, hp):
        self.mob_cur_hp[eid] = hp
        if hp > self.mob_max_hp.get(eid, 0):
            self.mob_max_hp[eid] = hp
            self._note_zone_hp(eid, hp)
        if hp == 0 and eid in self.mobs and eid not in self.dummies:
            # The HP feed reports 0 with the killing blow; the death record
            # follows about 4 s later (Tiere and Thamon, 2026-10-04).
            self.mark_dead(eid)

    def _note_zone_hp(self, eid, hp):
        if eid in self.mobs and eid not in self.dummies and eid not in self.bosses:
            self.zone_hps.append(hp)
        self._check_boss_like(eid)

    def _check_boss_like(self, eid):
        """A mob far above the zone's usual HP is a boss, even when the NPC table does not say so.

        Measured in a dungeon: ordinary mobs ~37K HP (median), elites 435K
        (12x), bosses 5.2M-276M (140x and up). 40x and a million HP keeps the
        elites out and every boss in."""
        mx = self.mob_max_hp.get(eid, 0)
        if (mx < BOSS_MIN_HP or eid not in self.mobs or eid in self.dummies
                or len(self.zone_hps) < BOSS_MIN_SAMPLES):
            return
        median = sorted(self.zone_hps)[len(self.zone_hps) // 2]
        if mx >= BOSS_HP_RATIO * median:
            self.boss_like.add(eid)

    def is_boss(self, eid):
        return eid in self.bosses or eid in self.boss_like

    def note_party_application(self, app):
        with self.lock:
            self.applicants.pop(app["id"], None)  # asking again puts them at the back, as in the game
            self.applicants[app["id"]] = dict(app, seen=self.now)

    def note_application_closed(self, char_id):
        with self.lock:
            self.applicants.pop(char_id, None)

    def pending_applicants(self):
        """The requests still waiting, first come first; old ones the game has surely dropped go."""
        with self.lock:
            for k in [k for k, a in self.applicants.items() if self.now - a["seen"] > APPLICANT_TTL_MS]:
                del self.applicants[k]
            return [dict(a, waited_ms=max(0, self.now - a["seen"])) for a in self.applicants.values()]

    def note_field_bosses(self, world, entries):
        if self.on_field_bosses is not None:
            try:
                self.on_field_bosses(world, entries, self.now)
            except Exception:
                pass

    def mark_dead(self, eid):
        with self.lock:
            if eid in self.dead:
                return
            self.dead.add(eid)
            if self.on_kill is not None and eid in self.mobs:
                try:
                    self.on_kill(self.mobs[eid])
                except Exception:
                    pass
            cur = self.current
            if cur and self.is_boss(eid) and eid in cur.targets:
                # The fight is over when its main boss (the one taking the most
                # damage) dies: a boss's adds and mechanic objects (Vakron's
                # thorn vines carry boss-size HP) must not keep it open.
                bosses = [t for t in cur.targets.values() if self.is_boss(t.id)]
                main = max(bosses, key=lambda t: t.total)
                if main.id == eid or all(t.id in self.dead for t in bosses):
                    self._end_encounter("kill")

    def register_confirmed_summon(self, summon, owner):
        with self.lock:
            self.confirmed_summons.add(summon)
            self.known_players.discard(summon)
            self.aliases.pop(summon, None)
            self.summons[summon] = owner
            self._purge_friendly()

    def append_summon(self, owner, summon):
        with self.lock:
            if summon in self.nicknames or summon in self.known_players or summon in self.hostile_targets:
                return
            if owner in self.summons:
                return
            if owner in self.mobs and owner not in self.summons:
                return
            sj, oj = self.actor_jobs.get(summon), self.actor_jobs.get(owner)
            if sj and oj and sj != oj:
                return
            self.summons[summon] = owner

    def find_id_by_name(self, name):
        for eid, n in self.nicknames.items():
            if n == name:
                return eid
        return None

    # ───────── names ─────────

    def append_nickname_authoritative(self, uid, name):
        """A name the game stated for this entity (spawn or self record)."""
        with self.lock:
            self.authoritative.add(uid)
            self.spawn_named.add(uid)
            self._set_nick(uid, name, force=True)

    def append_nickname(self, uid, name):
        """A lower-confidence name source: only for real entities, never stealing a stated name."""
        with self.lock:
            cur = self.current
            real = (uid in self.nicknames or uid in self.known_players or uid in self.summons
                    or uid in self.authoritative
                    or (cur is not None and any(uid in t.actors for t in cur.targets.values())))
            if not real:
                return
            for eid in self.authoritative:
                if eid != uid and self.nicknames.get(eid) == name:
                    return
            if uid in self.authoritative and self.nicknames.get(uid) not in (None, name):
                return
            self._set_nick(uid, name, force=False)

    def _set_nick(self, uid, name, force):
        existing = self.nicknames.get(uid)
        if existing == name:
            if self.local_name and self.local_name == name:
                self.local_id = uid
            return
        if existing and not force and len(name.encode()) <= 5 and len(existing.encode()) > len(name.encode()):
            return

        for old in [e for e, n in self.nicknames.items() if n == name and e != uid]:
            same_character = force and old in self.authoritative
            del self.nicknames[old]
            self.known_players.discard(old)
            self.authoritative.discard(old)
            self.spawn_named.discard(old)
            if same_character:
                # The same character came back as a new entity: keep what the old id did.
                self.aliases[old] = uid
                for s, o in list(self.summons.items()):
                    if o == old:
                        self.summons[s] = uid
            else:
                for s, o in list(self.summons.items()):
                    if o == old:
                        del self.summons[s]
                cur = self.current
                if cur:
                    for t in cur.targets.values():
                        a = t.actors.pop(old, None)
                        if a:
                            t.total -= a.total

        self.nicknames[uid] = name
        self.aliases.pop(uid, None)
        if uid not in self.confirmed_summons:
            self.summons.pop(uid, None)
            if uid not in self.known_players:
                self.known_players.add(uid)
                self._purge_friendly()
        if self.local_name and self.local_name == name:
            self.local_id = uid

    # ───────── who you are ─────────

    def set_local_identity(self, eid, name):
        with self.lock:
            self.local_from_game = True
            self.loot_applied = False
            self.local_id = eid
            self.local_name = name

    def note_self_profile(self, name, job, level, server):
        with self.lock:
            prev = self.self_profile
            if level is None and prev and prev[0] == name:
                level = prev[2]
            self.self_profile = (name, job, level, server)
            saved = self.saved_profile
            if not saved or saved.get("name") != name or saved.get("job") != job:
                self._save_profile(name, job)

    def note_party_scope(self, eid):
        if 100 <= eid <= 9_999_999 and len(self.party_scope) < 10_000:
            self.party_scope[eid] += 1
            self.scope_recent[eid] += 1

    def note_self_marker(self, eid):
        if 100 <= eid <= 9_999_999 and len(self.self_marks) < 1_000:
            self.self_marks[eid] += 1

    def note_zone_load(self):
        """Entity ids are handed out again on a zone load: counts from before say nothing now."""
        with self.lock:
            self.self_marks.clear()
            self.zone_hps.clear()  # a new zone has its own mob levels
            self.scope_recent.clear()

    def _save_profile(self, name, job):
        if not self.profile_path:
            return
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump({"name": name, "job": job}, f, ensure_ascii=False)
            self.saved_profile = {"name": name, "job": job}
        except OSError:
            pass

    def _marker_guess(self):
        """The entity the local-player HP records name, when they name one clearly."""
        ranked = sorted(((n, eid) for eid, n in self.self_marks.items()
                         if eid not in self.mobs and eid not in self.summons
                         and eid not in self.confirmed_summons and eid not in self.summon_spawns),
                        reverse=True)
        if not ranked or ranked[0][0] < SELF_MARK_MIN:
            return None
        if len(ranked) > 1 and ranked[0][0] < SELF_MARK_LEAD * ranked[1][0]:
            return None
        return ranked[0][1]

    def note_loot_owner(self, mob, owner, name):
        """Loot of a mob you fought names its owner; mostly that is you (until the self record)."""
        with self.lock:
            entry = self.loot_owners.setdefault(name, [owner, set()])
            entry[0] = owner
            if len(entry[1]) < 10_000:
                entry[1].add(mob)
            if self.local_from_game and not self.loot_applied:
                return
            ranked = sorted(((n, e[0], len(e[1])) for n, e in self.loot_owners.items()
                             if e[0] in self.party_scope), key=lambda r: -r[2])
            if not ranked:
                return
            if len(ranked) > 1 and ranked[0][2] == ranked[1][2]:
                if self.loot_applied:
                    self.loot_applied = False
                    self.local_from_game = False
                    self.local_id = None
                return
            lname, lid, _ = ranked[0]
            self.loot_applied = True
            self.local_from_game = True
            self.local_id = lid
            self.local_name = lname

    def _scope_guess(self):
        """Fallback: the player with a class that the `06 38` records name most, leading clearly."""
        ranked = sorted(((n, eid) for eid, n in self.scope_recent.items()
                         if self.actor_jobs.get(eid) and eid in self.known_players
                         and eid not in self.summons and eid not in self.confirmed_summons
                         and eid not in self.summon_spawns and eid not in self.mobs),
                        reverse=True)
        if not ranked or ranked[0][0] < SCOPE_MIN_RECORDS:
            return None
        if len(ranked) > 1 and ranked[0][0] < SCOPE_LEAD * ranked[1][0]:
            return None
        return ranked[0][1]

    def local_identity(self):
        """(entity id, name) of the local player, or (None, None)."""
        with self.lock:
            if self.local_id is not None:
                return self.local_id, self.local_name or self.nicknames.get(self.local_id)
            eid = self._marker_guess()
            if eid is None:
                eid = self._scope_guess()
            if eid is None:
                return None, None
            name = self.nicknames.get(eid)
            saved = self.saved_profile
            if name is None and saved and saved.get("job") == self.actor_jobs.get(eid):
                name = saved["name"]  # same class as the character you played last time
            return eid, name

    def local_is_guess(self):
        with self.lock:
            return self.local_id is None and (self._marker_guess() or self._scope_guess()) is not None

    # ───────── party ─────────

    def set_party_roster(self, members, complete, dungeon_id):
        with self.lock:
            if complete:
                self.roster = {}
            for name, m in members:
                self.roster[name] = m
            self.roster_by_dbid = {m["dbid"]: n for n, m in self.roster.items() if m.get("dbid")}
            for dbid, name in self.roster_by_dbid.items():
                self._learn_account(dbid, name)
            self.roster_ts = self.now
            self.dungeon_id = dungeon_id

    def _bind_roster_by_class(self):
        """Name a party member by class when exactly one candidate fits on each side."""
        if len(self.roster) < 2:
            return
        cur = self.current
        if not cur:
            return
        named = set(self.nicknames.values())
        unbound = defaultdict(list)
        for name, m in self.roster.items():
            if name not in named and m.get("job"):
                unbound[m["job"]].append(name)
        if not unbound:
            return
        fighting = defaultdict(set)
        for t in cur.targets.values():
            for actor in t.actors:
                rid = self.resolve(actor)
                if rid in self.nicknames or rid in self.summons or rid not in self.known_players:
                    continue
                job = self.actor_jobs.get(rid)
                if job:
                    fighting[job].add(rid)
        for job, names in unbound.items():
            ids = fighting.get(job, ())
            if len(names) == 1 and len(ids) == 1:
                self._set_nick(next(iter(ids)), names[0], force=False)

    # ───────── party members by position ─────────

    def _learn_account(self, dbid, name):
        if self.dbid_names.get(dbid) != name and len(self.dbid_names) < ACCOUNTS_MAX:
            self.dbid_names[dbid] = name
            self._accounts_dirty = True
        eid = self.dbid_entity.get(dbid)
        if eid is not None:
            self._name_from_account(eid, name)

    def _name_from_account(self, eid, name):
        """Name an entity from its account, without overruling what a spawn record stated."""
        if self.nicknames.get(eid) == name:
            return
        if eid in self.spawn_named:
            return  # the game named this entity itself; that wins
        holder = self.find_id_by_name(name)
        if holder is not None and holder != eid and holder in self.spawn_named:
            return  # the name is on another entity by the game's own word
        self.authoritative.add(eid)
        self._set_nick(eid, name, force=True)

    def note_player_dbid(self, eid, dbid, name):
        """A spawn stated a player's account id along with their name."""
        with self.lock:
            self.entity_dbid[eid] = dbid
            self.dbid_entity[dbid] = eid
            self._learn_account(dbid, name)

    def account_name(self, dbid):
        return self.roster_by_dbid.get(dbid) or self.dbid_names.get(dbid)

    def note_party_position(self, dbid, key):
        """A party member's map marker (`1C 92`): they are in your party, and this is where they are."""
        if not dbid:
            return
        self.party_dbids[dbid] = self.now
        if len(self.party_pos) > 20_000:
            self.party_pos.clear()
        prev = self.party_pos.get(key)
        if prev is not None and prev != dbid:
            self.party_pos[key] = AMBIGUOUS  # two members on the very same spot (an instance entrance)
            return
        self.party_pos[key] = dbid
        eid = self.entity_pos.get(key)
        if eid is not None and eid is not AMBIGUOUS:
            self._position_vote(eid, dbid)

    def note_entity_position(self, eid, key):
        if len(self.entity_pos) > 60_000:
            self.entity_pos.clear()
        prev = self.entity_pos.get(key)
        if prev is not None and prev != eid:
            self.entity_pos[key] = AMBIGUOUS  # shared by several entities: not a position
            return
        self.entity_pos[key] = eid
        dbid = self.party_pos.get(key)
        if dbid is not None and dbid is not AMBIGUOUS:
            self._position_vote(eid, dbid)

    def _position_vote(self, eid, dbid):
        """A party member's map marker sat exactly where this entity moved: count it.

        Bound once one entity clearly leads for the account. Mobs never
        qualify (a boss's records carry the positions of whoever it hits)."""
        with self.lock:
            if eid in self.mobs or eid in self.summon_spawns or eid in self.confirmed_summons:
                return
            if self.entity_dbid.get(eid) == dbid and self.dbid_entity.get(dbid) == eid:
                return
            self.position_votes[(eid, dbid)] += 1
            ranked = sorted((v, e) for (e, d), v in self.position_votes.items() if d == dbid)
            top_v, top_e = ranked[-1]
            second = ranked[-2][0] if len(ranked) > 1 else 0
            if top_e == eid and top_v >= POSITION_MIN_VOTES and top_v >= POSITION_LEAD * second:
                known = self.entity_dbid.get(eid)
                if known is not None and known != dbid and eid in self.spawn_named:
                    return  # the spawn said whose account this entity is
                self.entity_dbid[eid] = dbid
                self.dbid_entity[dbid] = eid
                name = self.account_name(dbid)
                if name:
                    self._name_from_account(eid, name)

    def _party_now(self):
        """(in a party?, party names, party entity ids) from the roster and fresh map markers."""
        fresh = [d for d, ts in self.party_dbids.items() if self.now - ts < PARTY_MARKER_FRESH_MS]
        names = set(self.roster)
        names.update(n for n in map(self.account_name, fresh) if n)
        entities = {self.dbid_entity[d] for d in fresh if d in self.dbid_entity}
        return bool(self.roster or fresh), names, entities

    def _save_accounts(self):
        now = time.time()
        if not self._accounts_dirty or now - self._accounts_saved_at < NAMES_SAVE_EVERY_S:
            return
        self._accounts_saved_at = now
        self._accounts_dirty = False
        try:
            tmp = self.accounts_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({str(k): v for k, v in self.dbid_names.items()}, f, ensure_ascii=False)
            os.replace(tmp, self.accounts_path)
        except OSError:
            self._accounts_dirty = True

    # ───────── zone / reset ─────────

    def note_zone_change(self):
        with self.lock:
            now = self.now
            if now - self.last_damage_ts < ZONE_RESET_LULL_MS:
                return  # a knockback/pull mid-fight, not a zone load
            if now - self.last_zone_reset < ZONE_RESET_DEBOUNCE_MS:
                return
            if not self.current or not self.current.targets:
                return
            self.last_zone_reset = now
            self._end_encounter("zone")
            self.dead.clear()

    def reset(self):
        with self.lock:
            self._end_encounter("reset")

    def set_paused(self, paused):
        """Stop / resume counting. Stopping closes the running fight, so its numbers freeze."""
        with self.lock:
            self.paused = paused
            if paused:
                self._end_encounter("paused")
            self.generation += 1

    def clear_history(self):
        with self.lock:
            self._end_encounter("reset")
            self.history.clear()
            self.generation += 1

    def tick(self):
        """Close the current encounter once it has been idle for IDLE_MS."""
        with self.lock:
            cur = self.current
            if cur and self.now - cur.last > IDLE_MS:
                self._end_encounter("idle")
            if self.names_path:
                self._apply_name_cache()
                self._save_name_cache()
            if self.accounts_path:
                self._save_accounts()

    def _apply_name_cache(self):
        """Same entity id as last run means the same zone instance: its names still hold."""
        cache = self.name_cache
        if not cache:
            return
        lid, _ = self.local_identity()
        if lid is None:
            return
        self.name_cache = None  # one decision per run
        if lid != cache["local_id"]:
            return
        taken = set(self.nicknames.values())
        for eid, name in cache["names"].items():
            if eid not in self.nicknames and name not in taken and eid not in self.mobs:
                self._set_nick(eid, name, force=False)
                taken.add(name)

    def _save_name_cache(self):
        now = time.time()
        if now - self._names_saved_at < NAMES_SAVE_EVERY_S or len(self.nicknames) == self._names_saved_count:
            return
        lid, _ = self.local_identity()
        if lid is None or self.name_cache is not None:
            return  # do not overwrite a cache this run has not had the chance to use
        self._names_saved_at = now
        self._names_saved_count = len(self.nicknames)
        try:
            tmp = self.names_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"local_id": self.resolve(lid), "saved": now,
                           "names": {str(k): v for k, v in self.nicknames.items()}}, f, ensure_ascii=False)
            os.replace(tmp, self.names_path)
        except OSError:
            pass

    def _end_encounter(self, reason):
        cur = self.current
        if cur is None:
            return
        self.current = None
        if cur.targets:
            cur.end_reason = reason
            cur.frozen = self.resolve_encounter(cur)
            self.history.append(cur)
            del self.history[:-HISTORY_MAX]
            if self.on_end is not None:
                try:
                    self.on_end(cur)
                except Exception:
                    pass
        self.generation += 1

    # ───────── damage ─────────

    def resolve(self, eid):
        """Follow alias (re-spawned character) and summon (pet -> owner) links."""
        for _ in range(4):
            nxt = _resolve_chain(eid, self.aliases)
            nxt = _resolve_chain(nxt, self.summons)
            if nxt == eid:
                break
            eid = nxt
        return eid

    def _is_friendly(self, actor, target):
        return self.resolve(actor) in self.known_players and self.resolve(target) in self.known_players

    def _purge_friendly(self):
        cur = self.current
        if not cur:
            return
        for tid in list(cur.targets):
            t = cur.targets[tid]
            for aid in [a for a in t.actors if self._is_friendly(a, tid)]:
                t.total -= t.actors.pop(aid).total
            if not t.actors:
                del cur.targets[tid]

    def _is_relevant(self, actor):
        """Damage from you, your party or your pets keeps an encounter going; strangers' does not."""
        local_id, local_name = self.local_identity()
        if local_id is None and not self.roster:
            return True
        rid = self.resolve(actor)
        if local_id is not None and rid == self.resolve(local_id):
            return True
        name = self.nicknames.get(rid)
        if name and (name == local_name or name in self.roster):
            return True
        return not self.roster and local_id is None

    def append_damage(self, actor, target, skill, damage, multi_hits=0, multi_damage=0,
                      specials=(), is_dot=False):
        with self.lock:
            self.records += 1
            if actor in self.mobs and actor not in self.summons and 1_000_000 <= skill <= 9_999_999:
                return
            if (is_player_skill(skill) and actor not in self.confirmed_summons
                    and actor not in self.summon_spawns and actor not in self.known_players):
                self.known_players.add(actor)
                self.summons.pop(actor, None)
                self._purge_friendly()
            if self._is_friendly(actor, target):
                self._heal(actor, skill, damage + multi_damage, False)
                return  # player-on-player: a heal or buff, not damage
            if self.resolve(actor) in self.known_players:
                self.hostile_targets.add(target)
            job = job_from_skill(skill)
            if job:
                self.actor_jobs.setdefault(actor, job)

            if self.paused:
                return
            # Every DoT tick counts, also the ones after your last direct hit on a
            # training dummy: the game's own Combat Analysis counts them (and its
            # battle time runs to the last tick), and comparing against it showed
            # the reference meter's "drop trailing dummy DoTs" rule as missing damage.
            self._apply((self.now, actor, target, skill, damage, multi_hits, multi_damage, specials, is_dot))

            self._since_roster_bind += 1
            if self._since_roster_bind >= ROSTER_BIND_EVERY:
                self._since_roster_bind = 0
                self._bind_roster_by_class()

    def append_heal(self, actor, skill, amount, is_hot=False):
        with self.lock:
            if not self.paused:
                self._heal(actor, skill, amount, is_hot)

    def _heal(self, actor, skill, amount, is_hot):
        """Healing done, booked on the running fight (heals never open one)."""
        cur = self.current
        if cur is None or amount <= 0:
            return
        book = cur.heals.setdefault(actor, {})
        h = book.get((skill, is_hot))
        if h is None:
            h = book[(skill, is_hot)] = SkillAgg()
        h.hits += 1
        h.total += amount
        if h.min is None or amount < h.min:
            h.min = amount
        h.max = max(h.max, amount)

    def zone_name(self):
        return self.gd.dungeon_name(self.dungeon_id) if self.dungeon_id else None

    def _boss_still_fought(self, enc, ts):
        return any(self.is_boss(tid) and tid not in self.dead and ts - t.last < BOSS_SWITCH_MS
                   for tid, t in enc.targets.items())

    def _apply(self, rec):
        ts, actor, target, skill, damage, mh_count, mh_damage, specials, is_dot = rec
        relevant = self._is_relevant(actor)
        cur = self.current
        if cur is not None and ts - cur.last > IDLE_MS:
            self._end_encounter("idle")
            cur = None
        if cur is None:
            if not relevant or target in self.dead:
                return
            cur = self.current = Encounter(ts, self.zone_name())
        is_boss = self.is_boss(target)
        if is_boss and relevant and cur.targets and target not in cur.targets and (
                not cur.has_boss or not self._boss_still_fought(cur, ts)):
            # A boss starts its own fight: after trash, and after another boss that died or was
            # left behind. Two bosses fought side by side (both hit lately) stay one fight.
            self._end_encounter("boss")
            cur = self.current = Encounter(ts, self.zone_name())
        if is_boss and relevant:
            cur.has_boss = True

        total = damage + mh_damage
        t = cur.targets.get(target)
        if t is None:
            t = cur.targets[target] = TargetAgg(target, ts)
        t.first = min(t.first, ts)
        t.last = max(t.last, ts)
        t.total += total

        a = t.actors.get(actor)
        if a is None:
            a = t.actors[actor] = ActorAgg(ts)
        a.total += total
        a.first = min(a.first, ts)
        a.last = max(a.last, ts)
        sec = ts // 1000
        a.buckets[sec] = a.buckets.get(sec, 0) + total

        key = (skill, is_dot)
        s = a.skills.get(key)
        if s is None:
            s = a.skills[key] = SkillAgg()
        s.hits += 1
        s.total += total
        if s.min is None or damage < s.min:
            s.min = damage
        if damage > s.max:
            s.max = damage
        for tag in specials:
            if tag == CRIT:
                s.crit += 1
            elif tag == BACK:
                s.back += 1
            elif tag == FRONT:
                s.front += 1
            elif tag == PARRY:
                s.parry += 1
            elif tag == PERFECT:
                s.perfect += 1
            elif tag == DOUBLE:
                s.double += 1
            elif tag == SMITE:
                s.smite += 1
            elif tag == POWERSHARD:
                s.powershard += 1
        if mh_count > 0:
            s.mh_events += 1
            s.mh_hits += mh_count
            s.mh_damage += mh_damage

        if relevant:
            cur.start = min(cur.start, ts)
            cur.last = max(cur.last, ts)
            self.last_damage_ts = ts
        self.generation += 1

    # ───────── the resolved view (what the UI shows) ─────────

    def resolve_encounter(self, enc):
        """Group an encounter's actors into players (pets folded in), named and classed."""
        with self.lock:
            gd = self.gd
            local_id, local_name = self.local_identity()
            local_rid = self.resolve(local_id) if local_id is not None else None

            # actor -> group key (character name, or #entity for the unnamed)
            group_of = {}
            group_ids = defaultdict(set)
            group_skills = defaultdict(set)
            for t in enc.targets.values():
                for actor, a in t.actors.items():
                    k = group_of.get(actor)
                    if k is None:
                        rid = self.resolve(actor)
                        k = (self.nicknames.get(rid) or (local_name if rid == local_rid else None)
                             or f"#{rid}")
                        group_of[actor] = k
                        group_ids[k].add(rid)
                    for code, _ in a.skills:
                        group_skills[k].add(code)

            jobs = {}
            for k, rids in group_ids.items():
                job = next((self.actor_jobs[r] for r in rids if r in self.actor_jobs), None)
                if job is None and k in self.roster:
                    job = self.roster[k].get("job")
                if job is None:
                    job = next((self.actor_jobs[a] for a, g in group_of.items()
                                if g == k and a in self.actor_jobs), None)
                jobs[k] = job

            # Orphan summons whose spawn never arrived: fold into the one plausible owner.
            merge = {}
            named = [k for k in group_ids if not k.startswith("#")]
            for k, rids in group_ids.items():
                if not k.startswith("#") or local_rid in rids:
                    continue
                rid = next(iter(rids))
                job = jobs.get(k) or next(
                    (j for j in map(job_from_skill_loose, group_skills[k]) if j), None)
                is_player = rid in self.known_players
                if job and not is_player:
                    same = [o for o in named if jobs.get(o) == job]
                    if len(same) == 1:
                        merge[k] = same[0]
                        continue
                mine = self.power_scalars.get(rid)
                if not mine or not group_skills[k]:
                    continue
                owners = []
                for o in named:
                    orids = group_ids[o]
                    if not any(r in self.known_players for r in orids):
                        continue
                    if (jobs.get(o) != job) if job else not jobs.get(o):
                        continue
                    if is_player and len(group_skills[o]) < 3 * len(group_skills[k]):
                        continue
                    if any(self.power_scalars.get(r, set()) & mine for r in orids):
                        owners.append(o)
                if len(owners) == 1:
                    merge[k] = owners[0]

            local_keys = {k for k, rids in group_ids.items()
                          if local_rid in rids or (local_name is not None and k == local_name)}
            in_a_party, party_names, party_entities = self._party_now()

            players = {}
            for k in group_ids:
                if k in merge:
                    continue
                name = None if k.startswith("#") else k
                member = self.roster.get(name) if name else None
                is_local = k in local_keys
                # In a party the party tab is the party; without one it is everyone.
                if in_a_party:
                    in_party = bool(is_local or (name and name in party_names)
                                    or group_ids[k] & party_entities)
                else:
                    in_party = True
                players[k] = {
                    "key": k,
                    "name": name or k,
                    "job": jobs.get(k) or (member or {}).get("job"),
                    "is_local": is_local,
                    "in_party": in_party,
                    "combat_power": (member or {}).get("combat_power", 0),
                    "level": (member or {}).get("level"),
                }

            targets = []
            for t in enc.targets.values():
                code = self.mobs.get(t.id)
                per_player = {}
                for actor, a in t.actors.items():
                    k = group_of[actor]
                    k = merge.get(k, k)
                    pp = per_player.get(k)
                    if pp is None:
                        pp = per_player[k] = {"total": 0, "first": a.first, "last": a.last, "skills": {}}
                    pp["total"] += a.total
                    pp["first"] = min(pp["first"], a.first)
                    pp["last"] = max(pp["last"], a.last)
                    b = pp.setdefault("buckets", {})
                    for sec, d in a.buckets.items():
                        b[sec] = b.get(sec, 0) + d
                    for (code_s, is_dot), s in a.skills.items():
                        dk = (gd.normalize_skill_id(code_s), is_dot)
                        agg = pp["skills"].get(dk)
                        if agg is None:
                            agg = pp["skills"][dk] = SkillAgg()
                        agg.absorb(s)
                targets.append({
                    "id": t.id,
                    "name": (gd.npc_name(code) if code is not None else "") or f"#{t.id}",
                    "is_boss": self.is_boss(t.id),
                    "is_dummy": t.id in self.dummies,
                    "dead": t.id in self.dead,
                    "first": t.first,
                    "last": t.last,
                    "total": t.total,
                    "max_hp": self.mob_max_hp.get(t.id, 0),
                    "cur_hp": 0 if t.id in self.dead else self.mob_cur_hp.get(t.id),
                    "players": per_player,
                })

            heals, heal_rids = self._resolve_heals(enc, group_of, merge, local_rid, local_name)
            for k, entry in heals.items():
                if k in players or k in merge:
                    continue
                job = next((j for j in (job_from_skill(code) for code, _ in entry["skills"]) if j), None)
                if job is None:
                    continue  # potions and items only: nothing says this is a player
                rids = heal_rids.get(k, set())
                name = None if k.startswith("#") else k
                member = self.roster.get(name) if name else None
                is_local = local_rid in rids or (local_name is not None and k == local_name)
                if in_a_party:
                    in_party = bool(is_local or (name and name in party_names) or rids & party_entities)
                else:
                    in_party = True
                players[k] = {
                    "key": k,
                    "name": name or k,
                    "job": job,
                    "is_local": is_local,
                    "in_party": in_party,
                    "combat_power": (member or {}).get("combat_power", 0),
                    "level": (member or {}).get("level"),
                }

            # A row without a class is not a player (unless it is you).
            return {
                "id": enc.id,
                "start": enc.start,
                "last": enc.last,
                "has_boss": enc.has_boss,
                "end_reason": enc.end_reason,
                "players": {k: p for k, p in players.items() if p["job"] or p["is_local"]},
                "targets": targets,
                "party_known": in_a_party,
                "zone": enc.zone,
                "heals": heals,
                "local_known": bool(local_keys),
                "local_name": local_name,
            }

    def _resolve_heals(self, enc, group_of, merge, local_rid, local_name):
        """({player key: {"total", "skills": {(code, is_hot): SkillAgg}}}, {player key: entity ids})."""
        out = {}
        rids = {}
        for actor, book in enc.heals.items():
            rid = self.resolve(actor)
            k = group_of.get(actor)
            if k is None:
                k = self.nicknames.get(rid) or (local_name if rid == local_rid else None) or f"#{rid}"
            k = merge.get(k, k)
            rids.setdefault(k, set()).add(rid)
            entry = out.setdefault(k, {"total": 0, "skills": {}})
            for key, h in book.items():
                agg = entry["skills"].get(key)
                if agg is None:
                    agg = entry["skills"][key] = SkillAgg()
                agg.absorb(h)
                entry["total"] += h.total
        return out, rids

    def view(self, enc):
        return enc.frozen if enc.frozen is not None else self.resolve_encounter(enc)

    def encounters(self):
        """[(encounter id, label info)] newest first, live one included."""
        with self.lock:
            out = []
            if self.current and self.current.targets:
                out.append(self.current)
            out.extend(reversed(self.history))
            return out

    def status(self):
        with self.lock:
            lid, lname = self.local_identity()
            return {
                "local_id": lid,
                "local_name": lname,
                "profile": self.self_profile,
                "names": len(self.nicknames),
                "players": len(self.known_players),
                "summons": len(self.summons),
                "mobs": len(self.mobs),
                "roster": dict(self.roster),
                "records": self.records,
            }
