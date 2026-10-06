"""DoT ticks after your last direct hit, per burst of attacks on a target.
python tools/trailing_dot.py kayitlar/DOSYA.txt ACTOR_ID"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import Store  # noqa: E402

gd = GameData()
st = Store(gd, profile_path=None)
actor = int(sys.argv[2])
recs = []
od = st.append_damage
st.append_damage = lambda **kw: (recs.append((st.now, kw)) if kw["actor"] == actor else None, od(**kw))[1]
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

bursts = []
cur = None
for ts, kw in recs:
    if cur is None or ts - cur["last"] > 20_000:
        cur = {"first": ts, "last": ts, "last_direct": None, "direct": 0, "dot": 0, "trail": 0, "trail_n": 0}
        bursts.append(cur)
    cur["last"] = ts
    dmg = kw["damage"] + kw.get("multi_damage", 0)
    if kw.get("is_dot"):
        cur["dot"] += dmg
        if cur["last_direct"] is not None:
            cur.setdefault("ticks", []).append((ts, dmg))
    else:
        cur["direct"] += dmg
        cur["last_direct"] = ts
        cur["ticks"] = []
for b in bursts:
    ticks = b.get("ticks", [])
    trail = sum(d for _, d in ticks)
    tail = (ticks[-1][0] - b["last_direct"]) / 1000 if ticks else 0
    span_direct = (b["last_direct"] - b["first"]) / 1000 if b["last_direct"] else 0
    print(f"vuruş süresi {span_direct:5.1f} sn  son vuruştan sonra {len(ticks):2d} DoT tiki, {trail:6,} hasar, "
          f"{tail:4.1f} sn daha sürüyor  (toplam {b['direct'] + b['dot']:,})")
