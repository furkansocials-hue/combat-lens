"""Builds dist/CombatLens (one folder, CombatLens.exe inside) and dist/CombatLens-<version>.zip.

Run with the project's virtualenv:  .venv\\Scripts\\python tools\\build_exe.py
Npcap is not bundled (its licence does not allow it); the app links to npcap.com on first start.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from aion2meter import __version__  # noqa: E402
from aion2meter.paths import APP_ID  # noqa: E402


def main():
    # --dist FOLDER: build somewhere else (e.g. while the current build is running)
    dist = sys.argv[sys.argv.index("--dist") + 1] if "--dist" in sys.argv else os.path.join(ROOT, "dist")
    pkg = os.path.join(ROOT, "aion2meter")
    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", APP_ID,
        "--icon", os.path.join(pkg, "web", "app.ico"),
        "--add-data", f"{os.path.join(pkg, 'data')}{sep}aion2meter/data",
        "--add-data", f"{os.path.join(pkg, 'web')}{sep}aion2meter/web",
        "--collect-all", "webview",
        "--hidden-import", "clr",
        "--distpath", dist,
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        os.path.join(ROOT, "run_meter.py"),
    ]
    subprocess.check_call(args, cwd=ROOT)
    out = os.path.join(dist, APP_ID)
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(os.path.join(ROOT, name), out)
    archive = shutil.make_archive(os.path.join(dist, f"{APP_ID}-{__version__}"), "zip", dist, APP_ID)
    print("hazır:", os.path.join(out, APP_ID + ".exe"))
    print("zip:", archive)


if __name__ == "__main__":
    main()
