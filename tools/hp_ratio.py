"""HP drop per damage read, for steps with exactly one hit between two HP updates.
python tools/hp_ratio.py kayitlar/DOSYA.txt

A target that takes damage 1:1 shows a ratio of 1.00; training scarecrows show
their own multiplier. A spread of ratios would mean misread hits."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import Store  # noqa: E402

gd = GameData()
st = Store(gd, profile_path=None)
ev = []
od, oh = st.append_damage, st.set_mob_current_hp
st.append_damage = lambda **kw: (ev.append(("d", kw["target"], kw["damage"] + kw.get("multi_damage", 0))), od(**kw))[1]
st.set_mob_current_hp = lambda e, v: (ev.append(("h", e, v)), oh(e, v))[1]
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

per_target = collections.defaultdict(collections.Counter)
state = {}
for k, e, v in ev:
    s = state.setdefault(e, {"last": None, "hits": []})
    if k == "d":
        s["hits"].append(v)
        continue
    if s["last"] is not None and len(s["hits"]) == 1 and s["hits"][0] >= 100:
        drop = s["last"] - v
        if drop > 0:
            per_target[e][round(drop / s["hits"][0], 2)] += 1
    s["last"] = v
    s["hits"] = []

for e, ratios in sorted(per_target.items(), key=lambda kv: -sum(kv[1].values())):
    n = sum(ratios.values())
    if n < 5:
        continue
    top, cnt = ratios.most_common(1)[0]
    near = sum(c for r, c in ratios.items() if abs(r - top) <= 0.02)
    name = gd.npc_name(st.mobs.get(e, 0)) or f"#{e}"
    print(f"{name:26s} tek vuruşlu adım {n:5d}  oran {top:.2f}  bu orana uyan %{near / n * 100:.1f}"
          f"  diğer: {[(r, c) for r, c in ratios.most_common(4)[1:]]}")
