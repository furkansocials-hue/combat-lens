"""Self-update from the project's GitHub releases: find, download, verify, swap in, restart.

A single-file build replaces its own exe (Windows lets a running exe be renamed) and starts the new
one. A folder build unpacks the new folder to the temp dir and starts the new exe from there with
--install-update; it waits for the old app to exit, copies itself over it and starts it.
"""
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

from . import __version__
from .paths import APP_ID, APP_NAME, GITHUB_REPO

STAGING = os.path.join(tempfile.gettempdir(), APP_ID + "-update")
# Only these hosts serve release files; a feed pointing anywhere else is refused.
_ALLOWED = ("https://github.com/", "https://objects.githubusercontent.com/",
            "https://release-assets.githubusercontent.com/")


def version_tuple(v):
    out = []
    for part in str(v).lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits or 0))
    return tuple(out)


def install_kind():
    """'onefile', 'onedir' (a frozen build) or 'source' (run from the code: no self-update)."""
    if not getattr(sys, "frozen", False):
        return "source"
    here = os.path.dirname(sys.executable)
    return "onedir" if os.path.isdir(os.path.join(here, "_internal")) else "onefile"


def latest_release(timeout=10):
    """The newest release: {version, page, assets: {name: {url, size, digest}}}. Raises on failure.
    COMBATLENS_UPDATE_FEED (a local JSON file in GitHub's format) stands in for the API in tests."""
    feed = os.environ.get("COMBATLENS_UPDATE_FEED")
    if feed:
        with open(feed, encoding="utf-8") as f:
            rel = json.load(f)
    else:
        req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                     headers={"User-Agent": APP_NAME, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rel = json.loads(r.read())
    tag = rel.get("tag_name") or ""
    return {
        "version": tag.lstrip("vV"),
        "page": rel.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest",
        "assets": {a["name"]: {"url": a["browser_download_url"], "size": a.get("size"), "digest": a.get("digest")}
                   for a in rel.get("assets", [])},
    }


def is_newer(info):
    return bool(info) and version_tuple(info["version"]) > version_tuple(__version__)


def pick_asset(info, kind=None):
    kind = kind or install_kind()
    names = info["assets"]
    if kind == "onefile":
        return names.get(APP_ID + ".exe")
    if kind == "onedir":
        name = next((n for n in names if n.startswith(APP_ID + "-") and n.endswith(".zip")), None)
        return names.get(name)
    return None


class Updater:
    """Runs one update in the background; `state` is what the update screen shows."""

    def __init__(self, log=print):
        self.log = log
        self.state = {"stage": "idle"}
        self.thread = None

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, info, on_ready):
        """`on_ready()` is called once the new version is in place and started: the app then quits."""
        if self.busy():
            return
        self.state = {"stage": "download", "pct": 0, "done": 0, "total": 0, "version": info["version"]}
        self.thread = threading.Thread(target=self._run, args=(info, on_ready), name="update", daemon=True)
        self.thread.start()

    def _run(self, info, on_ready):
        try:
            kind = install_kind()
            asset = pick_asset(info, kind)
            if kind == "source" or asset is None:
                raise RuntimeError("bu kurulum kendini güncelleyemiyor")
            url = asset["url"]
            if not (url.startswith(_ALLOWED) or (os.environ.get("COMBATLENS_UPDATE_FEED") and url.startswith("file:"))):
                raise RuntimeError("beklenmeyen indirme adresi")
            shutil.rmtree(STAGING, ignore_errors=True)
            os.makedirs(STAGING, exist_ok=True)
            path = os.path.join(STAGING, os.path.basename(url.split("?")[0]) or "update.bin")
            digest = self._download(url, path, asset.get("size"))
            self.state.update(stage="verify")
            want = (asset.get("digest") or "").split(":")[-1].lower()
            if want and digest != want:
                raise RuntimeError("indirilen dosya doğrulanamadı")
            self.state.update(stage="install")
            if kind == "onefile":
                self._swap_exe(path)
            else:
                self._stage_folder(path)
            self.state.update(stage="restart")
            time.sleep(0.8)  # long enough to read "restarting"
            on_ready()
        except Exception as e:
            self.log(f"güncelleme başarısız: {e!r}")
            self.state = dict(self.state, stage="error", error=str(e))

    def _download(self, url, path, size):
        h = hashlib.sha256()
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
            total = int(r.headers.get("Content-Length") or size or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                self.state.update(done=done, total=total, pct=round(done * 100 / total) if total else 0)
        if size and done != size:
            raise RuntimeError("indirme yarım kaldı")
        return h.hexdigest()

    def _swap_exe(self, new_file):
        """Single file: the running exe moves aside, the new one takes its name and is started."""
        exe = sys.executable
        old = os.path.splitext(exe)[0] + ".old.exe"
        tmp = exe + ".new"
        shutil.copy2(new_file, tmp)  # onto the same drive first, so the swap below is two renames
        try:
            os.remove(old)
        except OSError:
            pass
        os.replace(exe, old)
        try:
            os.replace(tmp, exe)
        except OSError:
            os.replace(old, exe)  # put the old one back: the app keeps working
            raise
        _launch([exe] + relaunch_args() + ["--wait-pid", str(os.getpid()), "--updated"])

    def _stage_folder(self, zip_path):
        """Folder build: unpack the new folder and let its exe copy itself over this one."""
        target = os.path.dirname(sys.executable)
        out = os.path.join(STAGING, "new")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out)
        new_exe = os.path.join(out, APP_ID, APP_ID + ".exe")
        if not os.path.isfile(new_exe):
            raise RuntimeError("güncelleme paketinde uygulama yok")
        _launch([new_exe, "--install-update", target, "--wait-pid", str(os.getpid())] + relaunch_args())


def relaunch_args():
    """The options this run was started with, so the restarted app opens the same way."""
    out, skip = [], False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a in ("--wait-pid", "--install-update"):
            skip = True
            continue
        if a != "--updated":
            out.append(a)
    return out


def _launch(cmd):
    # A frozen app started from a frozen app would take over the parent's unpacked files (which go
    # away with the parent); this makes the new one set itself up from scratch.
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI_") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=os.path.dirname(cmd[0]), env=env)


def wait_for_exit(pid, timeout=30.0):
    """Block until process `pid` is gone (the old app freeing its files and its single-run lock)."""
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if not h:
        return
    try:
        k32.WaitForSingleObject(h, int(timeout * 1000))
    finally:
        k32.CloseHandle(h)


def install_folder(target, rest_args, log=print):
    """Run by the new exe from the temp dir: copy this new folder over the old one, start it."""
    source = os.path.dirname(sys.executable)
    for attempt in range(20):
        try:
            shutil.copytree(source, target, dirs_exist_ok=True)
            break
        except OSError as e:  # a file still held for a moment (antivirus, OneDrive): try again
            if attempt == 19:
                log(f"güncelleme kopyalanamadı: {e!r}")
                raise
            time.sleep(0.5)
    time.sleep(1.5)  # let the freshly written files settle before starting from them
    _launch([os.path.join(target, APP_ID + ".exe")] + rest_args + ["--updated"])


def cleanup_after_update():
    """Remove what an earlier update left behind (the old single exe, the unpacked folder)."""
    if getattr(sys, "frozen", False):
        try:
            os.remove(os.path.splitext(sys.executable)[0] + ".old.exe")
        except OSError:
            pass
    if not os.path.abspath(sys.executable).startswith(os.path.abspath(STAGING)):
        shutil.rmtree(STAGING, ignore_errors=True)
