"""What the window would show for a recording: who you are, and the party tab.
python tools/replay_check.py kayitlar/DOSYA.txt"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import CLASSES, GameData  # noqa: E402
from aion2meter.report import build_view, fmt_num, visible_rows  # noqa: E402
from aion2meter.store import Store  # noqa: E402

gd = GameData()
st = Store(gd)  # uses son_karakter.json like the real window
first_known = []
o = st.append_damage
t0 = []


def dmg(**kw):
    t0.append(st.now) if not t0 else None
    r = o(**kw)
    if not first_known and st.local_identity()[0] is not None:
        first_known.append((st.now - t0[0]) / 1000)
    return r


st.append_damage = dmg
meter.replay(sys.argv[1], st, gd, log=lambda m: None)
print("sen:", st.local_identity(), "tahmini" if st.local_is_guess() else "kesin",
      f"(ilk hasardan {first_known[0]:.1f} sn sonra)" if first_known else "")
for enc in st.encounters()[:3]:
    view = build_view(st.view(enc))
    print(f"--- {view['title']}  parti listesi={view['party_known']}")
    for r in visible_rows(view, "party"):
        print(f"   {r['name']:12s} {CLASSES.get(r['job'], '?'):12s} DPS {fmt_num(r['dps']):>7s}"
              f"  toplam {fmt_num(r['total']):>7s}{'  (sen)' if r['is_local'] else ''}")
