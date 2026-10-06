"""python -m aion2meter  [--console] [--record [DOSYA]] [--replay DOSYA] [--lang en] [--update-data] [--tk]"""
import argparse
import importlib.util
import sys
import time

from .gamedata import GameData, update_data
from .meter import Dispatcher, default_record_path, replay
from .paths import APP_ID, APP_NAME, migrate_legacy, user_path
from .report import summary_text
from .store import ACCOUNTS_PATH, NAMES_PATH, Store

LOG_PATH = user_path("meter.log")


class _Static:
    """Status for a window showing a replayed recording."""

    def status(self):
        return {"locked": True, "flow": "kayıt", "packets": 0, "game_bytes": 0, "dropped": 0,
                "candidates": 0, "silent_ms": 0}


def _web(store, dispatcher, gd, log, start_capture=None, label=None):
    """The WebView2 interface. False when it cannot run here (then the classic window is used)."""
    if importlib.util.find_spec("webview") is None:
        log("pywebview kurulu değil: klasik pencere açılıyor")
        return False
    try:
        from .webapp import WebApp
    except Exception as e:
        log(f"web arayüzü yüklenemedi: {e!r}")
        return False
    try:
        WebApp(store, dispatcher, gd, start_capture=start_capture, log=log, label=label).run()
    except Exception as e:
        log(f"web arayüzü açılamadı: {e!r}")
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aion2meter", description="AION 2 DPS meter (pasif paket okuma)")
    ap.add_argument("--console", action="store_true", help="arayüz yerine konsola yaz")
    ap.add_argument("--seconds", type=float, default=0, help="--console: bu kadar saniye sonra çık")
    ap.add_argument("--record", nargs="?", const="", default=None, metavar="DOSYA",
                    help="oyun akışını dosyaya kaydet (hata ayıklama / doğrulama için)")
    ap.add_argument("--replay", metavar="DOSYA", help="kaydedilmiş akışı tekrar oynat (pencerede gösterir)")
    ap.add_argument("--lang", default="en", help="skill/NPC isim dili (en, de, fr, es, ru, ko, ja, pt)")
    ap.add_argument("--update-data", action="store_true", help="oyun verisini (skill/NPC) güncelle ve çık")
    ap.add_argument("--demo", action="store_true", help="sahte veriyle pencereyi önizle (gerçek veri değil)")
    ap.add_argument("--tab", choices=("me", "party"), default=None, help="açılıştaki sekme (klasik pencere)")
    ap.add_argument("--tk", action="store_true", help="klasik (Tkinter) pencereyi kullan")
    args = ap.parse_args(argv)

    # One live meter at a time: a second double-click brings the running one forward
    # (checked before the log is opened, so the running meter's log is not wiped).
    live_window = not (args.update_data or args.demo or args.replay or args.console)
    if live_window:
        from .winutil import SingleInstance, bring_to_front
        instance = SingleInstance("Local\\" + APP_ID)  # held until the meter exits
        if not instance.acquire():
            if not bring_to_front(APP_NAME):
                _error_box(f"{APP_NAME} zaten açık.")
            return 0

    migrate_legacy()
    logfile = open(LOG_PATH, "w", encoding="utf-8", buffering=1)

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        logfile.write(line + "\n")
        if sys.stdout is not None:
            print(line, flush=True)

    if args.update_data:
        update_data(args.lang, log=log)
        return 0

    gd = GameData(args.lang)
    store = Store(gd, profile_path=None)  # a demo or someone's recording must not become "your last character"

    if args.demo:
        from .demo import DemoDispatcher
        d = DemoDispatcher(store)
        d.start()
        if args.tk or not _web(store, d, gd, log, label="demo"):
            from .ui import run_ui
            run_ui(store, d, gd, tab=args.tab)
        return 0

    if args.replay:
        t0 = time.time()
        d = replay(args.replay, store, gd, log=log)
        log(f"replay: {time.time() - t0:.1f}s  {d.status()}")
        if args.console:
            print(summary_text(store))
        elif args.tk or not _web(store, _Static(), gd, log, label="replay"):
            from .ui import run_ui
            run_ui(store, _Static(), gd, tab=args.tab)
        return 0

    # live: remember names across restarts (same zone) and account ids for good
    store = Store(gd, names_path=NAMES_PATH, accounts_path=ACCOUNTS_PATH)
    record = None
    if args.record is not None:
        record = args.record or default_record_path()
        log(f"kayıt: {record}")

    dispatcher = Dispatcher(store, gd, record_path=record, log=log)
    from .capture import Capture, NpcapError
    captures = []

    def start_capture():
        cap = Capture(dispatcher.sink, log=log)
        devices = cap.start()  # NpcapError when the driver is missing
        captures.append(cap)
        log("dinlenen bağdaştırıcılar: " + " | ".join(devices))

    dispatcher.start()
    try:
        if args.console or args.tk:
            try:
                start_capture()
            except NpcapError as e:
                log(f"HATA: {e}")
                if not args.console:
                    _error_box(str(e))
                return 1
        if args.console:
            _console(store, dispatcher, args.seconds)
        elif args.tk or not _web(store, dispatcher, gd, log, start_capture=start_capture):
            if not captures:
                try:
                    start_capture()
                except NpcapError as e:
                    log(f"HATA: {e}")
                    _error_box(str(e))
                    return 1
            from .ui import run_ui
            run_ui(store, dispatcher, gd, tab=args.tab)
    finally:
        for cap in captures:
            cap.stop()
        dispatcher.stop()
        log("kapandı")
    return 0


def _console(store, dispatcher, seconds):
    try:
        t_end = time.time() + seconds if seconds else None
        while t_end is None or time.time() < t_end:
            time.sleep(3)
            st = dispatcher.status()
            ss = store.status()
            print(f"[durum] {st} | sen={ss['local_name']}#{ss['local_id']} isim={ss['names']} "
                  f"oyuncu={ss['players']} pet={ss['summons']} mob={ss['mobs']} "
                  f"parti={list(ss['roster'])} kayıt={ss['records']}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        print(summary_text(store))


def _error_box(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
