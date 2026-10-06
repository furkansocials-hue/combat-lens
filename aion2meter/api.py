"""JSON payloads for the web UI: the overlay's live state, a fight's full analysis, the history."""
import os

from .history import day_label
from .report import MODE_ALL, MODE_TARGET, build_view, row_summary, skill_rows, visible_rows

HEAL_MIN = 100  # largest single heal below this: a status record, not a heal
ROW_FIELDS = ("key", "name", "job", "is_local", "in_party", "total", "dps", "dps_own", "dps_fight", "pct",
              "crit_rate", "combat_power", "level", "hits", "active_ms")


def _icon(kind_url):
    kind, url = kind_url
    if kind == "url" and url:
        return "/icon/" + os.path.basename(url)
    return kind  # "basic" or "unknown": the page draws a glyph


def _view_head(view, enc_live):
    return {
        "id": view["id"],
        "title": view["title"],
        "multi": view["multi"],
        "duration_ms": view["duration_ms"],
        "hp": view["hp"],
        "party_known": view["party_known"],
        "shared_time": view["shared_time"],
        "has_boss": view["has_boss"],
        "end_reason": view["end_reason"],
        "live": enc_live,
    }


def _mode(mode):
    return mode if mode in (MODE_ALL, MODE_TARGET) else MODE_ALL


def overlay_state(app, mode, tab, pinned, clear_after_s=0):
    """`clear_after_s`: a finished fight leaves the panel this long after its last hit (0: it stays
    until the next fight). It is still in the history and the ‹ › arrows."""
    st = app.store
    ds = app.dispatcher.status()
    lid, lname = st.local_identity()
    out = {
        "status": {
            "npcap": app.npcap_ok,
            "locked": ds["locked"],
            "silent": ds.get("silent_ms", 0) > 10_000,
            "dropped": ds.get("dropped", 0),
            "paused": st.paused,
            "local": lname or (f"#{lid}" if lid else None),
            "guess": st.local_is_guess(),
            "update": app.update_info,
            "clickthrough": app.clickthrough,
        },
        "view": None,
        "nav": None,
    }
    encs = st.encounters()
    if not encs:
        return out
    ids = [e.id for e in encs]
    newest = encs[0]
    newest_cleared = bool(clear_after_s and newest.frozen is not None
                          and st.now - newest.last > clear_after_s * 1000)
    enc = next((e for e in encs if e.id == pinned), None)
    if enc is None:
        if newest_cleared:  # index -1: the empty panel before the newest fight in the ‹ › list
            out["nav"] = {"index": -1, "count": len(ids), "ids": ids, "newest_cleared": True}
            return out
        enc = newest
    resolved = st.view(enc)
    view = build_view(resolved, _mode(mode))
    group = visible_rows(view, "party")
    rows = [r for r in group if r["is_local"]] if tab == "me" else group
    out["view"] = dict(_view_head(view, enc.frozen is None),
                       rows=[{k: r.get(k) for k in ROW_FIELDS} for r in rows],
                       total=sum(r["total"] for r in group),
                       total_dps=sum(r["dps"] for r in group),
                       zone=resolved.get("zone"))
    out["nav"] = {"index": ids.index(enc.id), "count": len(ids), "ids": ids, "newest_cleared": newest_cleared}
    return out


def _find(app, fid):
    st = app.store
    for e in st.encounters():
        if e.id == fid:
            return st.view(e), e.frozen is None
    data = app.history.load(fid) if fid else None
    return (data, False) if data else (None, False)


def encounter_detail(app, fid, mode):
    resolved, live = _find(app, fid)
    if resolved is None:
        encs = app.store.encounters()
        if not encs:
            return None
        resolved, live = app.store.view(encs[0]), encs[0].frozen is None
    gd = app.gd
    view = build_view(resolved, _mode(mode))
    rows = visible_rows(view, "party")
    t0 = min((min(r.get("buckets", {}) or [0]) for r in rows), default=0)
    players = []
    for r in rows:
        summ = row_summary(r, gd)
        skills = []
        for sk in skill_rows(r, gd, r["seconds"]):
            sk = dict(sk)
            sk["icon"] = _icon(sk["icon"])
            sk.pop("key", None)
            skills.append(sk)
        heal = resolved.get("heals", {}).get(r["key"])
        heals = []
        if heal:
            for (code, hot), h in sorted(heal["skills"].items(), key=lambda kv: -kv[1].total):
                if h.max < HEAL_MIN:
                    continue  # stack counts and buff ticks, not healing
                heals.append({"name": (gd.skill_name(code) or f"Skill {code}") + (" (HoT)" if hot else ""),
                              "icon": _icon(gd.icon_for(code)), "total": h.total, "hits": h.hits, "max": h.max})
        buckets = r.get("buckets", {})
        players.append(dict(
            {k: r.get(k) for k in ROW_FIELDS},
            summary={k: v for k, v in summ.items() if k != "targets"},
            targets=[{"name": n, "boss": b, "total": d} for (n, b), d in summ["targets"][:12]],
            skills=skills,
            heal_total=sum(h["total"] for h in heals),
            heals=heals,
            timeline=sorted((sec - t0, d) for sec, d in buckets.items()),
        ))
    targets = []
    for t in resolved["targets"]:
        dealt = {k: pp["total"] for k, pp in t["players"].items() if k in view["rows"]}
        if dealt:
            targets.append({"name": t["name"], "boss": t["is_boss"], "total": sum(dealt.values()),
                            "dead": t.get("dead"), "max_hp": t.get("max_hp")})
    targets.sort(key=lambda t: -t["total"])
    return dict(_view_head(view, live), zone=resolved.get("zone"), start=resolved["start"],
                players=players, targets=targets[:30],
                total=sum(r["total"] for r in rows), total_dps=sum(r["dps"] for r in rows))


_SUMMARIES = {}  # encounter id -> list entry of a finished, in-memory fight


def _entry(resolved, live):
    view = build_view(resolved)
    rows = visible_rows(view, "party")
    return {"id": resolved["id"], "title": view["title"], "zone": resolved.get("zone"), "start": resolved["start"],
            "duration_ms": view["duration_ms"], "live": live, "favorite": False, "has_boss": view["has_boss"],
            "end_reason": resolved.get("end_reason"),
            "players": [{"name": r["name"], "job": r["job"], "local": r["is_local"]} for r in rows][:12],
            "total": sum(r["total"] for r in rows)}


def history_list(app):
    """Saved fights plus this session's (the running one, short skirmishes, a replay's fights)."""
    st = app.store
    saved = app.history.entries()
    known = {e["id"] for e in saved}
    items = [dict(e, live=False) for e in saved]
    for enc in st.encounters():
        if enc.frozen is None:
            items.append(_entry(st.view(enc), True))
        elif enc.id not in known:
            e = _SUMMARIES.get(enc.id)
            if e is None:
                e = _SUMMARIES[enc.id] = _entry(enc.frozen, False)
            items.append(e)
    items.sort(key=lambda e: -e["start"])
    for e in items:
        e["day"] = day_label(e["start"])
    return items
