"""The meter's windows: a see-through overlay over the game and an analysis window (WebView2)."""
import base64
import json
import os
import tempfile
import threading
import time

from . import __version__
from .api import encounter_detail, history_list, overlay_state
from .history import History
from .paths import APP_NAME, GITHUB_REPO, resource, user_dir, user_path
from .report import build_view
from .server import NOT_FOUND, UIServer
from .settings import Settings
from .timers import BossTimers
from .updater import Updater, is_newer, latest_release, pick_asset
from .winutil import Hotkeys, round_corners, set_clickthrough

STRIP_H = 38
RADIUS = 12          # the overlay's rounded corners, as in overlay.css
PANEL_BG = "#111018"  # the overlay's own colour, behind the page while it loads
_SAFE_URLS = ("https://npcap.com", "https://github.com/", "https://www.microsoft.com/")



class WebApp:
    def __init__(self, store, dispatcher, gd, start_capture=None, log=print, label=None, just_updated=False):
        self.store = store
        self.dispatcher = dispatcher
        self.gd = gd
        self.log = log
        self.label = label                    # "kayıt" / "demo": not a live capture
        self.start_capture = start_capture    # () -> None, raises NpcapError
        self.npcap_ok = start_capture is None
        self.npcap_error = None
        self.settings = Settings()
        # a demo or a replayed recording is shown, never added to your saved fights
        self.history = History(folder=tempfile.mkdtemp(prefix="combatlens_")) if label else History()
        self.update_info = None  # {version, url, can_install} when a newer release is out
        self._release = None
        self.updater = Updater(log)
        self.just_updated = just_updated
        self.clickthrough = False
        self.hidden = False
        self.hotkeys = None
        self.overlay = None
        self.analysis = None
        self._want = {}  # window -> (w, h) asked for, restored once the window is up
        self._overlay_hwnd = None
        self._geom_dirty = False
        store.on_end = self._on_fight_end
        self.timers = BossTimers()
        self._logged_worlds = set()
        if not label:  # a demo or a recording must not start real respawn timers
            store.on_kill = self._on_kill
            store.on_field_bosses = self._on_field_bosses
        self.server = UIServer(self).start()

    # ───────── fights → history ─────────

    def _on_fight_end(self, enc):
        resolved = enc.frozen

        def keep():
            try:
                self.history.add(resolved, build_view(resolved)["title"])
            except Exception as e:
                self.log(f"geçmişe yazılamadı: {e!r}")
        threading.Thread(target=keep, name="history", daemon=True).start()

    def _on_kill(self, code):
        # called under the store's lock: the file write goes to its own thread
        if self.timers.is_field_boss(code):
            threading.Thread(target=self.timers.note_kill, args=(code,), name="boss-kill", daemon=True).start()

    def _on_field_bosses(self, world, entries, ms):
        # the game's own field boss list, every few seconds while you are in a field world
        if not self.timers.note_list(world, entries, ms) and (world, len(entries)) not in self._logged_worlds:
            self._logged_worlds.add((world, len(entries)))
            self.log(f"bilinmeyen boss listesi: dünya {world}, {len(entries)} boss")

    # ───────── HTTP API ─────────

    def api_get(self, route, q):
        s = self.settings
        if route == "state":
            out = overlay_state(self, q.get("mode") or s["mode"], q.get("tab") or s["tab"], q.get("pin"),
                                s["keep_fight"])
            out["status"]["updating"] = None if self.updater.state["stage"] == "idle" else self.updater.state
            out["ui"] = {"folded": s["folded"], "lang": s["lang"], "mode": s["mode"], "tab": s["tab"],
                         "opacity": s["opacity"], "welcomed": s["welcomed"], "label": self.label,
                         "npcap_error": self.npcap_error, "hotkeys": s["hotkeys"],
                         "analysis_open": self.analysis is not None, "version": __version__,
                         "just_updated": __version__ if self.just_updated else None, "keep_fight": s["keep_fight"],
                         "faction": s["faction"], "region": s["region"]}
            return out
        if route == "timers":
            return dict(self.timers.state(), faction=s["faction"], region=s["region"])
        if route == "encounter":
            d = encounter_detail(self, q.get("id"), q.get("mode") or s["mode"])
            return d if d is not None else NOT_FOUND
        if route == "history":
            return {"items": history_list(self)}
        if route == "settings":
            return dict(s.data, version=__version__, app=APP_NAME, data_dir=user_dir(),
                        hotkeys_failed=self.hotkeys.failed if self.hotkeys else [],
                        update=self.update_info, repo=GITHUB_REPO)
        return NOT_FOUND

    def api_post(self, route, body):
        if route != "action":
            return {"error": "unknown"}
        op = body.get("op")
        st = self.store
        if op == "reset":
            st.clear_history()  # the panel starts from zero; finished fights stay saved for Analysis
        elif op == "pause":
            st.set_paused(bool(body.get("on", not st.paused)))
        elif op == "clear":
            st.clear_history()
        elif op == "favorite":
            self.history.set_favorite(body.get("id"), body.get("on"))
        elif op == "delete":
            self.history.delete(body.get("id"))
        elif op == "settings":
            self._apply_settings(body.get("values") or {})
        elif op == "fold":
            self.set_folded(bool(body.get("on", not self.settings["folded"])))
        elif op == "resize":
            self._resize(body.get("win"), int(body.get("w", 0)), int(body.get("h", 0)))
        elif op == "close":
            self._close(body.get("win"))
        elif op == "minimize":
            win = self._win(body.get("win"))
            if win:
                win.minimize()
        elif op == "maximize":
            self._toggle_maximize(self._win(body.get("win")))
        elif op == "analysis":
            self.open_analysis(body.get("id"))
        elif op == "clickthrough":
            self.set_clickthrough(bool(body.get("on", not self.clickthrough)))
        elif op == "open_url":
            url = str(body.get("url") or "")
            if url.startswith(_SAFE_URLS):
                os.startfile(url)
        elif op == "open_folder":
            os.startfile(user_dir())
        elif op == "retry_npcap":
            self.try_capture()
        elif op == "boss_kill":
            self.timers.note_kill(int(body.get("code", 0)))
        elif op == "boss_clear":
            self.timers.clear(int(body.get("code", 0)))
        elif op == "boss_cycle":
            self.timers.set_cycle(int(body.get("code", 0)), int(body.get("minutes", 0)))
        elif op == "check_update":
            ok = self._check_updates(force=True)
            return {"ok": ok, "update": self.update_info, "version": __version__}
        elif op == "install_update":
            if self._release is None or not (self.update_info or {}).get("can_install"):
                return {"error": "no update"}
            self.updater.start(self._release, on_ready=self._quit_for_update)
        elif op == "update_dismiss":
            if not self.updater.busy():
                self.updater.state = {"stage": "idle"}
        elif op == "update_data":
            threading.Thread(target=self._update_data, daemon=True).start()
        elif op == "copy_text":
            return {"ok": self._clipboard(text=str(body.get("text") or ""))}
        elif op == "copy_image":
            png = base64.b64decode(str(body.get("png") or "").split(",")[-1])
            return {"ok": self._clipboard(png=png)}
        elif op == "save_image":
            png = base64.b64decode(str(body.get("png") or "").split(",")[-1])
            return {"path": self._save_png(png)}
        else:
            return {"error": "unknown op"}
        return {"ok": True}

    # ───────── settings, geometry ─────────

    def _apply_settings(self, values):
        old_keys = dict(self.settings["hotkeys"])
        self.settings.update(values)
        if "opacity" in values:
            self._tune_overlay()
        if self.settings["hotkeys"] != old_keys:
            self._start_hotkeys()

    def _win(self, name):
        return self.analysis if name == "analysis" else self.overlay

    def _resize(self, name, w, h):
        win = self._win(name)
        if win is None or w < 200:
            return
        if name == "analysis":
            win.resize(max(w, 760), max(h, 480))
            return
        folded = self.settings["folded"]
        h = STRIP_H if folded else max(h, 150)
        win.resize(max(w, 280), h)

    def _toggle_maximize(self, win):
        if win is None:
            return
        try:
            from System.Windows.Forms import FormWindowState
            state = win.native.WindowState
            (win.restore if state == FormWindowState.Maximized else win.maximize)()
        except Exception:
            win.maximize()

    def set_folded(self, on):
        """The bottom edge stays put: the panel folds down onto the strip and opens upwards from it."""
        from webview.window import FixPoint
        self.settings.update({"folded": on})
        if self.overlay is not None:
            o = self.settings["overlay"]
            self.overlay.resize(o["w"], STRIP_H if on else o["h"], fix_point=FixPoint.SOUTH | FixPoint.WEST)
            if not on:
                self._keep_overlay_on_screen()

    def _keep_overlay_on_screen(self):
        """Keep the whole panel on its monitor: opening upwards near the top edge, or a start with
        the panel open where the strip was near the bottom edge, would push part of it off."""
        import webview
        win = self.overlay
        try:
            x, y, w, h = win.x, win.y, win.width, win.height
            cx = x + w // 2
            scr = (next((s for s in webview.screens if s.x <= cx < s.x + s.width and s.y <= y < s.y + s.height), None)
                   or next((s for s in webview.screens if s.x <= cx < s.x + s.width and s.y < y + h <= s.y + s.height), None))
        except Exception:
            return
        if scr is None:
            return
        top = min(max(y, scr.y), max(scr.y, scr.y + scr.height - h))
        if top != y:
            win.move(x, top)

    def _on_moved(self, x, y):
        if not self.hidden:
            self.settings.data["overlay"].update(x=x, y=y)
            self._geom_dirty = True

    def _on_resized(self, w, h):
        round_corners(self._overlay_hwnd, RADIUS)
        o = self.settings.data["overlay"]
        o["w"] = w
        if not self.settings["folded"] and h > STRIP_H + 20:
            o["h"] = h
        self._geom_dirty = True

    def _on_analysis_resized(self, w, h):
        if w >= 760 and h >= 480:
            self.settings.data["analysis"].update(w=w, h=h)
            self._geom_dirty = True

    def _housekeeping(self):
        last_check = time.time()
        while True:
            time.sleep(2)
            if time.time() - last_check > 6 * 3600:  # a long session hears about a new release too
                last_check = time.time()
                self._check_updates()
            if self._geom_dirty:
                self._geom_dirty = False
                self.settings.update({})

    # ───────── native window tweaks (WinForms under pywebview) ─────────

    def _invoke(self, win, fn):
        from System import Action
        form = win.native
        if form is not None:
            form.Invoke(Action(fn))

    def _overlay_shown(self):
        # A frameless form opens smaller than asked by the size of a normal window frame;
        # set the exact size once it is up, so the saved size does not shrink every start.
        w, h = self._want["overlay"]
        self.settings.data["overlay"].update(w=w, h=h)
        self.overlay.resize(w, STRIP_H if self.settings["folded"] else h)
        self._keep_overlay_on_screen()
        self._tune_overlay()

    def _analysis_shown(self):
        w, h = self._want["analysis"]
        self.settings.data["analysis"].update(w=w, h=h)
        if self.analysis is not None:
            self.analysis.resize(w, h)

    def _tune_overlay(self):
        """Window opacity lets the game show through; a rounded window region shapes the panel.
        (A colour key would look the same but lets every click fall through to the game.)"""
        win = self.overlay
        if win is None:
            return
        opacity = min(1.0, max(0.35, float(self.settings["opacity"])))

        def apply():
            form = win.native
            form.Opacity = opacity
            self._overlay_hwnd = form.Handle.ToInt64()
            round_corners(self._overlay_hwnd, RADIUS)
            if self.clickthrough:
                set_clickthrough(self._overlay_hwnd, True)
        try:
            self._invoke(win, apply)
        except Exception as e:
            self.log(f"pencere ayarı: {e!r}")

    def set_clickthrough(self, on):
        """Clicks go to the game while on; the hotkey turns it back off."""
        self.clickthrough = on
        win = self.overlay
        if win is None:
            return

        def apply():
            set_clickthrough(win.native.Handle.ToInt64(), on)
        try:
            self._invoke(win, apply)
        except Exception as e:
            self.log(f"tıklama geçirgenliği: {e!r}")

    def _clipboard(self, text=None, png=None):
        win = self.analysis or self.overlay
        if win is None:
            return False
        done = []

        def apply():
            from System.Windows.Forms import Clipboard
            if text is not None:
                Clipboard.SetText(text)
            else:
                from System import Array, Byte
                from System.Drawing import Image
                from System.IO import MemoryStream
                img = Image.FromStream(MemoryStream(Array[Byte](png)))
                Clipboard.SetImage(img)
            done.append(True)
        try:
            self._invoke(win, apply)
        except Exception as e:
            self.log(f"pano: {e!r}")
        return bool(done)

    def _save_png(self, png):
        folder = os.path.join(os.path.expanduser("~"), "Pictures", APP_NAME)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("savas_%Y%m%d_%H%M%S.png"))
        with open(path, "wb") as f:
            f.write(png)
        os.startfile(folder)
        return path

    # ───────── windows ─────────

    def _close(self, name):
        if name == "analysis":
            if self.analysis is not None:
                self.analysis.destroy()
            return
        self.settings.update({})
        for w in (self.analysis, self.overlay):
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass

    def toggle_hidden(self):
        if self.overlay is None:
            return
        self.hidden = not self.hidden
        (self.overlay.hide if self.hidden else self.overlay.show)()

    def open_analysis(self, fid=None):
        import webview
        if self.analysis is not None:
            try:
                self.analysis.restore()
                self.analysis.show()
                if fid:
                    self.analysis.evaluate_js(f"window.openFight && window.openFight({json.dumps(fid)})")
            except Exception:
                pass
            return
        a = self.settings["analysis"]
        self._want["analysis"] = (a["w"], a["h"])
        url = self.server.url("analysis.html", id=fid or "")
        x, y = self._centre_on_overlay_screen(a["w"], a["h"])
        win = webview.create_window(f"{APP_NAME} · Analiz", url, width=a["w"], height=a["h"], x=x, y=y,
                                    frameless=True, easy_drag=False, min_size=(760, 480), on_top=True,
                                    background_color="#0d0c12")  # on top: the game is a borderless full screen
        win.events.closed += self._analysis_closed
        win.events.shown += self._analysis_shown
        win.events.resized += self._on_analysis_resized
        self.analysis = win

    def _centre_on_overlay_screen(self, w, h):
        """(x, y) that centres a window on the monitor the overlay is on (not just the primary one)."""
        import webview
        o = self.settings["overlay"]
        if o["x"] is None or o["y"] is None:
            return None, None
        cx, cy = o["x"] + o["w"] // 2, o["y"] + 19
        try:
            screens = list(webview.screens)
        except Exception:
            return None, None
        scr = next((s for s in screens if s.x <= cx < s.x + s.width and s.y <= cy < s.y + s.height), None)
        if scr is None:
            return None, None
        return scr.x + max(0, (scr.width - w) // 2), scr.y + max(0, (scr.height - h) // 2)

    def _analysis_closed(self):
        self.analysis = None

    def toggle_analysis(self):
        if self.analysis is not None:
            self.analysis.destroy()
        else:
            self.open_analysis()

    # ───────── hotkeys ─────────

    def _start_hotkeys(self):
        if self.hotkeys is not None:
            self.hotkeys.stop()
        self.hotkeys = Hotkeys(self.settings["hotkeys"], self._on_hotkey)
        self.hotkeys.start()
        self.hotkeys.ready.wait(2)
        if self.hotkeys.failed:
            self.log("kullanılamayan kısayollar: " + ", ".join(self.hotkeys.failed))

    def _on_hotkey(self, name):
        st = self.store
        if name == "reset":
            st.clear_history()
        elif name == "pause":
            st.set_paused(not st.paused)
        elif name == "fold":
            self.set_folded(not self.settings["folded"])
        elif name == "hide":
            self.toggle_hidden()
        elif name == "clickthrough":
            self.set_clickthrough(not self.clickthrough)
        elif name == "analysis":
            self.toggle_analysis()

    # ───────── capture, updates ─────────

    def try_capture(self):
        if self.start_capture is None or self.npcap_ok:
            return True
        try:
            self.start_capture()
        except Exception as e:  # NpcapError or a driver hiccup: the overlay explains it
            self.npcap_ok = False
            self.npcap_error = str(e)
            return False
        self.npcap_ok = True
        self.npcap_error = None
        return True

    def _check_updates(self, force=False):
        """False when GitHub could not be reached."""
        if not GITHUB_REPO or not (force or self.settings["check_updates"]):
            return True
        try:
            info = latest_release()
        except Exception as e:
            self.log(f"güncelleme denetlenemedi: {e!r}")
            return False
        if is_newer(info):
            self._release = info
            self.update_info = {"version": info["version"], "url": info["page"],
                                "can_install": pick_asset(info) is not None}
        else:
            self._release = self.update_info = None
        return True

    def _quit_for_update(self):
        """The new version is in place and starting: this one steps aside."""
        self._close(None)

    def _update_data(self):
        from .gamedata import update_data
        try:
            update_data(self.gd.lang, log=self.log)
            with self.store.lock:
                self.gd.load()
        except Exception as e:
            self.log(f"veri güncellenemedi: {e!r}")

    # ───────── run ─────────

    def run(self):
        import webview
        s = self.settings
        o = s["overlay"]
        if o["x"] is None or o["y"] is None:  # first run: top right, clear of the game's minimap
            try:
                scr = webview.screens[0]
                o["x"], o["y"] = scr.x + scr.width - o["w"] - 300, scr.y + 140
            except Exception:
                pass
        h = STRIP_H if s["folded"] else o["h"]
        self._want["overlay"] = (o["w"], o["h"])
        self.overlay = webview.create_window(APP_NAME, self.server.url("overlay.html"), width=o["w"], height=h,
                                             x=o["x"], y=o["y"], frameless=True, easy_drag=False, on_top=True,
                                             shadow=False, min_size=(280, 30), background_color=PANEL_BG)
        self.overlay.events.shown += self._overlay_shown
        self.overlay.events.moved += self._on_moved
        self.overlay.events.resized += self._on_resized
        if os.environ.get("COMBATLENS_DEBUG"):
            self.log(f"arayüz (pid {os.getpid()}): " + self.server.url("overlay.html"))
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()
        threading.Thread(target=self._check_updates, name="updates", daemon=True).start()
        self.try_capture()
        self._start_hotkeys()
        icon = resource("web", "app.ico")
        try:
            webview.start(gui="edgechromium", private_mode=True,
                          storage_path=os.path.dirname(user_path("webview", "x")),
                          icon=icon if os.path.exists(icon) else None)
        finally:
            if self.hotkeys is not None:
                self.hotkeys.stop()
            self.settings.update({})
            self.server.stop()
