"""Field boss respawn timers. A kill the meter sees (or one marked by hand) starts the boss's cycle.

The cycles and the Spacetime Rift clock come from data/field_bosses.json; the countdowns themselves
are drawn by the page, which also turns server time into the player's time.
"""
import json
import os
import threading
import time

from .paths import resource, user_path

DATA_PATH = resource("data", "field_bosses.json")
KILLS_PATH = user_path("boss_sayaclari.json")


class BossTimers:
    def __init__(self, data_path=DATA_PATH, kills_path=KILLS_PATH):
        with open(data_path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.bosses = {b["code"]: b for b in self.data["bosses"]}
        self.path = kills_path
        self.lock = threading.Lock()
        self.kills = {}    # code -> epoch ms of the last kill
        self.cycles = {}   # code -> respawn minutes the player set (overrides the table)
        try:
            with open(kills_path, encoding="utf-8") as f:
                saved = json.load(f)
            self.kills = {int(k): int(v) for k, v in saved.get("kills", {}).items() if int(k) in self.bosses}
            self.cycles = {int(k): int(v) for k, v in saved.get("cycles", {}).items() if int(k) in self.bosses}
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"kills": self.kills, "cycles": self.cycles}, f)
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

    def clear(self, code):
        with self.lock:
            self.kills.pop(code, None)
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

    def state(self):
        with self.lock:
            rows = []
            for code, b in self.bosses.items():
                cycle = self.cycles.get(code, b["respawn_min"])
                killed = self.kills.get(code)
                rows.append(dict(b, cycle_min=cycle, custom=code in self.cycles, killed=killed,
                                 due=killed + cycle * 60_000 if killed is not None else None))
        return {"now": int(time.time() * 1000), "bosses": rows, "rift": self.data["rift"],
                "regions": self.data["regions"], "note": self.data["note"], "sources": self.data["sources"]}
