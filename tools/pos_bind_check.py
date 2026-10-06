"""Bind party names to entities by matching party-map positions with movement records,
and check the result against the names the game itself sent.
python tools/pos_bind_check.py kayitlar/DOSYA.txt"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter, protocol  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.protocol import read_varint  # noqa: E402
from aion2meter.store import Store  # noqa: E402

frames = []
orig_ppp = protocol.StreamProcessor.parse_perfect_packet
protocol.StreamProcessor.parse_perfect_packet = lambda self, pkt: (
    frames.append((self.store.now, bytes(pkt))), orig_ppp(self, pkt))[1]
gd = GameData()
st = Store(gd, profile_path=None)
meter.replay(sys.argv[1], st, gd, log=lambda m: None)
dbid_name = {m["dbid"].to_bytes(8, "little"): n for n, m in st.roster.items()}

party_keys = {}   # (x,y) bytes -> name
ent_keys = {}     # (x,y) bytes -> entity
votes = collections.Counter()
first_vote = {}
for ts, pkt in frames:
    _, ln = read_varint(pkt, 0)
    body = pkt[ln:]
    if len(body) < 12:
        continue
    if body[:2] == b"\x1c\x92" and len(body) >= 34:
        name = dbid_name.get(body[2:10])
        if name:
            key = body[26:34]
            party_keys[key] = name
            e = ent_keys.get(key)
            if e is not None:
                votes[(e, name)] += 1
                first_vote.setdefault((e, name), ts)
        continue
    if body[1] not in (0x36, 0x37, 0x38):
        continue
    e, n = read_varint(body, 2)
    if n <= 0 or e < 100:
        continue
    seg = body[2 + n:2 + n + 24]
    for k in range(0, max(0, len(seg) - 7)):
        key = seg[k:k + 8]
        if len(key) < 8:
            break
        if key in party_keys:
            votes[(e, party_keys[key])] += 1
            first_vote.setdefault((e, party_keys[key]), ts)
        ent_keys[key] = e

truth = {n: e for e, n in st.nicknames.items()}
by_name = collections.defaultdict(list)
for (e, name), v in votes.items():
    by_name[name].append((v, e))
for name in sorted(st.roster):
    cands = sorted(by_name.get(name, []), reverse=True)
    best = cands[0][1] if cands else None
    ok = "DOĞRU" if best == truth.get(name) else "YANLIŞ"
    print(f"{name:14s} oyunun dediği={truth.get(name)}  konumdan={best}  oylar={cands[:3]}  {ok}")
