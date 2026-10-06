"""Do these names appear anywhere in a recording (raw or decompressed), and where?
python tools/find_names.py kayitlar/DOSYA.txt Name1 Name2 ..."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter, protocol  # noqa: E402
from aion2meter.gamedata import CLASSES, GameData  # noqa: E402
from aion2meter.protocol import read_varint  # noqa: E402
from aion2meter.store import Store  # noqa: E402

frames = []
o = protocol.StreamProcessor.parse_perfect_packet
protocol.StreamProcessor.parse_perfect_packet = lambda self, pkt: (frames.append(bytes(pkt)), o(self, pkt))[1]
raw = []
of = meter.Dispatcher.feed_chunk
meter.Dispatcher.feed_chunk = lambda self, f, ts, c: (raw.append(c), of(self, f, ts, c))[1]
gd = GameData()
st = Store(gd, profile_path=None)
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

fighters = {}
for enc in st.encounters():
    for t in enc.targets.values():
        for a in t.actors:
            r = st.resolve(a)
            fighters[r] = st.nicknames.get(r) or f"#{r} {CLASSES.get(st.actor_jobs.get(r), '?')}"
print("vuranlar:", fighters)
print("isimli varlıklar:", len(st.nicknames), sorted(st.nicknames.values())[:40])
for name in sys.argv[2:]:
    nb = name.encode()
    in_frames = [(p[read_varint(p, 0)[1]:read_varint(p, 0)[1] + 2].hex(), p.find(nb)) for p in frames if nb in p]
    in_raw = sum(c.count(nb) for c in raw)
    print(f"{name}: frame içinde {len(in_frames)} {in_frames[:4]}  ham akışta {in_raw}  "
          f"meter'daki id: {[e for e, n in st.nicknames.items() if n == name]}")
