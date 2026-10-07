"""The app around the parser: saved fights, the UI's JSON, its local server, settings, hotkeys."""
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aion2meter.api import encounter_detail, history_list, overlay_state  # noqa: E402
from aion2meter.history import History  # noqa: E402
from aion2meter.report import build_view, skill_rows  # noqa: E402
from aion2meter.server import UIServer  # noqa: E402
from aion2meter.settings import Settings  # noqa: E402
from aion2meter.updater import version_tuple as _version_tuple  # noqa: E402
from aion2meter.winutil import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey  # noqa: E402
from test_protocol import GD, damage_record, new, packet  # noqa: E402


def fight(store, proc, t0=0, seconds=10, target=9001):
    """Corin (you, Gladiator) and Necs (Templar) in a party, hitting one target."""
    store.append_nickname_authoritative(5123, "Corin")
    store.append_nickname_authoritative(6000, "Necs")
    store.set_local_identity(5123, "Corin")
    store.set_party_roster([("Corin", {"job": "GL"}), ("Necs", {"job": "TE"})], True, 0)
    for t in range(0, seconds + 1, 2):
        store.now = t0 + t * 1000
        proc.consume_stream(packet(damage_record(target, 5123, 11020010, 3000)))
        proc.consume_stream(packet(damage_record(target, 6000, 12010010, 1000)))


class _Dispatcher:
    def status(self):
        return {"locked": True, "dropped": 0, "silent_ms": 0}


class _App:
    def __init__(self, store, history):
        self.store, self.history, self.gd = store, history, GD
        self.dispatcher = _Dispatcher()
        self.npcap_ok, self.update_info, self.clickthrough = True, None, False

    def api_get(self, route, q):
        return {"route": route, "q": q}

    def api_post(self, route, body):
        return {"got": body}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="combatlens_test_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class HistoryTest(TempDirCase):
    def test_a_saved_fight_reads_back_the_same(self):
        store, proc = new()
        fight(store, proc)
        store.reset()
        resolved = store.history[0].frozen
        h = History(self.dir)
        h.add(resolved, "Dummy")
        back = History(self.dir).load(resolved["id"])
        a, b = build_view(resolved), build_view(back)
        self.assertEqual({k: r["total"] for k, r in a["rows"].items()}, {k: r["total"] for k, r in b["rows"].items()})
        self.assertEqual(a["duration_ms"], b["duration_ms"])
        sa = skill_rows(a["rows"]["Corin"], GD, a["seconds"])
        sb = skill_rows(b["rows"]["Corin"], GD, b["seconds"])
        self.assertEqual([(s["code"], s["hits"], s["total"]) for s in sa], [(s["code"], s["hits"], s["total"]) for s in sb])
        self.assertEqual(a["rows"]["Corin"]["buckets"], b["rows"]["Corin"]["buckets"])
        entry = h.entries()[0]
        self.assertEqual(entry["title"], "Dummy")
        self.assertEqual(entry["total"], 6 * 3000 + 6 * 1000)

    def test_favourites_and_delete(self):
        store, proc = new()
        fight(store, proc)
        store.reset()
        resolved = store.history[0].frozen
        h = History(self.dir)
        h.add(resolved, "Dummy")
        h.set_favorite(resolved["id"], True)
        self.assertTrue(History(self.dir).entries()[0]["favorite"])
        h.delete(resolved["id"])
        self.assertEqual(History(self.dir).entries(), [])
        self.assertIsNone(h.load(resolved["id"]))

    def test_a_short_skirmish_is_not_saved(self):
        store, proc = new()
        fight(store, proc, seconds=2)
        store.reset()
        h = History(self.dir)
        h.add(store.history[0].frozen, "x")
        self.assertEqual(h.entries(), [])


class ApiTest(TempDirCase):
    def test_overlay_rows_and_the_me_tab(self):
        store, proc = new()
        fight(store, proc)
        app = _App(store, History(self.dir))
        s = overlay_state(app, "all", "party", None)
        rows = s["view"]["rows"]
        self.assertEqual([r["name"] for r in rows], ["Corin", "Necs"])
        self.assertAlmostEqual(rows[0]["pct"], 75.0)
        self.assertEqual(s["view"]["total"], 24000)
        self.assertTrue(s["view"]["live"])
        me = overlay_state(app, "all", "me", None)["view"]["rows"]
        self.assertEqual([r["name"] for r in me], ["Corin"])
        self.assertAlmostEqual(me[0]["pct"], 75.0)  # still the share of the party

    def test_reset_empties_the_panel_but_keeps_the_fight_saved(self):
        store, proc = new()
        h = History(self.dir)
        store.on_end = lambda enc: h.add(enc.frozen, build_view(enc.frozen)["title"])
        fight(store, proc)
        app = _App(store, h)
        self.assertIsNotNone(overlay_state(app, "all", "party", None)["view"])
        store.clear_history()  # what the reset button and hotkey do
        s = overlay_state(app, "all", "party", None)
        self.assertIsNone(s["view"])
        self.assertIsNone(s["nav"])
        self.assertEqual(len(h.entries()), 1)

    def test_detail_has_skills_timeline_and_icons(self):
        store, proc = new()
        fight(store, proc)
        app = _App(store, History(self.dir))
        d = encounter_detail(app, store.current.id, "all")
        corin = d["players"][0]
        self.assertEqual(corin["name"], "Corin")
        self.assertEqual(corin["timeline"][0][0], 0)
        self.assertEqual(sum(v for _, v in corin["timeline"]), 18000)
        self.assertTrue(all(isinstance(sk["icon"], str) for sk in corin["skills"]))
        json.dumps(d)  # everything the page gets is plain JSON

    def test_history_lists_live_saved_and_unsaved_fights_once(self):
        store, proc = new()
        h = History(self.dir)
        store.on_end = lambda enc: h.add(enc.frozen, build_view(enc.frozen)["title"])
        fight(store, proc, t0=0)                 # 10 s: saved on disk
        store.reset()
        fight(store, proc, t0=60_000, seconds=2)  # 2 s: kept in memory only
        store.reset()
        fight(store, proc, t0=120_000)           # still running
        app = _App(store, h)
        items = history_list(app)
        self.assertEqual(len(items), 3)
        self.assertEqual(len({i["id"] for i in items}), 3)
        self.assertTrue(items[0]["live"])
        self.assertEqual([i["start"] for i in items], sorted((i["start"] for i in items), reverse=True))


class HealerTest(TempDirCase):
    def test_clerics_and_chanters_show_their_own_class_heals(self):
        store, proc = new()
        for eid, name in ((5123, "Corin"), (6000, "Mirae"), (6100, "Velka")):
            store.append_nickname_authoritative(eid, name)
        store.set_local_identity(5123, "Corin")
        store.set_party_roster([("Corin", {"job": "GL"}), ("Mirae", {"job": "CL"}), ("Velka", {"job": "CL"})], True, 0)
        for t in range(0, 11, 2):
            store.now = t * 1000
            proc.consume_stream(packet(damage_record(9001, 5123, 11020010, 3000)))
            proc.consume_stream(packet(damage_record(9001, 6000, 17010010, 1000)))
            store.append_heal(6000, 17080010, 2000)   # a Cleric heal
            store.append_heal(6000, 1000010, 500)     # a potion: not a class skill
            store.append_heal(5123, 1000010, 800)     # the Gladiator's potion
            store.append_heal(6100, 17080010, 1500)   # a Cleric who only heals
        rows = {r["name"]: r for r in overlay_state(_App(store, History(self.dir)), "all", "party", None)["view"]["rows"]}
        self.assertEqual(rows["Mirae"]["heal"], 6 * 2000)
        self.assertAlmostEqual(rows["Mirae"]["hps"], 6 * 2000 / 10)
        self.assertEqual(rows["Corin"]["heal"], 0)
        self.assertIn("Velka", rows)  # never hit anything, still on the list
        self.assertEqual((rows["Velka"]["total"], rows["Velka"]["heal"]), (0, 6 * 1500))
        # the analysis window: the healer's heal skills, the potion left out
        mirae = next(p for p in encounter_detail(_App(store, History(self.dir)), store.current.id, "all")["players"]
                     if p["name"] == "Mirae")
        self.assertEqual([(h["hits"], h["total"], h["is_hot"], h["pct"]) for h in mirae["heals"]], [(6, 12000, False, 100.0)])
        self.assertAlmostEqual(mirae["heals"][0]["hps"], 1200)
        self.assertEqual((mirae["heal_total"], mirae["heals"][0]["avg"]), (12000, 2000))


class ServerTest(unittest.TestCase):
    def setUp(self):
        store, _ = new()
        self.srv = UIServer(_App(store, None)).start()
        self.base = f"http://127.0.0.1:{self.srv.port}"

    def tearDown(self):
        self.srv.stop()

    def get(self, path, token=None):
        req = urllib.request.Request(self.base + path, headers={"X-Token": token} if token else {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_api_needs_the_token(self):
        self.assertEqual(self.get("/api/state")[0], 403)
        self.assertEqual(self.get("/api/state", "wrong")[0], 403)
        code, body = self.get("/api/state?mode=all", self.srv.token)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["q"], {"mode": "all"})

    def test_static_files_stay_inside_the_web_folder(self):
        self.assertEqual(self.get("/overlay.html")[0], 200)
        self.assertEqual(self.get("/../aion2meter/store.py")[0], 404)
        self.assertEqual(self.get("/%2e%2e/%2e%2e/README.md")[0], 404)
        self.assertEqual(self.get("/icon/..%5Cx.png")[0], 404)


class SettingsTest(TempDirCase):
    def test_merge_keeps_defaults_and_drops_unknown_keys(self):
        path = os.path.join(self.dir, "s.json")
        s = Settings(path)
        s.update({"lang": "en", "hotkeys": {"reset": "Alt+F5"}, "nonsense": 1})
        back = Settings(path)
        self.assertEqual(back["lang"], "en")
        self.assertEqual(back["hotkeys"]["reset"], "Alt+F5")
        self.assertEqual(back["hotkeys"]["fold"], "Ctrl+Shift+M")
        self.assertNotIn("nonsense", back.data)
        self.assertEqual(back["scale"], 0.9)  # a settings file from before the size setting gets the smaller size


class UserFolderTest(TempDirCase):
    def test_the_folder_of_the_earlier_name_is_taken_over(self):
        from aion2meter import paths
        os.makedirs(os.path.join(self.dir, "DaevaMeter", "gecmis"))
        with open(os.path.join(self.dir, "DaevaMeter", "ayarlar.json"), "w") as f:
            f.write("{}")
        old_env = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self.dir
        try:
            path = paths.user_dir()
        finally:
            os.environ["APPDATA"] = old_env
        self.assertEqual(path, os.path.join(self.dir, paths.APP_ID))
        self.assertTrue(os.path.isfile(os.path.join(path, "ayarlar.json")))
        self.assertTrue(os.path.isdir(os.path.join(path, "gecmis")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "DaevaMeter")))


class SmallTest(unittest.TestCase):
    def test_hotkey_text(self):
        self.assertEqual(parse_hotkey("Ctrl+Shift+R"), (MOD_CONTROL | MOD_SHIFT, ord("R")))
        self.assertEqual(parse_hotkey("alt + f5"), (MOD_ALT, 0x74))
        self.assertIsNone(parse_hotkey("Ctrl+Shift"))
        self.assertIsNone(parse_hotkey("Ctrl+Banana"))

    def test_versions_compare_as_numbers(self):
        self.assertGreater(_version_tuple("v1.2.10"), _version_tuple("1.2.9"))
        self.assertEqual(_version_tuple("1.0.0"), (1, 0, 0))


if __name__ == "__main__":
    unittest.main()
