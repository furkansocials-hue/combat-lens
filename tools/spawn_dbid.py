"""Check reading the account id (dbid) out of player spawns (`45 36`).
python tools/spawn_dbid.py kayitlar/DOSYA.txt

The dbid sits after the name as `01 <dbid u64> 04 CD 00`; its top u16 is the
home server. Verified against the party roster's dbids, and for everyone else
by consistency (one name, one dbid)."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter, protocol  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.protocol import find_spawn_dbid, read_varint  # noqa: E402
from aion2meter.store import Store  # noqa: E402

frames = []
o = protocol.StreamProcessor.parse_perfect_packet
protocol.StreamProcessor.parse_perfect_packet = lambda self, pkt: (frames.append(bytes(pkt)), o(self, pkt))[1]
gd = GameData()
st = Store(gd, profile_path=None)
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

seen = collections.defaultdict(collections.Counter)
spawns = found = 0
for p in frames:
    _, ln = read_varint(p, 0)
    if p[ln:ln + 2] != b"\x45\x36":
        continue
    eid, n = read_varint(p, ln + 2)
    m2 = ln + 2 + n + 4
    if m2 + 1 >= len(p) or not p[m2] & 1:
        continue
    nl = p[m2 + 1]
    name = protocol.exact_name(p[m2 + 2:m2 + 2 + nl])
    if not name:
        continue
    spawns += 1
    dbid = find_spawn_dbid(p, m2 + 2 + nl)
    if dbid is not None:
        found += 1
        seen[name][dbid] += 1
print(f"oyuncu belirme paketi: {spawns}, hesap no bulunan: {found}")
bad = {n: c for n, c in seen.items() if len(c) > 1}
print("bir isme birden fazla hesap no:", bad or "yok")
for name, m in st.roster.items():
    got = seen.get(name)
    print(f"  {name:14s} parti listesi={m['dbid']}  belirme paketi={dict(got) if got else None}  "
          f"{'DOĞRU' if got and set(got) == {m['dbid']} else '-'}")
