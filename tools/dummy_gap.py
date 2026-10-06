"""On a training scarecrow (HP falls 4.5x the damage), how much HP loss is not explained by hits we read?
python tools/dummy_gap.py kayitlar/DOSYA.txt ENTITY_ID [FACTOR]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import Store  # noqa: E402

gd = GameData()
st = Store(gd, profile_path=None)
eid = int(sys.argv[2])
factor = float(sys.argv[3]) if len(sys.argv) > 3 else 4.5
ev = []
od, oh = st.append_damage, st.set_mob_current_hp
st.append_damage = lambda **kw: (ev.append((st.now, "d", kw)) if kw["target"] == eid else None, od(**kw))[1]
st.set_mob_current_hp = lambda e, v: (ev.append((st.now, "h", v)) if e == eid else None, oh(e, v))[1]
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

read = 0
explained = 0
unexplained = 0
pending = []
last = None
samples = []
for ts, k, x in ev:
    if k == "d":
        pending.append(x)
        read += x["damage"] + x.get("multi_damage", 0)
        continue
    if last is not None and x < last:  # a drop (resets to full are skipped)
        drop = last - x
        want = sum(p["damage"] + p.get("multi_damage", 0) for p in pending) * factor
        if drop > want + factor * 2:
            unexplained += (drop - want) / factor
            if len(samples) < 12:
                samples.append((ts, last, x, drop, round(want), [(gd.skill_name(p["skill"]), p["damage"], p.get("multi_damage", 0), p.get("is_dot")) for p in pending]))
        explained += min(drop, want) / factor
    pending = []
    last = x
print(f"okunan hasar {read:,}   HP'den açıklanamayan (hasar cinsinden) ~{unexplained:,.0f}  (%{unexplained / max(read, 1) * 100:.2f})")
for s in samples:
    print("  ", s)
