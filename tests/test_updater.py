"""Self-update: which file is picked, how the restart is started, download and checksum."""
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aion2meter import __version__, updater  # noqa: E402


def release(version, names):
    return {"version": version, "page": "https://example.invalid/r",
            "assets": {n: {"url": f"https://github.com/x/{n}", "size": 1, "digest": None} for n in names}}


class PickTest(unittest.TestCase):
    def test_newer_only(self):
        self.assertTrue(updater.is_newer(release("99.0.0", [])))
        self.assertFalse(updater.is_newer(release(__version__, [])))
        self.assertFalse(updater.is_newer(None))

    def test_the_build_kind_picks_its_file(self):
        info = release("9.9.9", ["CombatLens.exe", "CombatLens-9.9.9.zip"])
        self.assertTrue(updater.pick_asset(info, "onefile")["url"].endswith("CombatLens.exe"))
        self.assertTrue(updater.pick_asset(info, "onedir")["url"].endswith(".zip"))
        self.assertIsNone(updater.pick_asset(info, "source"))
        self.assertIsNone(updater.pick_asset(release("9.9.9", ["CombatLens.exe"]), "onedir"))

    def test_restart_keeps_the_options_but_not_the_update_ones(self):
        with mock.patch.object(sys, "argv", ["x", "--demo", "--wait-pid", "12", "--updated", "--install-update", "C:\\a", "--tab", "me"]):
            self.assertEqual(updater.relaunch_args(), ["--demo", "--tab", "me"])


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="combatlens_upd_")
        self.payload = os.path.join(self.dir, "CombatLens.exe")
        with open(self.payload, "wb") as f:
            f.write(os.urandom(300_000))
        self.sha = hashlib.sha256(open(self.payload, "rb").read()).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def feed(self, digest):
        path = os.path.join(self.dir, "feed.json")
        json.dump({"tag_name": "v9.9.9", "html_url": "https://example.invalid/r", "assets": [
            {"name": "CombatLens.exe", "browser_download_url": pathlib.Path(self.payload).as_uri(),
             "size": os.path.getsize(self.payload), "digest": digest}]}, open(path, "w"))
        return path

    def run_update(self, digest):
        with mock.patch.dict(os.environ, {"COMBATLENS_UPDATE_FEED": self.feed(digest)}), \
                mock.patch.object(updater, "install_kind", return_value="onefile"), \
                mock.patch.object(updater, "STAGING", os.path.join(self.dir, "staging")), \
                mock.patch.object(updater.Updater, "_swap_exe") as swap:
            info = updater.latest_release()
            self.assertEqual(info["version"], "9.9.9")
            done = []
            u = updater.Updater(log=lambda m: None)
            u.start(info, on_ready=lambda: done.append(True))
            for _ in range(100):
                if not u.busy():
                    break
                time.sleep(0.05)
            return u.state, swap, done

    def test_a_good_download_is_installed_and_the_app_restarts(self):
        state, swap, done = self.run_update("sha256:" + self.sha)
        self.assertEqual(state["stage"], "restart")
        self.assertEqual(state["pct"], 100)
        swap.assert_called_once()
        self.assertEqual(done, [True])

    def test_a_file_that_does_not_match_its_checksum_is_refused(self):
        state, swap, done = self.run_update("sha256:" + "0" * 64)
        self.assertEqual(state["stage"], "error")
        swap.assert_not_called()
        self.assertEqual(done, [])


if __name__ == "__main__":
    unittest.main()
