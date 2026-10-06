"""Where things live: bundled resources (read-only) and the user's own files (%APPDATA%)."""
import os
import shutil
import sys

APP_NAME = "Combat Lens"
APP_ID = "CombatLens"
_OLD_IDS = ("DaevaMeter",)  # earlier names: their user folder is taken over once
GITHUB_REPO = "furkansocials-hue/combat-lens"  # releases there are offered as updates; "" turns it off

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_PKG_DIR)


def resource_dir():
    """The package's own files (data tables, web UI). Inside the bundle when frozen."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "aion2meter")
    return _PKG_DIR


def resource(*parts):
    return os.path.join(resource_dir(), *parts)


def user_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_ID)
    if not os.path.isdir(path):
        _take_over_old_folder(base, path)
    os.makedirs(path, exist_ok=True)
    return path


def _take_over_old_folder(base, path):
    """Settings, saved fights and the account book of a build that ran under an earlier name."""
    for old in _OLD_IDS:
        prev = os.path.join(base, old)
        if not os.path.isdir(prev):
            continue
        try:
            os.rename(prev, path)
        except OSError:  # a file still open there: copy instead, the old folder stays as it is
            try:
                shutil.copytree(prev, path, dirs_exist_ok=True)
            except OSError:
                pass
        return


def user_path(*parts):
    path = os.path.join(user_dir(), *parts)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


_LEGACY = ("son_karakter.json", "oyuncu_hesaplari.json", "isim_onbellek.json")


def migrate_legacy():
    """Bring files an earlier, folder-based version kept next to the code into the user dir."""
    for name in _LEGACY:
        old = os.path.join(_PROJECT_DIR, name)
        new = os.path.join(user_dir(), name)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                shutil.copy2(old, new)
            except OSError:
                pass
