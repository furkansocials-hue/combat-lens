"""Start-in-the-middle check: replay with every spawn/self name record ignored,
as if the meter was opened after everyone had already appeared.
python tools/midstart_check.py kayitlar/DOSYA.txt"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from aion2meter import meter, protocol  # noqa: E402
from aion2meter.gamedata import CLASSES, GameData  # noqa: E402
from aion2meter.report import build_view, fmt_num, visible_rows  # noqa: E402
from aion2meter.store import Store  # noqa: E402

gd = GameData()
truth = Store(gd, profile_path=None)
meter.replay(sys.argv[1], truth, gd, log=lambda m: None)

protocol.StreamProcessor.parse_player_spawn_name = lambda self, data, at, **kw: None
protocol.StreamProcessor.scan_masked_identity = lambda self, data: None
st = Store(gd, profile_path=None)
meter.replay(sys.argv[1], st, gd, log=lambda m: None)

print("isim kaynağı olarak sadece parti listesi + konum + HP işareti:")
for enc in st.encounters()[:4]:
    view = build_view(st.view(enc))
    print(f"--- {view['title']}")
    for r in visible_rows(view, "party"):
        print(f"   {r['name']:14s} {CLASSES.get(r['job'], '?'):12s} DPS {fmt_num(r['dps']):>7s}"
              f"{'  (sen)' if r['is_local'] else ''}")
wrong = [(e, n, truth.nicknames.get(e)) for e, n in st.nicknames.items()
         if truth.nicknames.get(e) not in (None, n)]
print("yanlış bağlanan isim:", wrong or "yok")
