"""User settings, kept as JSON in the user dir."""
import json
import os
import threading

from .paths import user_path

PATH = user_path("ayarlar.json")

DEFAULTS = {
    "lang": "tr",            # UI language: tr / en
    "opacity": 0.92,         # overlay window opacity
    "mode": "all",           # all targets / main target
    "tab": "party",          # party / me
    "overlay": {"x": None, "y": None, "w": 380, "h": 300},
    "analysis": {"w": 1180, "h": 760},
    "folded": False,
    "check_updates": True,
    "skipped_version": "",
    "hotkeys": {
        "reset": "Ctrl+Shift+R",
        "pause": "Ctrl+Shift+P",
        "fold": "Ctrl+Shift+M",
        "hide": "Ctrl+Shift+H",
        "clickthrough": "Ctrl+Shift+T",
        "analysis": "Ctrl+Shift+D",
    },
    "welcomed": False,
    "keep_fight": 300,       # seconds a finished fight stays on the panel (0: until the next one)
    "faction": "",           # Elyos / Asmodian: which field bosses the timers list shows
    "region": "eu",          # server region: the Spacetime Rift runs on its clock
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            out[k] = _merge(base[k], v)
        elif k in base:
            out[k] = v
    return out


class Settings:
    def __init__(self, path=PATH):
        self.path = path
        self.lock = threading.Lock()
        try:
            with open(path, encoding="utf-8") as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError):
            self.data = _merge(DEFAULTS, {})

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def update(self, values):
        """Apply known keys only (nested dicts merged), then save."""
        with self.lock:
            self.data = _merge(self.data, values)
            self._save()
        return self.data

    def _save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass
