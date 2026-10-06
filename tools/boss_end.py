"""How does a boss fight end in the stream? Last hits, HP feed and death records per boss.
python tools/boss_end.py kayitlar/DOSYA.txt"""
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
ev = collections.defaultdict(list)
od, oh, odead = st.append_damage, st.set_mob_current_hp, st.mark_dead
st.append_damage = lambda **kw: (ev[kw["target"]].append((st.now, "hit", kw["damage"])), od(**kw))[1]
st.set_mob_current_hp = lambda e, v: (ev[e].append((st.now, "hp", v)), oh(e, v))[1]
st.mark_dead = lambda e: (ev[e].append((st.now, "DEATH", None)), odead(e))[1]
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

big = sorted(((st.mob_max_hp.get(e, 0), e) for e in ev if st.mob_max_hp.get(e, 0) >= 500_000), reverse=True)
print("aday:", len(big))
for mx, e in big[:40]:
    name = gd.npc_name(st.mobs.get(e, 0)) or f"#{e}"
    evs = ev[e]
    hits = [t for t, k, _ in evs if k == "hit"]
    if not hits:
        continue
    last_hit = hits[-1]
    deaths = [t for t, k, _ in evs if k == "DEATH"]
    hp_vals = [(t, v) for t, k, v in evs if k == "hp"]
    zero = [t for t, v in hp_vals if v == 0]
    last_hp = hp_vals[-1][1] if hp_vals else None
    print(f"{name:26s} maks HP {mx:>10,}  boss tablosunda={e in st.bosses}  vuruş={len(hits)}"
          f"  son HP={last_hp}  HP=0 kaydı={'evet' if zero else 'yok'}"
          f"  ölüm paketi={'evet' if deaths else 'yok'}"
          + (f" (son vuruştan {(deaths[0] - last_hit) / 1000:+.1f} sn)" if deaths else ""))
