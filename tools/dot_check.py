"""DoT ticks (`05 38`, damage) that the allowlist dropped, per actor and skill.
python tools/dot_check.py kayitlar/DOSYA.txt"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter, protocol  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.protocol import read_varint, u32le  # noqa: E402
from aion2meter.store import Store  # noqa: E402

dropped = collections.Counter()
dropped_n = collections.Counter()
kept = collections.Counter()
effects = collections.Counter()
orig = protocol.StreamProcessor.parse_dot_packet


def parse(self, pkt):
    o = self._opcode_at(pkt)
    if o >= 0 and len(pkt) > o + 1 and pkt[o] == 0x05 and pkt[o + 1] == 0x38:
        p = o + 2
        target, n = read_varint(pkt, p)
        p += max(n, 0)
        if n > 0 and p < len(pkt):
            effect = pkt[p]
            p += 1
            actor, n = read_varint(pkt, p)
            p += max(n, 0)
            _, n2 = read_varint(pkt, p)
            p += max(n2, 0)
            if n > 0 and n2 > 0 and p + 4 <= len(pkt):
                skill = int(u32le(pkt, p) / 100)
                amount, n3 = read_varint(pkt, p + 4)
                if n3 > 0 and 0 < amount < 99_999_999 and actor != target:
                    effects[effect] += 1
                    if effect in (0x02, 0x0A):
                        key = (actor, skill)
                        if skill in self.gd.dot_ids:
                            kept[key] += amount
                        else:
                            dropped[key] += amount
                            dropped_n[key] += 1
    return orig(self, pkt)


protocol.StreamProcessor.parse_dot_packet = parse
gd = GameData()
st = Store(gd, profile_path=None)
meter.replay(sys.argv[1], st, gd, log=lambda m: None)
print("05 38 etki türleri:", dict(effects))
lid = st.local_identity()[0]
print("sen:", st.local_identity())
print("listede olmadığı için atılan DoT'lar (en çok):")
for (actor, skill), amt in dropped.most_common(15):
    who = st.nicknames.get(st.resolve(actor), f"#{actor}") + (" (sen)" if actor == lid else "")
    print(f"   {who:16s} {skill:>9d} {gd.skill_name(skill) or '?':28s} x{dropped_n[(actor, skill)]:<4d} {amt:>9,}")
mine_kept = sum(v for (a, _), v in kept.items() if a == lid)
mine_drop = sum(v for (a, _), v in dropped.items() if a == lid)
print(f"senin DoT hasarın: sayılan {mine_kept:,}  atılan {mine_drop:,}")
