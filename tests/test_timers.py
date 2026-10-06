"""Field boss timers, the boss table they use, one fight per boss, and clearing the panel after a fight."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aion2meter.api import overlay_state  # noqa: E402
from aion2meter.timers import DATA_PATH, BossTimers  # noqa: E402
from test_app import _App  # noqa: E402
from test_protocol import GD, damage_record, new, packet  # noqa: E402

KERNON, LAGTA_ELYOS, LAGTA_ASMO, GARTUA = 2100050, 2101131, 2400853, 2101074


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
        self.assertEqual(rows[LAGTA_ELYOS]["due"], 1_000_000 + 6 * 3600_000)    # same name, Verteron
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
