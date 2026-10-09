"""Field boss respawn timers.

The game sends the field boss list of the world you are in (the one its map shows "Time Left" from):
those times are used as they are. For the rest, a kill the meter sees (or one marked by hand) starts
the boss's cycle from data/field_bosses.json, which also holds the Spacetime Rift clock. The
countdowns themselves are drawn by the page, which also turns server time into the player's time.
"""
import json
import os
import threading
import time

from .paths import resource, user_path

DATA_PATH = resource("data", "field_bosses.json")
KILLS_PATH = user_path("boss_sayaclari.json")
SAVE_EVERY_MS = 5 * 60_000   # the game's list comes every few seconds; the file is kept fresh this often
LEARN_GAP_MS = 30_000        # a boss seen up, then gone in the next list: killed in between
ALERT_LEAD_MS = 10 * 60_000  # an alerted boss is announced this long before it is due
ALERT_HOLD_MS = 10 * 60_000  # and stays announced this long after: it comes back within about that


class BossTimers:
    def __init__(self, data_path=DATA_PATH, kills_path=KILLS_PATH):
        with open(data_path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.bosses = {b["code"]: b for b in self.data["bosses"]}
        # the game numbers a world's field bosses in the order of their NPC codes
        self.worlds = {int(w): sorted(c for c, b in self.bosses.items() if b["faction"] == fac)
                       for w, fac in self.data["worlds"].items()}
        self.path = kills_path
        self.lock = threading.Lock()
        self.kills = {}      # code -> epoch ms of the last kill
        self.cycles = {}     # code -> respawn minutes the player set (overrides the table)
        self.learned = {}    # code -> respawn minutes measured from the game's own list
        self.live = {}       # code -> {"up", "at", "seen"} from the game's list
        self.live_seen = {}  # world -> epoch ms of its last list
        self.unknown_worlds = set()
        self._saved_at = 0
        try:
            with open(kills_path, encoding="utf-8") as f:
                saved = json.load(f)

            def ints(key):
                return {int(k): int(v) for k, v in saved.get(key, {}).items() if int(k) in self.bosses}
            self.kills, self.cycles, self.learned = ints("kills"), ints("cycles"), ints("learned")
            self.live = {int(k): {"up": bool(v["up"]), "at": int(v["at"]), "seen": int(v["seen"])}
                         for k, v in saved.get("live", {}).items() if int(k) in self.bosses}
            self.live_seen = {int(k): int(v) for k, v in saved.get("live_seen", {}).items()}
        except (OSError, ValueError, AttributeError, KeyError, TypeError):
            pass

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"kills": self.kills, "cycles": self.cycles, "learned": self.learned,
                           "live": self.live, "live_seen": self.live_seen}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def is_field_boss(self, code):
        return code in self.bosses

    def note_kill(self, code, when_ms=None):
        """A field boss died (seen by the meter or marked by hand): its respawn cycle starts now."""
        if code not in self.bosses:
            return False
        with self.lock:
            self.kills[code] = int(when_ms if when_ms is not None else time.time() * 1000)
            self._save()
        return True

    def note_list(self, world, entries, seen_ms):
        """The game's field boss list for `world`: [(n, up, ms)], n counted from 1. False when unknown."""
        codes = self.worlds.get(world)
        if codes is None or len(entries) != len(codes):
            self.unknown_worlds.add((world, len(entries)))
            return False
        with self.lock:
            prev_seen = self.live_seen.get(world, 0)
            changed = False
            for n, up, at in entries:
                if not 1 <= n <= len(codes):
                    continue
                code = codes[n - 1]
                old = self.live.get(code)
                if old is None or old["up"] != up or old["at"] != at:
                    changed = True
                    if old is not None and old["up"] and not up and seen_ms - prev_seen <= LEARN_GAP_MS:
                        # killed since the last list: that is the kill, and the wait to the next spawn its cycle
                        self.kills[code] = seen_ms
                        minutes = int(round((at - seen_ms) / 300_000)) * 5
                        if 5 <= minutes <= 7 * 24 * 60:
                            self.learned[code] = minutes
                self.live[code] = {"up": up, "at": at, "seen": seen_ms}
            self.live_seen[world] = seen_ms
            if changed or seen_ms - self._saved_at >= SAVE_EVERY_MS:
                self._saved_at = seen_ms
                self._save()
        return True

    def clear(self, code):
        with self.lock:
            self.kills.pop(code, None)
            self.live.pop(code, None)
            self._save()

    def set_cycle(self, code, minutes):
        if code not in self.bosses:
            return
        with self.lock:
            minutes = int(minutes)
            if minutes <= 0 or minutes == self.bosses[code]["respawn_min"]:
                self.cycles.pop(code, None)  # back to the table's cycle
            else:
                self.cycles[code] = min(minutes, 7 * 24 * 60)
            self._save()

    def _due(self, code):
        """(cycle, killed, due, live) of a boss; live only while the game's list is newer than the kill."""
        cycle = self.cycles.get(code) or self.learned.get(code) or self.bosses[code]["respawn_min"]
        killed = self.kills.get(code)
        due = killed + cycle * 60_000 if killed is not None else None
        live = self.live.get(code)
        if live is not None and (killed is None or live["seen"] >= killed):
            due = None if live["up"] else live["at"]  # the game's own word, newer than the kill
        else:
            live = None
        return cycle, killed, due, live

    def alerts(self, codes, now_ms=None):
        """The bosses in `codes` about to come back or just back, soonest first. stage: "soon" (due
        within ALERT_LEAD_MS), "due" (its time has come) or "up" (the game's list says it is up)."""
        now = int(now_ms if now_ms is not None else time.time() * 1000)
        out = []
        with self.lock:
            for code in codes:
                if code not in self.bosses:
                    continue
                _, _, due, live = self._due(code)
                if live is not None and live["up"]:
                    at, stage = live["at"], "up"
                elif due is not None:
                    at, stage = due, "soon" if now < due else "due"
                else:
                    continue
                if at - ALERT_LEAD_MS <= now < at + ALERT_HOLD_MS:
                    b = self.bosses[code]
                    out.append({"code": code, "name": b["name"], "zone": b["zone"], "at": at, "stage": stage})
        return sorted(out, key=lambda a: a["at"])

    def state(self):
        with self.lock:
            rows = []
            for code, b in self.bosses.items():
                cycle, killed, due, live = self._due(code)
                rows.append(dict(b, cycle_min=cycle, custom=code in self.cycles, learned=code in self.learned,
                                 killed=killed, due=due, live=live))
            seen = {self.bosses[codes[0]]["faction"]: self.live_seen[w]
                    for w, codes in self.worlds.items() if w in self.live_seen and codes}
        return {"now": int(time.time() * 1000), "bosses": rows, "live_seen": seen, "rift": self.data["rift"],
                "regions": self.data["regions"], "note": self.data["note"], "sources": self.data["sources"]}
