"""Game data: skill names, NPC names, classes and skill icons.

The tables are AION 2 client data as published by the A2Tools project
(src/data in github.com/taengu/A2Tools-DPS-Meter). `update_data()` refreshes
them from there after a game patch.
"""
import json
import os
import urllib.request

from .paths import resource, user_path

DATA_DIR = resource("data")  # shipped tables (read-only when installed)
UPSTREAM = "https://raw.githubusercontent.com/taengu/A2Tools-DPS-Meter/main/src/data"
ICON_BASE = "https://assets.playnccdn.com/static-aion2-gamedata/resources"
LANGS = ("en", "de", "es", "fr", "ja", "ko", "pt", "ru", "zh-Hans", "zh-Hant")

# Class codes as they appear in skill ids (first two digits) and icon names.
CLASSES = {
    "GL": "Gladiator",
    "TE": "Templar",
    "AS": "Assassin",
    "RA": "Ranger",
    "SO": "Sorcerer",
    "EL": "Spiritmaster",
    "CL": "Cleric",
    "CH": "Chanter",
    "GT": "Brawler",
}
_PREFIX_TO_CLASS = {11: "GL", 12: "TE", 13: "AS", 14: "RA", 15: "SO", 16: "EL", 17: "CL", 18: "CH", 19: "GT"}

TRAINING_DUMMY_CODES = {
    2300229, 2300919, 2310229, 2310919, 2320229, 2320919,
    2400032, 2400035, 2400392, 2500075, 2500076, 2701376,
    2090773, 2702605,
}
_DUMMY_NAMES = ("Training Scarecrow", "Punching Bag")


def job_from_skill(code: int):
    """Strict class detection from a skill code (JobClass::convert_from_skill)."""
    if 100510 <= code <= 103500 or 109300 <= code <= 109362:
        return "EL"
    if 10_000_000 <= code <= 19_999_999:
        prefix = code // 1_000_000
        sub = (code // 10000) % 100
        if sub == 0:
            if prefix == 16 and 11 <= (code // 100) % 100 <= 13:
                return "EL"
            return None
        if prefix == 16:
            pc = sub in (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 17, 19, 21, 22, 23, 24, 25, 26,
                         30, 31, 32, 34, 35, 36, 37, 70, 71, 72, 73, 74, 75, 76, 80)
            return "EL" if pc else None
        return _PREFIX_TO_CLASS.get(prefix)
    return None


def job_from_skill_loose(code: int):
    if 100510 <= code <= 103500 or 109300 <= code <= 109362:
        return "EL"
    if 10_000_000 <= code <= 19_999_999:
        prefix = code // 1_000_000
        sub = (code // 10000) % 100
        if sub == 0:
            if prefix == 16 and 11 <= (code // 100) % 100 <= 13:
                return "EL"
            return None
        return _PREFIX_TO_CLASS.get(prefix)
    return None


def job_from_roster_class(value: int):
    """The class field of a party roster record (blocks of four per class)."""
    if 5 <= value <= 8:
        return "GL"
    if 9 <= value <= 12:
        return "TE"
    if 13 <= value <= 16:
        return "RA"
    if 17 <= value <= 20:
        return "AS"
    if 21 <= value <= 24:
        return "EL"
    if 25 <= value <= 28:
        return "SO"
    if 29 <= value <= 32:
        return "CL"
    if 33 <= value <= 36:
        return "CH"
    return None


def is_player_skill(code: int) -> bool:
    return (11_000_000 <= code <= 19_999_999
            or 3_000_000 <= code <= 3_999_999
            or 100_000 <= code <= 199_999)


class GameData:
    def __init__(self, lang: str = "en"):
        self.lang = lang if lang in LANGS else "en"
        self.skills = {}
        self.npcs = {}
        self.icon_map = {}
        self.dot_ids = set()
        self.dungeons = {}
        self.load()

    def _path(self, name):
        """A table refreshed by --update-data (user dir) wins over the shipped one."""
        fresh = user_path("data", name)
        return fresh if os.path.exists(fresh) else os.path.join(DATA_DIR, name)

    def load(self):
        skills_file = self._path(f"skills_{self.lang}.json")
        if not os.path.exists(skills_file):
            skills_file = self._path("skills_en.json")
        with open(skills_file, encoding="utf-8") as f:
            self.skills = {int(k): v for k, v in json.load(f).items() if k.isdigit()}

        npcs_file = self._path(f"npcs_{self.lang}.json")
        if not os.path.exists(npcs_file):
            npcs_file = self._path("npcs_en.json")
        with open(npcs_file, encoding="utf-8") as f:
            raw = json.load(f)
        self.npcs = {}
        for k, v in raw.items():
            if not k.isdigit():
                continue
            if isinstance(v, dict):
                name = v.get("name", "")
                self.npcs[int(k)] = (name, bool(v.get("isBoss")),
                                     bool(v.get("isDummy")) or any(d in name for d in _DUMMY_NAMES))
            elif isinstance(v, str):
                self.npcs[int(k)] = (v, False, any(d in v for d in _DUMMY_NAMES))

        with open(self._path("skill_icons.json"), encoding="utf-8") as f:
            self.icon_map = json.load(f)
        with open(self._path("dot_skill_ids.json"), encoding="utf-8") as f:
            self.dot_ids = set(json.load(f))
        try:
            with open(self._path("dungeons_en.json"), encoding="utf-8") as f:
                self.dungeons = {int(k): v.get("name", "") for k, v in json.load(f).items() if k.isdigit()}
        except (OSError, ValueError):
            self.dungeons = {}

    # ----- skills -----

    def raw_name(self, code: int) -> str:
        return self.skills.get(code, "")

    def normalize_skill_id(self, raw: int) -> int:
        """Fold a skill's level/variant digits into its base code when they share a name."""
        if 30_000_000 <= raw <= 30_999_999:
            return raw
        base = raw - (raw % 10000)
        base_name = self.skills.get(base, "")
        if not base_name:
            return raw
        raw_name = self.skills.get(raw, "")
        if not raw_name:
            return base
        if raw_name != base_name:
            return raw
        return base

    def is_known_skill(self, code: int) -> bool:
        if not 1 <= code <= 299_999_999:
            return False
        norm = self.normalize_skill_id(code)
        if not 1 <= norm <= 299_999_999:
            return False
        if 30_000_000 <= norm <= 30_999_999:
            return True
        return bool(self.skills.get(norm) or self.skills.get(code))

    def skill_name(self, code: int) -> str:
        name = self.skills.get(code)
        if name:
            return name
        if 3_000_000 <= code <= 3_099_999:
            name = self.skills.get(code * 10 + 1)
            if name:
                return name
        return ""

    def display_name(self, code: int, is_dot: bool) -> str:
        name = self.skill_name(code) or f"Skill {code}"
        return f"{name} (DoT)" if is_dot else name

    def icon_for(self, code: int):
        """('url', url) for a game icon, or ('basic', None) for basic attacks, ('unknown', None)."""
        digits = str(code)
        code8 = digits[:8] if len(digits) >= 8 else digits.ljust(8, "0")

        # Theostones (item procs): their own icon set.
        if code8.startswith("30") and len(code8) >= 7:
            try:
                icon_code = int(code8[5:7])
            except ValueError:
                icon_code = 0
            if icon_code > 0:
                return "url", f"{ICON_BASE}/Icon_Item_Usable_Godstone_WP_r_{icon_code:03x}.png"

        prefix2, mid4 = code8[:2], code8[2:6]
        if "11" <= prefix2 <= "18" and mid4 == "0000" and code8[6:] != "00":
            return "basic", None
        if code8.startswith("1000") or code8.startswith("1699"):
            return "basic", None

        icon = self.icon_map.get(code8[:4])
        if icon:
            return "url", f"{ICON_BASE}/{icon}.png"

        cls = _PREFIX_TO_CLASS.get(int(prefix2)) if prefix2.isdigit() else None
        if not cls:
            return "unknown", None
        sub = int(code8[2:4])
        return "url", f"{ICON_BASE}/ICON_{cls}_SKILL_{sub:03d}.png"

    def dungeon_name(self, dungeon_id):
        return self.dungeons.get(dungeon_id) or None

    # ----- NPCs -----

    def npc_name(self, code: int) -> str:
        info = self.npcs.get(code)
        return info[0] if info else ""

    def is_boss(self, code: int) -> bool:
        info = self.npcs.get(code)
        return bool(info and info[1])

    def is_dummy(self, code: int) -> bool:
        info = self.npcs.get(code)
        return code in TRAINING_DUMMY_CODES or bool(info and info[2])


def update_data(lang: str = "en", log=print):
    """Download the latest skill/NPC tables (after a game patch)."""
    files = {
        f"i18n/skills/{lang}.json": f"skills_{lang}.json",
        f"i18n/npcs/{lang}.json": f"npcs_{lang}.json",
        "skill_icons.json": "skill_icons.json",
        "dot_skill_ids.json": "dot_skill_ids.json",
    }
    for remote, local in files.items():
        url = f"{UPSTREAM}/{remote}"
        log(f"indiriliyor: {url}")
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read()
        json.loads(body)  # refuse to save anything that is not valid JSON
        dest = user_path("data", local)
        with open(dest + ".tmp", "wb") as f:
            f.write(body)
        os.replace(dest + ".tmp", dest)
    log("oyun verisi güncellendi")
