"""Fill the account book (oyuncu_hesaplari.json) from recordings, so players seen
in them are named from now on. python tools/learn_accounts.py kayitlar/*.txt"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter  # noqa: E402
from aion2meter.gamedata import GameData  # noqa: E402
from aion2meter.store import ACCOUNTS_PATH, Store  # noqa: E402

gd = GameData()
paths = [p for a in sys.argv[1:] for p in glob.glob(a)]
for path in paths:
    st = Store(gd, profile_path=None, accounts_path=ACCOUNTS_PATH)
    before = len(st.dbid_names)
    meter.replay(path, st, gd, log=lambda m: None)
    st._accounts_saved_at = 0
    st._save_accounts()
    print(f"{os.path.basename(path)}: {len(st.dbid_names) - before} yeni oyuncu (toplam {len(st.dbid_names)})")
