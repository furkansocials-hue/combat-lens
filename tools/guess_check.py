"""Would the meter find you without the game's self record? Replays with that record ignored.
python tools/guess_check.py kayitlar/DOSYA.txt"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import Store  # noqa: E402

gd = GameData()
truth = Store(gd, profile_path=None)
meter.replay(sys.argv[1], truth, gd, log=lambda m: None)
real_name = truth.local_identity()[1]

st = Store(gd, profile_path=None)
st.set_local_identity = lambda eid, name: None  # pretend it never came
st.note_loot_owner = lambda *a: None
samples = []
o = st.append_damage


def dmg(**kw):
    r = o(**kw)
    if st.records % 2000 == 0:
        eid, name = st.local_identity()
        samples.append((st.records, eid, st.nicknames.get(eid) if eid else None))
    return r


st.append_damage = dmg
meter.replay(sys.argv[1], st, gd, log=lambda m: None)
right = sum(1 for _, _, n in samples if n == real_name)
wrong = [(r, e, n) for r, e, n in samples if e is not None and n != real_name]
unknown = sum(1 for _, e, _ in samples if e is None)
print(f"gerçek: {real_name}  örnek: {len(samples)}  doğru: {right}  bilinmiyor: {unknown}  yanlış: {len(wrong)}")
print("yanlışlar:", wrong[:10])
