"""Turns a resolved encounter into what the meter shows: player rows and their skills."""

MODE_ALL = "all"        # every target in the encounter
MODE_TARGET = "target"  # the main target only (the boss, else the most-hit mob)


def _main_target(targets, players):
    def dealt(t):
        return sum(pp["total"] for k, pp in t["players"].items() if k in players)
    candidates = [t for t in targets if dealt(t) > 0]
    if not candidates:
        return None
    bosses = [t for t in candidates if t["is_boss"]]
    return max(bosses or candidates, key=dealt)


def _span(targets, players):
    """First to last hit by `players` (your group) on `targets`."""
    first = last = None
    for t in targets:
        for k, pp in t["players"].items():
            if k in players:
                first = pp["first"] if first is None else min(first, pp["first"])
                last = pp["last"] if last is None else max(last, pp["last"])
    return (last - first) if first is not None else 0


def build_view(resolved, mode=MODE_ALL):
    # Only your group counts: you, your party, or (without a party list) whoever
    # hits the same targets as you. Their hits alone set the fight's duration.
    players = {k: p for k, p in resolved["players"].items() if p["in_party"]}
    targets = resolved["targets"]
    hp_target = None
    multi = 0  # several targets and no boss: the title is just their count
    if mode == MODE_TARGET:
        main = _main_target(targets, players)
        selected = [main] if main else []
        duration = _span(selected, players)
        title = main["name"] if main else "-"
        hp_target = main
    else:
        selected = targets
        hit = [t for t in targets if any(k in players for k in t["players"])]
        duration = _span(hit, players)
        bosses = [t for t in hit if t["is_boss"]]
        if bosses:
            hp_target = max(bosses, key=lambda t: t["total"])
            title = hp_target["name"]
        elif len(hit) == 1:
            hp_target = hit[0]
            title = hit[0]["name"]
        else:
            title = f"{len(hit)} hedef"
            multi = len(hit)

    seconds = max(duration, 1000) / 1000.0
    rows = {}
    for t in selected:
        for k, pp in t["players"].items():
            p = players.get(k)
            if p is None:
                continue
            r = rows.get(k)
            if r is None:
                r = rows[k] = dict(p, total=0, skills={}, by_target={}, first=pp["first"], last=pp["last"])
            r["total"] += pp["total"]
            b = r.setdefault("buckets", {})
            for sec, d in pp.get("buckets", {}).items():
                b[sec] = b.get(sec, 0) + d
            r["first"] = min(r["first"], pp["first"])
            r["last"] = max(r["last"], pp["last"])
            tk = (t["name"], t["is_boss"])
            r["by_target"][tk] = r["by_target"].get(tk, 0) + pp["total"]
            for sk, s in pp["skills"].items():
                agg = r["skills"].get(sk)
                if agg is None:
                    r["skills"][sk] = agg = type(s)()
                agg.absorb(s)

    # In a party everyone shares the fight's duration (the usual meter DPS). Without
    # one, the people around you fight on their own, so each is timed from their own
    # first hit to their own last: someone still hitting the next dummy must not
    # lower your DPS, nor your stopping lower theirs.
    shared = resolved["party_known"]
    for r in rows.values():
        r["active_ms"] = r["last"] - r["first"]
        r["seconds_own"] = max(r["active_ms"], 1000) / 1000.0
        r["dps_own"] = r["total"] / r["seconds_own"]
        r["dps_fight"] = r["total"] / seconds
        r["seconds"] = seconds if shared else r["seconds_own"]
        r["dps"] = r["total"] / r["seconds"]
        r["hits"] = sum(s.hits for s in r["skills"].values())
        direct = [s for (_, dot), s in r["skills"].items() if not dot]
        dh = sum(s.hits for s in direct)
        r["crit_rate"] = (sum(s.crit for s in direct) / dh) if dh else 0.0

    hp = None
    if hp_target is not None and hp_target.get("max_hp"):
        cur = hp_target.get("cur_hp")
        if cur is None:
            cur = max(0, hp_target["max_hp"] - hp_target["total"])
        hp = (min(cur, hp_target["max_hp"]), hp_target["max_hp"])
    return {
        "hp": hp,
        "title": title,
        "multi": multi,
        "duration_ms": duration,
        "seconds": seconds,
        "rows": rows,
        "party_known": resolved["party_known"],
        "shared_time": shared,
        "local_known": resolved.get("local_known", False),
        "has_boss": resolved["has_boss"],
        "end_reason": resolved["end_reason"],
        "local_name": resolved["local_name"],
        "id": resolved["id"],
    }


def visible_rows(view, who):
    """who='me' -> only you; who='party' -> your group (rows are already limited to it)."""
    rows = list(view["rows"].values())
    if who == "me":
        rows = [r for r in rows if r["is_local"]]
    rows.sort(key=lambda r: -r["total"])
    group_total = sum(r["total"] for r in rows) or 1
    for r in rows:
        r["pct"] = r["total"] / group_total * 100.0
    return rows


def party_share(view, row):
    """Your share of the party's damage (party = everyone shown on the party tab)."""
    rows = visible_rows(view, "party")
    total = sum(r["total"] for r in rows)
    return row["total"] / total * 100.0 if total else 0.0


_TAGS = ("crit", "back", "front", "perfect", "double", "parry", "smite", "powershard")


def skill_rows(row, gamedata, seconds):
    """One entry per skill: totals, per-hit stats, and each hit tag as a count and a rate."""
    out = []
    total = row["total"] or 1
    for (code, is_dot), s in row["skills"].items():
        hits = s.hits or 1
        entry = {
            "key": (code, is_dot),
            "code": code,
            "is_dot": is_dot,
            "name": gamedata.display_name(code, is_dot),
            "icon": gamedata.icon_for(code),
            "total": s.total,
            "pct": s.total / total * 100.0,
            "dps": s.total / seconds,
            "hits": s.hits,
            "avg": s.total / hits,
            "max": s.max,
            "min": s.min or 0,
            "mh_events": s.mh_events,
            "mh_hits": s.mh_hits,
            "mh_damage": s.mh_damage,
        }
        for tag in _TAGS:
            n = getattr(s, tag)
            entry[tag + "_n"] = n
            entry[tag] = n / hits * 100.0
        out.append(entry)
    out.sort(key=lambda r: -r["total"])
    return out


def row_summary(row, gamedata):
    """A player's whole-fight figures for the details window."""
    direct = [(k, s) for k, s in row["skills"].items() if not k[1]]
    dots = [s for k, s in row["skills"].items() if k[1]]
    dh = sum(s.hits for _, s in direct)

    def rate(tag):
        return sum(getattr(s, tag) for _, s in direct) / dh * 100.0 if dh else 0.0

    biggest = max(direct, key=lambda ks: ks[1].max, default=None)
    return {
        "direct_hits": dh,
        "dot_ticks": sum(s.hits for s in dots),
        "dot_total": sum(s.total for s in dots),
        "crit": rate("crit"),
        "back": rate("back"),
        "front": rate("front"),
        "smite": rate("smite"),
        "perfect": rate("perfect"),
        "double": rate("double"),
        "parry": rate("parry"),
        "max_hit": biggest[1].max if biggest else 0,
        "max_hit_skill": gamedata.display_name(biggest[0][0], False) if biggest else "",
        "skills": len(row["skills"]),
        "targets": sorted(row.get("by_target", {}).items(), key=lambda kv: -kv[1]),
    }


def fmt_num(v):
    """Short number, Turkish style: 9,89K · 20,3K · 1,38M."""
    v = float(v)
    if abs(v) >= 1e9:
        s = f"{v / 1e9:.2f}B"
    elif abs(v) >= 1e6:
        s = f"{v / 1e6:.2f}M"
    elif abs(v) >= 1e4:
        s = f"{v / 1e3:.1f}K"
    elif abs(v) >= 1e3:
        s = f"{v / 1e3:.2f}K"
    else:
        s = f"{v:.0f}"
    return s.replace(".", ",")


def fmt_pct(v, digits=1):
    return "%" + f"{v:.{digits}f}".replace(".", ",")


def fmt_full(v):
    return f"{int(v):,}".replace(",", ".")


def fmt_time(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def summary_text(store, mode=MODE_ALL, top_skills=8):
    from .gamedata import CLASSES
    lines = []
    for enc in store.encounters():
        view = build_view(store.view(enc), mode)
        lines.append(f"=== Savaş #{view['id']}  {view['title']}  süre {fmt_time(view['duration_ms'])}"
                     f"  ({'canlı' if enc.frozen is None else view['end_reason']})")
        for r in visible_rows(view, "party"):
            tag = " (sen)" if r["is_local"] else ""
            job = CLASSES.get(r["job"], r["job"] or "?")
            lines.append(f"  {r['name']}{tag:6s} {job:12s} DPS {fmt_num(r['dps']):>8s}  "
                         f"toplam {fmt_full(r['total']):>12s}  %{r['pct']:5.1f}  krit %{r['crit_rate'] * 100:4.1f}")
            for s in skill_rows(r, store.gd, view["seconds"])[:top_skills]:
                lines.append(f"      {s['name'][:28]:28s} {fmt_full(s['total']):>11s}  %{s['pct']:5.1f}  "
                             f"x{s['hits']:<4d} maks {fmt_full(s['max'])}")
    return "\n".join(lines) if lines else "(henüz savaş verisi yok)"
