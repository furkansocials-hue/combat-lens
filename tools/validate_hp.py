"""Accuracy check on a recording: for every mob that died, does the damage we
read add up to its max HP?  (python tools/validate_hp.py kayitlar/DOSYA.txt)

Every hit from every player is summed per target here, independent of the
meter's encounter logic. A kill should land close to 100% (a little over is
overkill on the last hit; well under means hits were missed)."""
import collections
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import Store  # noqa: E402


def main(path):
    gd = GameData()
    st = Store(gd)
    dealt = collections.Counter()
    hits = collections.Counter()
    last_hit = {}
    orig = st.append_damage

    def collect(**kw):
        dealt[kw["target"]] += kw["damage"] + kw.get("multi_damage", 0)
        hits[kw["target"]] += 1
        last_hit[kw["target"]] = kw["damage"] + kw.get("multi_damage", 0)
        return orig(**kw)

    st.append_damage = collect
    meter.replay(path, st, gd, log=lambda m: None)

    ratios = []
    rows = []
    for tid in st.dead:
        mx = st.mob_max_hp.get(tid)
        if not mx or tid not in dealt or tid in st.known_players:
            continue
        # Some adds spawn with part of their HP; the kill is measured against that.
        mx = min(mx, st.mob_spawn_hp.get(tid) or mx)
        r = dealt[tid] / mx
        ratios.append(r)
        name = gd.npc_name(st.mobs.get(tid, 0)) or f"#{tid}"
        rows.append((name, mx, dealt[tid], r, hits[tid], last_hit[tid]))
    rows.sort(key=lambda x: -x[1])
    print(f"{'mob':32s} {'HP':>10s} {'okunan':>10s} {'oran':>7s} {'vuruş':>6s}")
    for name, mx, d, r, h, lh in rows[:40]:
        print(f"{name[:32]:32s} {mx:>10,} {d:>10,} {r * 100:6.1f}% {h:>6d}")
    if ratios:
        within = sum(1 for r in ratios if 0.97 <= r <= 1.25)
        print(f"\nölen mob: {len(ratios)}  medyan oran: %{statistics.median(ratios) * 100:.1f}  "
              f"%97-%125 aralığında: {within}/{len(ratios)}")
        low = [r for r in rows if r[3] < 0.97]
        if low:
            print("eksik görünenler:", [(n, f"{r * 100:.0f}%") for n, _, _, r, _, _ in low[:15]])


if __name__ == "__main__":
    main(sys.argv[1])
