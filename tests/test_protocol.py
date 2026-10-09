"""Parser tests. Byte samples marked "live" are from real captures quoted in the
A2Tools test-suite; the rest are built to the documented record layouts."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.lz4 import decompress_block  # noqa: E402
from aion2meter.meter import Reassembler  # noqa: E402
from aion2meter.protocol import (BUNDLE, StreamProcessor, exact_name,  # noqa: E402
                                 read_varint, varint_ending_at, walk)
from aion2meter.report import build_view, skill_rows, visible_rows  # noqa: E402
from aion2meter.store import Store as _Store  # noqa: E402

GD = GameData("en")


def Store(gd):  # never touch the real son_karakter.json from tests
    return _Store(gd, profile_path=None)


def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def u32(v):
    return v.to_bytes(4, "little")


def packet(payload):
    """`<varint len> payload` with len = physical size + 3 (the AION 2 quirk)."""
    for ln in (1, 2, 3):
        total = ln + len(payload)
        pre = varint(total + 3)
        if len(pre) == ln:
            return pre + payload
    raise ValueError


def lz4_literals(data):
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    rest = n - 15
    ext = b"\xff" * (rest // 255) + bytes([rest % 255])
    return bytes([0xF0]) + ext + data


def bundle(inner):
    body = b"\xff\xff" + u32(len(inner)) + lz4_literals(inner)
    # An outer bundle occupies len - 3 + 1 bytes, prefix included.
    for ln in (1, 2, 3):
        total = ln + len(body)
        pre = varint(total + 2)
        if len(pre) == ln:
            return pre + body
    raise ValueError


def damage_record(target, actor, skill, damage, crit=False, scalar=16000, back=False):
    """04 38 record, and_result 5 layout (12-byte block after the type)."""
    switch = 5
    block = bytearray(12)
    if back:
        block[2] = 0x01  # direction byte
    return (b"\x04\x38" + varint(target) + varint(switch) + varint(0) + varint(actor) + u32(skill)
            + b"\x00" + varint(3 if crit else 1) + bytes(block)
            + varint(0) + varint(scalar) + varint(damage) + varint(0))


def new():
    store = Store(GD)
    return store, StreamProcessor(store, GD)


class Framing(unittest.TestCase):
    def test_back_to_back_packets(self):
        buf = packet(b"\x23\x36\x01") + packet(b"\x41\x36\x02\x03")
        frames, consumed = walk(buf)
        self.assertEqual(len(frames), 2)
        self.assertEqual(consumed, len(buf))
        self.assertEqual(buf[frames[0][1] + frames[0][3]:frames[0][2]], b"\x23\x36\x01")

    def test_padding_and_fragment(self):
        full = b"\x00\x00" + packet(b"\x01\x02\x03")
        frames, consumed = walk(full + b"\x40")
        self.assertEqual(len(frames), 1)
        self.assertEqual(consumed, len(full), "the fragment must wait for more bytes")

    def test_bundle_extra_byte(self):
        payload = bytes([0xFF, 0xFF, 0x10, 0, 0, 0, 0xAA, 0xBB])
        buf = packet(payload) + b"\x00"
        frames, _ = walk(buf)
        self.assertEqual(frames[0][0], BUNDLE)
        self.assertEqual(frames[0][2] - frames[0][1], len(buf))

    def test_lz4_overlap(self):
        # "abc" then a match of 9 at offset 3 -> "abcabcabcabc"
        block = bytes([0x35]) + b"abc" + b"\x03\x00" + b"\x10z"
        out = decompress_block(block, 64)
        self.assertEqual(out, b"abcabcabcabcz")


class Names(unittest.TestCase):
    def test_exact_name(self):
        for name in ["A", "é", "あ", "ApexZ", "Amber1", "Zoë", "さくら", "전사", "Abcdefghijkl"]:
            self.assertEqual(exact_name(name.encode()), name)
        for field in [b"Abcdefghijklm", b"12345", b"Apex Z", b"ApexZ\x06", b"\x05ApexZ", b"", b"\xc3"]:
            self.assertIsNone(exact_name(field))

    def test_varint_ending_at(self):
        self.assertEqual(varint_ending_at(bytes([1, 0x9A, 0x6D, 0xE2, 0x07]), 3, 0, 100, 99_999), 13978)
        self.assertEqual(varint_ending_at(bytes([1, 0xED, 0x74, 0x18, 0x05]), 3, 0, 100, 99_999), 14957)
        self.assertEqual(varint_ending_at(bytes([1, 0x6D, 0xE2, 0x07]), 2, 0, 100, 99_999), 109)
        self.assertEqual(varint_ending_at(bytes([1, 0xBD, 0x44, 0xE2, 0x07]), 3, 0, 100, 99_999), 8765)

    def test_self_record_live(self):
        """live: Naicha, entity 14957, server 1304, Cleric, level 28."""
        store, proc = new()
        rec = bytes.fromhex("3336ed745e91c12837064e616963686118051e000000011c0000007f0100007f010000"
                            "1c000000d002040000000000")
        proc.scan_masked_identity(rec)
        self.assertEqual(store.local_identity(), (14957, "Naicha"))
        self.assertEqual(store.self_profile, ("Naicha", "CL", 28, 1304))

    def test_kill_record_live(self):
        """live: a Sorcerer on Ventus (server 1305) killing a mob."""
        _, proc = new()
        rec = (bytes([0x04, 0x8d, 0xec, 0xde, 0x02, 0x72, 0x28, 0xe9, 0x00, 0xae, 0x0b, 0x19, 0x05, 0x05])
               + b"ApexZ" + b"\x06" + b"Ventus" + bytes([1, 0, 0, 0]))
        self.assertTrue(proc.scan_for_embedded_04_8d(rec))
        bad = bytearray(rec)
        bad[13] = 0x07
        self.assertFalse(proc.scan_for_embedded_04_8d(bytes(bad)))

    def test_player_spawn_name(self):
        store, proc = new()
        rec = b"\x45\x36" + varint(5123) + u32(0x01020304) + b"\x07" + bytes([5]) + b"Corin" + b"\x00" * 8
        proc.consume_stream(packet(rec))
        self.assertEqual(store.nicknames.get(5123), "Corin")


class Damage(unittest.TestCase):
    def test_direct_hit(self):
        store, proc = new()
        store.now = 1000
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 12345, crit=True, back=True)))
        enc = store.current
        self.assertIsNotNone(enc)
        a = enc.targets[9001].actors[5123]
        self.assertEqual(a.total, 12345)
        (code, dot), s = next(iter(a.skills.items()))
        self.assertEqual(code, 11020000, "variant folds into the base skill of the same name")
        self.assertEqual((s.hits, s.crit, s.back), (1, 1, 1))
        self.assertIn(5123, store.known_players)
        self.assertEqual(store.power_scalars[5123], {16000})

    def test_inside_bundle(self):
        store, proc = new()
        inner = packet(damage_record(9001, 5123, 11020010, 777)) + packet(damage_record(9001, 5123, 11030010, 223))
        proc.consume_stream(bundle(inner))
        self.assertEqual(proc.stats["bundles"], 1)
        self.assertEqual(store.current.targets[9001].total, 1000)

    def test_player_on_player_is_not_damage(self):
        store, proc = new()
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 100)))
        proc.consume_stream(packet(damage_record(6000, 6001, 12010010, 100)))  # makes 6001 a player
        proc.consume_stream(packet(damage_record(6001, 5123, 17010010, 5000)))  # heal on a player
        self.assertNotIn(6001, store.current.targets)

    def test_npc_skills_are_ignored(self):
        store, proc = new()
        proc.consume_stream(packet(damage_record(5123, 9001, 2100001, 999)))
        self.assertIsNone(store.current)

    def test_dot_tick(self):
        store, proc = new()
        dot_skill = 11410000
        rec = (b"\x05\x38" + varint(9001) + b"\x02" + varint(5123) + varint(0)
               + u32(dot_skill * 100) + varint(4321))
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 100)))
        proc.consume_stream(packet(rec))
        skills = store.current.targets[9001].actors[5123].skills
        self.assertEqual(skills[(dot_skill, True)].total, 4321)

    def test_summon_folds_into_owner(self):
        store, proc = new()
        store.append_nickname_authoritative(5123, "Corin")
        store.register_confirmed_summon(7777, 5123)
        proc.consume_stream(packet(damage_record(9001, 5123, 16010010, 1000)))
        proc.consume_stream(packet(damage_record(9001, 7777, 16020010, 500)))
        view = build_view(store.view(store.current))
        rows = visible_rows(view, "party")
        self.assertEqual([(r["name"], r["total"]) for r in rows], [("Corin", 1500)])

    def test_encounter_split_on_idle(self):
        store, proc = new()
        store.now = 0
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 100)))
        store.now = 5_000
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 100)))
        store.now = 40_000
        proc.consume_stream(packet(damage_record(9002, 5123, 11020010, 300)))
        self.assertEqual(len(store.history), 1)
        old = build_view(store.history[0].frozen)
        self.assertEqual(old["duration_ms"], 5_000)
        self.assertEqual(sum(r["total"] for r in old["rows"].values()), 200)

    def test_without_a_party_each_player_is_timed_on_their_own(self):
        """You stop after 10 s; the stranger on the next dummy goes on to 30 s."""
        store, proc = new()
        store.append_nickname_authoritative(5123, "Corin")
        store.append_nickname_authoritative(6000, "Necs")
        for t in range(0, 31, 2):
            store.now = t * 1000
            if t <= 10:
                proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 1000)))
            proc.consume_stream(packet(damage_record(9002, 6000, 12010010, 1000)))
        rows = build_view(store.view(store.current))["rows"]
        self.assertAlmostEqual(rows["Corin"]["dps"], 6000 / 10)   # 6 hits over his own 10 s
        self.assertAlmostEqual(rows["Necs"]["dps"], 16000 / 30)
        self.assertAlmostEqual(rows["Corin"]["dps_fight"], 6000 / 30)

    def test_in_a_party_everyone_shares_the_fight_time(self):
        store, proc = new()
        store.append_nickname_authoritative(5123, "Corin")
        store.append_nickname_authoritative(6000, "Necs")
        store.set_party_roster([("Corin", {"job": "GL"}), ("Necs", {"job": "TE"})], True, 0)
        for t in range(0, 31, 2):
            store.now = t * 1000
            if t <= 10:
                proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 1000)))
            proc.consume_stream(packet(damage_record(9001, 6000, 12010010, 1000)))
        rows = build_view(store.view(store.current))["rows"]
        self.assertAlmostEqual(rows["Corin"]["dps"], 6000 / 30)
        self.assertAlmostEqual(rows["Corin"]["dps_own"], 6000 / 10)

    def test_dot_ticks_after_the_last_hit_on_a_dummy_count(self):
        """As in the game's Combat Analysis: trailing ticks add damage and run the clock on."""
        store, proc = new()
        store.append_mob(9001, 2300229)  # a Training Scarecrow
        store.append_nickname_authoritative(5123, "Corin")
        dot = 11410000
        store.now = 0
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 1000)))
        store.now = 10_000
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 1000)))
        for t in (12_000, 14_000, 16_000):
            store.now = t
            proc.consume_stream(packet(b"\x05\x38" + varint(9001) + b"\x02" + varint(5123) + varint(0)
                                       + u32(dot * 100) + varint(200)))
        row = build_view(store.view(store.current))["rows"]["Corin"]
        self.assertEqual(row["total"], 2600)
        self.assertEqual(row["active_ms"], 16_000)

    def test_a_boss_missing_from_the_npc_table_still_splits_and_ends_fights(self):
        """Found by HP: the zone's mobs are ~30K, this one 5M. Its HP reaching 0 ends the fight at once."""
        store, proc = new()
        store.append_nickname_authoritative(5123, "Corin")
        for i in range(10):  # the zone's ordinary mobs
            store.append_mob(7000 + i, 2999990 + i)
            store.append_mob_hp(7000 + i, 30_000 + i * 1000)
        store.append_mob(9001, 2999999)  # unknown to the table
        store.append_mob_hp(9001, 5_000_000)
        self.assertTrue(store.is_boss(9001))
        store.now = 0
        proc.consume_stream(packet(damage_record(7000, 5123, 11020010, 500)))   # trash
        store.now = 2000
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 4000)))  # the pull
        self.assertEqual(len(store.history), 1, "trash before the pull is its own fight")
        store.now = 3000
        hp_zero = b"\x8d" + varint(9001) + b"\x02\x01\x00" + u32(0) + b"\x00\x00\x00\x00"
        proc.consume_stream(packet(b"\x1e\x05" + hp_zero))
        self.assertIsNone(store.current)
        self.assertEqual(store.history[-1].end_reason, "kill")
        store.now = 4000  # a late DoT on the dead boss does not open a new fight
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 100)))
        self.assertIsNone(store.current)

    def test_elites_are_not_bosses(self):
        store, _ = new()
        for i in range(10):
            store.append_mob(7000 + i, 2999990 + i)
            store.append_mob_hp(7000 + i, 36_000)
        store.append_mob(7100, 2999980)
        store.append_mob_hp(7100, 435_000)  # 12x: an elite, like Eroded Kalgolem
        self.assertFalse(store.is_boss(7100))

    def test_pause_stops_counting_but_keeps_learning_names(self):
        store, proc = new()
        store.now = 0
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 100)))
        store.set_paused(True)
        self.assertEqual(len(store.history), 1, "the running fight is closed and frozen")
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 999)))
        rec = b"\x45\x36" + varint(5124) + u32(0x01020304) + b"\x07" + bytes([4]) + b"Necs" + b"\x00" * 8
        proc.consume_stream(packet(rec))
        self.assertIsNone(store.current)
        self.assertEqual(store.nicknames.get(5124), "Necs")
        store.set_paused(False)
        store.now = 1000
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 300)))
        self.assertEqual(store.current.targets[9001].total, 300)

    def test_dps_and_skill_rows(self):
        store, proc = new()
        store.append_nickname_authoritative(5123, "Corin")
        for i, dmg in enumerate((1000, 3000, 2000)):
            store.now = i * 1000
            proc.consume_stream(packet(damage_record(9001, 5123, 11020010, dmg, crit=(i == 1))))
        view = build_view(store.view(store.current))
        row = view["rows"]["Corin"]
        self.assertEqual(row["total"], 6000)
        self.assertAlmostEqual(row["dps"], 3000.0)  # 6000 over 2 s
        sk = skill_rows(row, GD, view["seconds"])[0]
        self.assertEqual((sk["name"], sk["hits"], sk["max"], sk["min"]), ("Keen Strike", 3, 3000, 1000))
        self.assertAlmostEqual(sk["crit"], 100 / 3)


class Identity(unittest.TestCase):
    def dummy_scene(self, store, proc):
        """You (6047, Assassin) and a stranger (12939, Gladiator) on two training dummies."""
        for i in range(20):
            store.now = i * 500
            proc.consume_stream(packet(damage_record(9001, 6047, 13010010, 300)))
            proc.consume_stream(packet(damage_record(9002, 12939, 11020010, 900)))
            proc.consume_stream(packet(self.marker(6047)))
            # a nearby Spiritmaster's spirit gets `06 38` records too: they must not decide
            proc.consume_stream(packet(b"\x06\x38" + varint(20684) + b"\x00\x00"))
            proc.consume_stream(packet(b"\x06\x38" + varint(20684) + b"\x00\x00"))

    @staticmethod
    def marker(eid):
        """Local-player HP-feed record (`8D <id> 01 01 01 ...`)."""
        return b"\x1e\x05" + b"\x8d" + varint(eid) + b"\x01\x01\x01" + u32(3194) + b"\x00\x00\x00\x00"

    def test_hp_marker_tells_you_apart_from_a_stranger(self):
        store, proc = new()
        self.dummy_scene(store, proc)
        self.assertEqual(store.local_identity()[0], 6047)
        self.assertTrue(store.local_is_guess())
        view = build_view(store.view(store.current))
        rows = visible_rows(view, "party")
        # not in a party: everyone fighting is shown, you are marked
        self.assertEqual(sorted(r["key"] for r in rows), ["#12939", "#6047"])
        self.assertEqual([r["key"] for r in rows if r["is_local"]], ["#6047"])

    def test_last_characters_name_is_used_when_the_class_matches(self):
        store, proc = new()
        store.saved_profile = {"name": "Velkara", "job": "AS"}
        self.dummy_scene(store, proc)
        self.assertEqual(store.local_identity(), (6047, "Velkara"))
        rows = visible_rows(build_view(store.view(store.current)), "me")
        self.assertEqual(rows[0]["name"], "Velkara")

    def test_a_classless_spirit_in_scope_records_is_not_you(self):
        store, proc = new()
        for _ in range(50):
            proc.consume_stream(packet(b"\x06\x38" + varint(20684) + b"\x00\x00"))
        proc.consume_stream(packet(damage_record(9001, 20684, 100024, 100)))  # Water Spirit: Basic Attack
        self.assertEqual(store.local_identity(), (None, None))

    def test_scope_records_find_you_when_no_hp_marker_comes(self):
        """Full HP and MP: the HP feed is silent. The classed player in `06 38` is you."""
        store, proc = new()
        for _ in range(12):
            proc.consume_stream(packet(b"\x06\x38" + varint(6047) + b"\x00\x00"))
        proc.consume_stream(packet(damage_record(9001, 6047, 13010010, 300)))
        self.assertEqual(store.local_identity()[0], 6047)

    def test_a_pet_is_never_you(self):
        store, proc = new()
        store.register_confirmed_summon(7777, 5000)
        for _ in range(10):
            proc.consume_stream(packet(self.marker(7777)))
        self.assertEqual(store.local_identity(), (None, None))

    def test_zone_load_forgets_old_ids(self):
        store, proc = new()
        self.dummy_scene(store, proc)
        proc.consume_stream(packet(b"\x23\x36\x00\x01\x02"))
        self.assertEqual(store.local_identity(), (None, None))


class PartyNames(unittest.TestCase):
    DBID = (0x0901 << 48) | 0x02EB0E

    def roster(self):
        # `02 97`: party_key, party name, size, dungeon, pads, leader, pads, count, member...
        member = (b"\x01\x01" + self.DBID.to_bytes(8, "little") + bytes([6]) + b"Tharos"
                  + u32(7) + u32(45) + u32(1492) + (0x0901).to_bytes(2, "little") + b"\x00\x00\x00"
                  + (69719).to_bytes(8, "little") + b"\x00\x00\x00")
        body = (b"\x02\x97" + u32(1) + bytes([4]) + b"Raid" + bytes([5]) + u32(600091) + b"\x00" * 13
                + varint(1) + member + b"\x00" * 16)
        return body

    def test_map_marker_names_the_entity(self):
        store, proc = new()
        proc.consume_stream(packet(self.roster()))
        self.assertIn("Tharos", store.roster)
        for i in range(6):
            xy = struct_xy(38218.7 + i * 50, 58094.7 - i * 30)
            proc.consume_stream(packet(b"\x1a\x37" + varint(1299) + b"\x00\x00" + xy + u32(0)))
            proc.consume_stream(packet(b"\x1c\x92" + self.DBID.to_bytes(8, "little") + bytes(16) + xy + u32(0)))
        self.assertEqual(store.nicknames.get(1299), "Tharos")

    def test_members_on_the_same_spot_do_not_bind_and_spawn_names_stand(self):
        """At an instance entrance the whole party stands on one point."""
        store, proc = new()
        other = (0x0901 << 48) | 0x0BBB
        store.dbid_names.update({self.DBID: "Tharos", other: "Mirae"})
        store.append_nickname_authoritative(593, "Mirae")  # the game named 593 itself
        for i in range(8):
            xy = struct_xy(500.0 + i, 500.0 + i)
            for dbid in (self.DBID, other):  # both markers on the same coordinates
                proc.consume_stream(packet(b"\x1c\x92" + dbid.to_bytes(8, "little") + bytes(16) + xy + u32(0)))
            proc.consume_stream(packet(b"\x1a\x37" + varint(593) + b"\x00\x00" + xy + u32(0)))
        self.assertEqual(store.nicknames.get(593), "Mirae")
        self.assertNotEqual(store.dbid_entity.get(self.DBID), 593)

    def test_party_without_roster_is_named_from_the_account_book(self):
        """Joined before the meter started: no roster, no spawn. Map markers + the book name them."""
        store, proc = new()
        store.dbid_names[self.DBID] = "Mustilicious"
        for i in range(6):
            xy = struct_xy(1200.5 + i * 10, -800.25 + i * 7)
            proc.consume_stream(packet(b"\x1a\x37" + varint(10430) + b"\x00\x00" + xy + u32(0)))
            proc.consume_stream(packet(b"\x1c\x92" + self.DBID.to_bytes(8, "little") + bytes(16) + xy + u32(0)))
        proc.consume_stream(packet(damage_record(9001, 10430, 13010010, 500)))
        proc.consume_stream(packet(damage_record(9002, 12939, 11020010, 900)))  # a stranger
        rows = visible_rows(build_view(store.view(store.current)), "party")
        self.assertEqual([r["name"] for r in rows], ["Mustilicious"])

    def test_spawn_dbid_goes_into_the_account_book(self):
        store, proc = new()
        spawn = (b"\x45\x36" + varint(10430) + u32(0x01A0301D) + b"\x07" + bytes([12]) + b"Mustilicious"
                 + bytes(40) + b"\x01" + self.DBID.to_bytes(8, "little") + b"\x04\xcd\x00" + bytes(8))
        proc.consume_stream(packet(spawn))
        self.assertEqual(store.dbid_names.get(self.DBID), "Mustilicious")
        self.assertEqual(store.dbid_entity.get(self.DBID), 10430)

    def test_name_cache_is_used_only_in_the_same_zone_instance(self):
        import json
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "names.json")
        import time as _t
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"local_id": 6047, "saved": _t.time(), "names": {"11188": "Ruhm3"}}, f)
        for my_id, expected in ((6047, "Ruhm3"), (9999, None)):
            store = _Store(GD, profile_path=None, names_path=path)
            proc = StreamProcessor(store, GD)
            for _ in range(3):
                proc.consume_stream(packet(Identity.marker(my_id)))
            proc.consume_stream(packet(damage_record(9001, my_id, 13010010, 100)))
            store.tick()
            self.assertEqual(store.nicknames.get(11188), expected)


def struct_xy(x, y):
    import struct
    return struct.pack("<ff", x, y)


class Reassembly(unittest.TestCase):
    def test_retransmission_dropped(self):
        r = Reassembler()
        self.assertEqual(r.push(100, b"abcd", 0), [b"abcd"])
        self.assertEqual(r.push(100, b"abcd", 1), [])
        self.assertEqual(r.push(102, b"cdef", 2), [b"ef"])

    def test_out_of_order(self):
        r = Reassembler()
        r.push(0, b"aa", 0)
        self.assertEqual(r.push(4, b"cc", 1), [])
        self.assertEqual(r.push(2, b"bb", 2), [b"bb", b"cc"])

    def test_wraparound(self):
        r = Reassembler()
        r.push(0xFFFFFFFE, b"ab", 0)
        self.assertEqual(r.push(0, b"cd", 1), [b"cd"])

    def test_gap_is_skipped_eventually(self):
        r = Reassembler()
        r.push(0, b"aa", 0)
        r.push(10, b"zz", 1)
        out = r.push(12, b"yy", 1000)
        self.assertIs(out[0], Reassembler.RESET)
        self.assertEqual(out[1:], [b"zz", b"yy"])


def application(name, char, server=1307, cls=9, level=45, cp=73701, party=80593):
    """`07 97`: a request to join your listed party, laid out as the game sends it."""
    dbid = (server << 48) | char
    nm = name.encode()
    return packet(b"\x07\x97" + varint(party) + b"\x00" + dbid.to_bytes(8, "little") + u32(cls) + u32(level)
                  + u32(1446) + bytes([len(nm)]) + nm + server.to_bytes(2, "little") + b"\x00" * 4
                  + cp.to_bytes(8, "little") + b"\x01" + (1_791_414_721_371).to_bytes(8, "little"))


def answered(char, server=1307):
    return packet(b"\x16\x97" + ((server << 48) | char).to_bytes(8, "little") + b"\x01")


class PartyFinder(unittest.TestCase):
    def test_every_request_is_listed_first_come_first(self):
        store, proc = new()
        store.now = 1000
        proc.consume_stream(application("Varnis", 1001))
        store.now = 2000
        proc.consume_stream(application("Kelda", 1002, cls=0x1a, cp=81000))
        got = store.pending_applicants()
        self.assertEqual([(a["name"], a["job"], a["level"], a["combat_power"], a["server_id"]) for a in got],
                         [("Varnis", "TE", 45, 73701, 1307), ("Kelda", "SO", 45, 81000, 1307)])
        self.assertEqual([a["gear_score"] for a in got], [1446, 1446])
        store.now = 5000
        self.assertEqual([a["waited_ms"] for a in store.pending_applicants()], [4000, 3000])

    def test_an_answered_request_leaves_and_a_new_one_goes_to_the_back(self):
        store, proc = new()
        for i, name in enumerate(("Varnis", "Kelda", "Orrin")):
            proc.consume_stream(application(name, 1001 + i))
        proc.consume_stream(answered(1001))
        proc.consume_stream(application("Kelda", 1002))  # asked again
        self.assertEqual([a["name"] for a in store.pending_applicants()], ["Orrin", "Kelda"])
        proc.consume_stream(answered(1002, server=1302))  # someone else's id: nothing changes
        self.assertEqual(len(store.pending_applicants()), 2)

    def test_an_old_request_goes_by_itself(self):
        store, proc = new()
        store.now = 0
        proc.consume_stream(application("Varnis", 1001))
        store.now = 11 * 60_000
        self.assertEqual(store.pending_applicants(), [])


class Varint(unittest.TestCase):
    def test_roundtrip(self):
        for v in (0, 1, 127, 128, 300, 16384, 2 ** 28 - 1, 99_999_999):
            self.assertEqual(read_varint(varint(v), 0), (v, len(varint(v))))


if __name__ == "__main__":
    unittest.main()
