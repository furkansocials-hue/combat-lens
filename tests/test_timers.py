"""Field boss timers, the boss table they use, one fight per boss, and clearing the panel after a fight."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import struct  # noqa: E402

from aion2meter.api import overlay_state  # noqa: E402
from aion2meter.timers import DATA_PATH, BossTimers  # noqa: E402
from test_app import _App  # noqa: E402
from test_protocol import GD, damage_record, new, packet, u32, varint  # noqa: E402

KERNON, LAGTA_ELYOS, LAGTA_ASMO, GARTUA = 2100050, 2101131, 2400853, 2101074
NOW = 1_791_411_164_000  # 2026-10-08, the packets carry real epoch times
VERTERON = 1010


def boss_list(world, entries):
    """The game's field boss list: (n, up, ms[, extra byte]) per boss, as the server sends it."""
    body = bytearray(b"\x01\x91\x00\x00" + u32(world) + bytes([len(entries)]))
    for n, up, ms, *extra in entries:
        body += bytes([1 if up else 0]) + varint(world * 100 + n)
        if up:
            body += struct.pack("<fff", -57517.0, -85173.0, 10150.0) + bytes(extra)
        body += ms.to_bytes(8, "little")
    return packet(bytes(body + b"\x00\x00"))


def verteron(**changes):
    """All 24 Verteron bosses down for an hour, with `n=(up, ms)` changes."""
    rows = []
    for n in range(1, 25):
        up, ms = changes.get(f"n{n}", (False, NOW + 3600_000))
        rows.append((n, up, ms, 221) if up and n % 2 else (n, up, ms))
    return rows


class TimersTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="combatlens_timers_")
        self.path = os.path.join(self.dir, "kills.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_table_is_the_game_s_field_bosses(self):
        data = json.load(open(DATA_PATH, encoding="utf-8"))
        self.assertEqual(len(data["bosses"]), 48)
        for b in data["bosses"]:
            self.assertTrue(GD.is_boss(b["code"]), b["name"])
            self.assertEqual(GD.npc_name(b["code"]), b["name"])
            self.assertGreater(b["respawn_min"], 0)
        self.assertEqual(sum(b["faction"] == "Elyos" for b in data["bosses"]), 24)

    def test_a_kill_starts_that_boss_s_own_cycle(self):
        t = BossTimers(kills_path=self.path)
        t.note_kill(LAGTA_ELYOS, 1_000_000)
        t.note_kill(LAGTA_ASMO, 1_000_000)
        rows = {b["code"]: b for b in t.state()["bosses"]}
        self.assertEqual(rows[LAGTA_ELYOS]["due"], 1_000_000 + 12 * 3600_000)   # same name, Verteron
        self.assertEqual(rows[LAGTA_ASMO]["due"], 1_000_000 + 12 * 3600_000)    # Altgard
        self.assertIsNone(rows[KERNON]["due"])
        self.assertFalse(t.note_kill(1234567, 1))  # not a field boss
        back = {b["code"]: b for b in BossTimers(kills_path=self.path).state()["bosses"]}
        self.assertEqual(back[LAGTA_ELYOS]["killed"], 1_000_000)

    def test_cycle_set_by_hand_and_back_to_the_table(self):
        t = BossTimers(kills_path=self.path)
        t.set_cycle(KERNON, 45)
        t.note_kill(KERNON, 0)
        row = next(b for b in t.state()["bosses"] if b["code"] == KERNON)
        self.assertEqual((row["cycle_min"], row["custom"], row["due"]), (45, True, 45 * 60_000))
        t.set_cycle(KERNON, 30)  # the table's own value
        row = next(b for b in BossTimers(kills_path=self.path).state()["bosses"] if b["code"] == KERNON)
        self.assertEqual((row["cycle_min"], row["custom"]), (30, False))
        t.clear(KERNON)
        self.assertIsNone(next(b for b in t.state()["bosses"] if b["code"] == KERNON)["killed"])


def _party(store):
    store.append_nickname_authoritative(5123, "Corin")
    store.set_local_identity(5123, "Corin")


class GameListTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="combatlens_timers_")
        self.path = os.path.join(self.dir, "kills.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def lists(self, *rows_list, world=VERTERON, gap=2000):
        """Feed lists through the parser, `gap` ms apart; returns the timers."""
        store, proc = new()
        t = BossTimers(kills_path=self.path)
        store.on_field_bosses = t.note_list
        for i, rows in enumerate(rows_list):
            store.now = NOW + i * gap
            proc.consume_stream(boss_list(world, rows))
        return t

    def test_the_parser_reads_the_list_spawned_bosses_and_all(self):
        store, proc = new()
        got = []
        store.on_field_bosses = lambda world, entries, ms: got.append((world, entries))
        rows = [(1, True, NOW - 7_000_000, 221), (2, True, NOW - 60_000), (3, False, NOW + 40_201_000)]
        proc.consume_stream(boss_list(VERTERON, rows))
        self.assertEqual(got, [(VERTERON, [(1, True, NOW - 7_000_000), (2, True, NOW - 60_000), (3, False, NOW + 40_201_000)])])
        # the same opcode also carries other lists (a dungeon's markers): not field bosses
        proc.consume_stream(packet(bytes.fromhex("01910000082809000001c9f5038b1b2300e342d744e2838dc6007763470000")))
        self.assertEqual(len(got), 1)

    def test_bosses_are_numbered_in_the_order_of_their_npc_codes(self):
        t = self.lists(verteron(n21=(False, NOW + 40_201_000), n19=(True, NOW - 3_000_000), n11=(False, NOW + 3_514_000)))
        rows = {b["name"]: b for b in t.state()["bosses"]}
        self.assertEqual(rows["Eternal Gartua"]["due"], NOW + 40_201_000)   # the game: 11 h 10 min left
        self.assertEqual(rows["Black Tentacle Lawa"]["due"], NOW + 3_514_000)
        self.assertEqual(rows["Chaser Taulo"]["live"]["up"], True)          # the game: spawned
        self.assertIsNone(rows["Chaser Taulo"]["due"])
        self.assertIsNone(rows["Melted Danar"]["live"])                      # Altgard: not in this list
        self.assertEqual(t.state()["live_seen"], {"Elyos": NOW})
        back = {b["name"]: b for b in BossTimers(kills_path=self.path).state()["bosses"]}
        self.assertEqual(back["Eternal Gartua"]["due"], NOW + 40_201_000)   # kept over a restart

    def test_a_boss_gone_between_two_lists_was_killed_and_shows_its_cycle(self):
        up = verteron(n1=(True, NOW - 600_000))
        down = verteron(n1=(False, NOW + 2000 + 30 * 60_000))
        t = self.lists(up, down)
        neikel = next(b for b in t.state()["bosses"] if b["name"] == "Neikel of the East")
        self.assertEqual((neikel["killed"], neikel["due"], neikel["cycle_min"], neikel["learned"]),
                         (NOW + 2000, NOW + 2000 + 30 * 60_000, 30, True))
        os.remove(self.path)
        t = self.lists(up, down, gap=3600_000)  # an hour between the lists: when it died is not known
        neikel = next(b for b in t.state()["bosses"] if b["name"] == "Neikel of the East")
        self.assertEqual((neikel["killed"], neikel["learned"]), (None, False))

    def test_a_kill_seen_after_the_list_wins(self):
        t = self.lists(verteron(n24=(True, NOW - 60_000)))
        t.note_kill(LAGTA_ELYOS, NOW + 10_000)
        lagta = next(b for b in t.state()["bosses"] if b["code"] == LAGTA_ELYOS)
        self.assertEqual((lagta["live"], lagta["due"]), (None, NOW + 10_000 + 12 * 3600_000))

    def test_an_unknown_world_or_a_short_list_is_left_alone(self):
        t = self.lists(verteron(), world=3030)
        self.assertEqual(t.state()["live_seen"], {})
        self.assertEqual(t.unknown_worlds, {(3030, 24)})
        t = self.lists(verteron()[:20])
        self.assertTrue(all(b["live"] is None for b in t.state()["bosses"]))


class BossFightsTest(unittest.TestCase):
    def test_a_field_boss_dying_reaches_the_timers(self):
        store, proc = new()
        _party(store)
        seen = []
        store.on_kill = seen.append
        store.append_mob(9001, KERNON)
        store.now = 0
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 4000)))
        store.set_mob_current_hp(9001, 0)
        self.assertEqual(seen, [KERNON])
        self.assertEqual(store.history[-1].end_reason, "kill")

    def test_the_next_boss_is_a_new_fight(self):
        store, proc = new()
        _party(store)
        store.append_mob(9001, KERNON)
        store.append_mob(9002, GARTUA)
        store.now = 0
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 4000)))
        store.now = 18_000  # boss one left behind, a second boss pulled (within the idle time)
        proc.consume_stream(packet(damage_record(9002, 5123, 11020010, 4000)))
        self.assertEqual(len(store.history), 1)
        self.assertEqual(store.history[0].end_reason, "boss")
        self.assertEqual(list(store.current.targets), [9002])

    def test_two_bosses_fought_together_stay_one_fight(self):
        store, proc = new()
        _party(store)
        store.append_mob(9001, KERNON)
        store.append_mob(9002, GARTUA)
        for t in range(0, 10_000, 1000):
            store.now = t
            proc.consume_stream(packet(damage_record(9001 + (t // 1000) % 2, 5123, 11020010, 4000)))
        self.assertEqual(store.history, [])
        self.assertEqual(sorted(store.current.targets), [9001, 9002])


class ClearAfterTest(unittest.TestCase):
    def test_a_finished_fight_leaves_the_panel_but_not_the_history(self):
        store, proc = new()
        _party(store)
        store.append_mob(9001, KERNON)
        store.now = 0
        proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 4000)))
        store.set_mob_current_hp(9001, 0)  # killed: the fight is over
        app = _App(store, None)
        store.now = 20_000
        self.assertIsNotNone(overlay_state(app, "all", "party", None, 30)["view"])
        store.now = 31_000
        s = overlay_state(app, "all", "party", None, 30)
        self.assertIsNone(s["view"])
        self.assertEqual((s["nav"]["index"], s["nav"]["newest_cleared"]), (-1, True))
        fid = s["nav"]["ids"][0]
        self.assertEqual(overlay_state(app, "all", "party", fid, 30)["view"]["id"], fid)  # ‹ brings it back
        self.assertIsNotNone(overlay_state(app, "all", "party", None, 0)["view"])        # setting off


if __name__ == "__main__":
    unittest.main()
