"""Fights kept on disk: one JSON file per fight plus a small index for the history list."""
import json
import os
import threading
import time

from .paths import user_path
from .store import SkillAgg

KEEP = 300            # most recent fights kept (favourites are never dropped)
MIN_DURATION_MS = 5_000


def _agg_out(s):
    return [s.hits, s.total, s.min, s.max, s.crit, s.back, s.front, s.parry, s.perfect, s.double,
            s.smite, s.powershard, s.mh_events, s.mh_hits, s.mh_damage]


def _agg_in(v):
    s = SkillAgg()
    (s.hits, s.total, s.min, s.max, s.crit, s.back, s.front, s.parry, s.perfect, s.double,
     s.smite, s.powershard, s.mh_events, s.mh_hits, s.mh_damage) = v
    return s


def _skills_out(skills):
    return [[code, int(dot), _agg_out(s)] for (code, dot), s in skills.items()]


def _skills_in(rows):
    return {(code, bool(dot)): _agg_in(v) for code, dot, v in rows}


def to_json(resolved):
    out = dict(resolved)
    out["targets"] = [dict(t, players={k: dict(pp, skills=_skills_out(pp["skills"]),
                                                buckets=sorted(pp.get("buckets", {}).items()))
                                       for k, pp in t["players"].items()})
                      for t in resolved["targets"]]
    out["heals"] = {k: {"total": h["total"], "skills": _skills_out(h["skills"])}
                    for k, h in resolved.get("heals", {}).items()}
    return out


def from_json(data):
    data["targets"] = [dict(t, players={k: dict(pp, skills=_skills_in(pp["skills"]),
                                                 buckets={int(sec): d for sec, d in pp.get("buckets", [])})
                                        for k, pp in t["players"].items()})
                       for t in data["targets"]]
    data["heals"] = {k: {"total": h["total"], "skills": _skills_in(h["skills"])}
                     for k, h in data.get("heals", {}).items()}
    return data


def summary_of(resolved, title):
    players = [p for p in resolved["players"].values() if p.get("in_party")]
    total = sum(pp["total"] for t in resolved["targets"] for k, pp in t["players"].items()
                if k in resolved["players"] and resolved["players"][k].get("in_party"))
    return {
        "id": resolved["id"],
        "title": title,
        "zone": resolved.get("zone"),
        "start": resolved["start"],
        "duration_ms": resolved["last"] - resolved["start"],
        "end_reason": resolved.get("end_reason"),
        "has_boss": resolved.get("has_boss", False),
        "players": [{"name": p["name"], "job": p.get("job"), "local": p.get("is_local")} for p in players][:12],
        "total": total,
        "favorite": False,
    }


class History:
    def __init__(self, folder=None):
        self.dir = folder or os.path.dirname(user_path("gecmis", "x"))
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, "index.json")
        self.lock = threading.Lock()
        self._cache = {}
        try:
            with open(self.index_path, encoding="utf-8") as f:
                self.index = json.load(f)
        except (OSError, ValueError):
            self.index = []

    def _save_index(self):
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False)
        os.replace(tmp, self.index_path)

    def _file(self, fid):
        return os.path.join(self.dir, f"{fid}.json")

    def add(self, resolved, title):
        """Keep a finished fight. Very short skirmishes are left out of the history."""
        if resolved["last"] - resolved["start"] < MIN_DURATION_MS and not resolved.get("has_boss"):
            return
        entry = summary_of(resolved, title)
        if not entry["players"]:
            return
        with self.lock:
            try:
                with open(self._file(entry["id"]), "w", encoding="utf-8") as f:
                    json.dump(to_json(resolved), f, ensure_ascii=False)
            except (OSError, TypeError, ValueError):
                return
            self.index = [e for e in self.index if e["id"] != entry["id"]]
            self.index.append(entry)
            self._prune()
            self._save_index()

    def _prune(self):
        normal = [e for e in self.index if not e.get("favorite")]
        drop = normal[:-KEEP] if len(normal) > KEEP else []
        for e in drop:
            try:
                os.remove(self._file(e["id"]))
            except OSError:
                pass
            self._cache.pop(e["id"], None)
        gone = {e["id"] for e in drop}
        self.index = [e for e in self.index if e["id"] not in gone]

    def entries(self):
        with self.lock:
            return list(reversed(self.index))

    def load(self, fid):
        with self.lock:
            if fid in self._cache:
                return self._cache[fid]
            try:
                with open(self._file(fid), encoding="utf-8") as f:
                    data = from_json(json.load(f))
            except (OSError, ValueError, KeyError, TypeError):
                return None
            if len(self._cache) > 20:
                self._cache.clear()
            self._cache[fid] = data
            return data

    def set_favorite(self, fid, on):
        with self.lock:
            for e in self.index:
                if e["id"] == fid:
                    e["favorite"] = bool(on)
            self._save_index()

    def delete(self, fid):
        with self.lock:
            self.index = [e for e in self.index if e["id"] != fid]
            self._cache.pop(fid, None)
            try:
                os.remove(self._file(fid))
            except OSError:
                pass
            self._save_index()


def day_label(epoch_ms, now=None):
    now = now or time.time()
    t = time.localtime(epoch_ms / 1000)
    today = time.localtime(now)
    if t.tm_yday == today.tm_yday and t.tm_year == today.tm_year:
        return "today"
    if (time.mktime(today) - time.mktime(t)) < 2 * 86400 and t.tm_yday == today.tm_yday - 1:
        return "yesterday"
    return time.strftime("%d.%m.%Y", t)
