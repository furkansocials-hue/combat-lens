"""Reconcile targets' live HP feed against the damage we read, step by step.
python tools/hp_reconcile.py kayitlar/DOSYA.txt ["Mob Name" | ENTITY_ID]

Without a name or id, every target with an HP feed is checked. Each HP update
is compared with the damage read since the previous one:
  match    HP fell by exactly what we read
  heal     HP went up (regeneration, a dummy resetting)
  absorbed we read more than HP fell (the HP update came early; the rest shows next step)
  unseen   HP fell by more than we read
absorbed and unseen come in pairs when an HP update lands between two hits of
one burst; summed over a fight they cancel out."""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import Store  # noqa: E402


def main(path, wanted=None):
    gd = GameData()
    st = Store(gd, profile_path=None)
    ev = []
    o_dmg, o_hp = st.append_damage, st.set_mob_current_hp

    def dmg(**kw):
        ev.append(("d", kw["target"], kw["damage"] + kw.get("multi_damage", 0), kw["actor"]))
        return o_dmg(**kw)

    def hp(eid, v):
        ev.append(("h", eid, v, None))
        return o_hp(eid, v)

    st.append_damage, st.set_mob_current_hp = dmg, hp
    meter.replay(path, st, gd, log=lambda m: None)

    with_hp = {e for k, e, _, _ in ev if k == "h"}
    hit = {e for k, e, _, _ in ev if k == "d"}
    targets = sorted(with_hp & hit)
    if wanted:
        targets = [t for t in targets if str(t) == wanted or gd.npc_name(st.mobs.get(t, 0)) == wanted]

    total = collections.Counter()
    amounts = collections.Counter()
    for eid in targets:
        kinds = collections.Counter()
        amt = collections.Counter()
        pending = 0
        last = None
        read_total = 0
        attackers = collections.Counter()
        for k, e, v, actor in ev:
            if e != eid:
                continue
            if k == "d":
                pending += v
                read_total += v
                attackers[st.nicknames.get(st.resolve(actor), f"#{actor}")] += v
                continue
            if last is not None:
                drop = last - v
                if drop == pending:
                    kind = "match"
                elif drop < 0:
                    kind = "heal"
                elif drop < pending:
                    kind = "absorbed"
                else:
                    kind = "unseen"
                kinds[kind] += 1
                amt[kind] += (pending - drop) if kind == "absorbed" else (drop - pending) if kind == "unseen" else 0
            pending = 0
            last = v
        steps = sum(kinds.values())
        if steps < 5:
            continue
        name = gd.npc_name(st.mobs.get(eid, 0)) or f"#{eid}"
        net = amt["unseen"] - amt["absorbed"]
        print(f"{name:22s} HP adımı {steps:5d}  birebir {kinds['match']:5d} (%{kinds['match'] / steps * 100:4.1f})"
              f"  iyileşme {kinds['heal']:4d}  okunan {read_total:>11,}  net fark {net:+,}"
              f"  vuranlar {dict(attackers.most_common(3))}")
        total.update(kinds)
        amounts["read"] += read_total
        amounts["net"] += net
    steps = sum(total.values())
    if steps:
        print(f"\nTOPLAM: {steps} HP adımı, birebir eşleşen %{total['match'] / steps * 100:.1f}; "
              f"okunan hasar {amounts['read']:,}, HP düşüşüyle net fark {amounts['net']:+,} "
              f"(%{amounts['net'] / max(1, amounts['read']) * 100:+.3f})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
