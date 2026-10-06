"""Overlay window ([Ben] / [Parti], Durdur / Sıfırla) and a larger details window."""
import ctypes
import json
import math
import os
import tkinter as tk
import tkinter.font as tkfont

from .gamedata import CLASSES
from .icons import IconCache
from .report import (MODE_ALL, MODE_TARGET, build_view, fmt_full, fmt_num, fmt_pct, fmt_time,
                     party_share, row_summary, skill_rows, visible_rows)

BG = "#0f1319"
PANEL = "#161b23"
PANEL_HI = "#1d2430"
LINE = "#252d3a"
TEXT = "#e7eaf0"
MUTED = "#8a93a6"
FAINT = "#5a6273"
ACCENT = "#e3b55b"
LIVE = "#5fd38d"
WARN = "#e8a33d"
BAD = "#e5636b"
DOT = "#c9a0ff"

CLASS_COLORS = {
    "GL": "#e08a3c",  # Gladiator
    "TE": "#6ea7e0",  # Templar
    "AS": "#ad7fe0",  # Assassin
    "RA": "#6cc472",  # Ranger
    "SO": "#e85d6c",  # Sorcerer
    "EL": "#3fc6b6",  # Spiritmaster
    "CL": "#efd36a",  # Cleric
    "CH": "#e98bc4",  # Chanter
    "GT": "#c3c8d1",  # Brawler
}
NO_CLASS = "#9aa3b5"

END_REASONS = {"idle": "bitti", "kill": "hedef öldü", "boss": "bitti", "zone": "bölge değişti",
               "reset": "sıfırlandı", "paused": "durduruldu"}

REFRESH_MS = 400
MIN_W, MIN_H = 390, 240   # unscaled px
STRIP_H = 34              # height of the folded strip (and of the header)
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ayarlar.json")


def _load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _blend(hex_a, hex_b, t):
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class _Surface:
    """A canvas redrawn from scratch each time, with its own click regions, drag and resize."""

    drag_height = 34

    def _init_surface(self, window, k):
        self.win = window
        self.k = k
        self.canvas = tk.Canvas(window, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.hits = []
        self._content = False
        self._ctop = 0
        self._cbot = 10 ** 9
        self._drag = None
        self._resize = None
        self.scroll = 0
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_motion)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Enter>", lambda e: c.focus_set())  # so the wheel scrolls the window under the mouse

    def s(self, v):
        return int(round(v * self.k))

    def _ellipsize(self, text, font, width):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…"

    def _hit(self, x0, y0, x1, y1, cb):
        self.hits.append((x0, y0, x1, y1, cb, self._content))

    def _button(self, x0, y0, x1, y1, label, active, cb, font, fg=None, outline=None):
        c = self.canvas
        c.create_rectangle(x0, y0, x1, y1, fill=PANEL_HI if active else PANEL,
                           outline=outline or (ACCENT if active else LINE), width=1)
        c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=label, font=font,
                      fill=fg or (TEXT if active else MUTED))
        self._hit(x0, y0, x1, y1, cb)

    def _grip(self, W, H):
        for i in range(3):
            o = self.s(4 + i * 4)
            self.canvas.create_line(W - o, H - self.s(2), W - self.s(2), H - o, fill=FAINT)

    def _on_press(self, e):
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if e.x > w - self.s(16) and e.y > h - self.s(16) and not getattr(self, "collapsed", False):
            self._resize = (e.x_root, e.y_root, self.win.winfo_width(), self.win.winfo_height())
            return
        for x0, y0, x1, y1, cb, in_content in reversed(self.hits):
            if in_content and not self._ctop <= e.y <= self._cbot:
                continue
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                cb()
                return
        if e.y < self.s(self.drag_height):
            self._drag = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _on_motion(self, e):
        if self._drag:
            dx, dy = self._drag
            self.win.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")
        elif self._resize:
            x, y, w, h = self._resize
            mw, mh = self.win.minsize()
            self.win.geometry(f"{max(mw, w + e.x_root - x)}x{max(mh, h + e.y_root - y)}")

    def _on_release(self, _e):
        self._drag = None
        self._resize = None

    def _on_wheel(self, e):
        self.scroll = max(0, self.scroll - int(e.delta / 120 * self.s(48)))
        self.redraw(force=True)

    def _clamp_scroll(self, content_end, top, bottom):
        content_h = content_end + self.scroll - top
        max_scroll = max(0, content_h - (bottom - top) + self.s(8))
        if self.scroll > max_scroll:
            self.scroll = max_scroll
            self.win.after_idle(lambda: self.redraw(force=True))

    def _icon(self, app, kind, url, x, y, size, font):
        c = self.canvas
        photo = app.photo(url, size) if kind == "url" else None
        if photo is not None:
            c.create_image(x, y, image=photo, anchor="nw")
        else:
            c.create_rectangle(x, y, x + size, y + size, fill=PANEL_HI, outline=LINE)
            c.create_text(x + size / 2, y + size / 2, text="⚔" if kind == "basic" else "✦",
                          font=font, fill=MUTED)


# ═════════════════════════ main overlay ═════════════════════════

class MeterUI(_Surface):
    def __init__(self, store, dispatcher, gamedata):
        _dpi_aware()
        self.store = store
        self.dispatcher = dispatcher
        self.gd = gamedata
        self.root = tk.Tk()
        self.root.title("AION2 DPS")
        k = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        self.k = k
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.alpha = 0.97
        self.root.configure(bg=BG)
        self.settings = _load_settings()
        w, h = self.s(380), self.s(470)
        sw = self.root.winfo_screenwidth()
        geo = self.settings.get("geometry") or f"{w}x{h}+{sw - w - self.s(40)}+{self.s(120)}"
        try:  # a window saved narrower than the header now needs is widened
            size, _, pos = geo.partition("+")
            gw, gh = (int(v) for v in size.split("x"))
            geo = f"{max(gw, self.s(MIN_W))}x{max(gh, self.s(MIN_H))}+{pos}"
        except ValueError:
            pass
        self.root.geometry(geo)
        if isinstance(self.settings.get("alpha"), (int, float)):
            self.alpha = min(1.0, max(0.3, self.settings["alpha"]))
        self.root.attributes("-alpha", self.alpha)
        self.root.minsize(self.s(MIN_W), self.s(MIN_H))
        self.collapsed = False  # "–": the window folds into one strip
        self._full_height = self.settings.get("full_height")

        fam = "Segoe UI"
        num = "Bahnschrift" if "Bahnschrift" in tkfont.families() else fam
        F = tkfont.Font
        self.f_title = F(family=fam, size=10, weight="bold")
        self.f_tab = F(family=fam, size=9, weight="bold")
        self.f_bold = F(family=fam, size=9, weight="bold")
        self.f_small = F(family=fam, size=8)
        self.f_num_b = F(family=num, size=10, weight="bold")
        self.f_big = F(family=num, size=20, weight="bold")
        self.f_glyph = F(family="Segoe UI Symbol", size=11)
        # details window: one size up
        self.fd_title = F(family=fam, size=13, weight="bold")
        self.fd_head = F(family=fam, size=11, weight="bold")
        self.fd_bold = F(family=fam, size=10, weight="bold")
        self.fd_body = F(family=fam, size=10)
        self.fd_small = F(family=fam, size=9)
        self.fd_num = F(family=num, size=11)
        self.fd_num_b = F(family=num, size=11, weight="bold")
        self.fd_big = F(family=num, size=26, weight="bold")
        self.fd_glyph = F(family="Segoe UI Symbol", size=14)

        self._init_surface(self.root, k)
        self.tab = "party"     # "me" | "party"
        self.mode = MODE_ALL   # all targets | main target
        self.pinned = None     # encounter id being viewed, None = follow the latest
        self.enc = None
        self.view = None
        self.photos = {}
        self.icons = IconCache()
        self._last_sig = None
        self.root.update_idletasks()
        self.details = DetailWindow(self)

        self.canvas.bind("<Button-3>", self._on_menu)
        self.canvas.bind("<Configure>", lambda e: self.redraw(force=True))
        self.canvas.bind("<Double-Button-1>", lambda e: self.collapsed and self._set_collapsed(False))
        self.root.bind("<Escape>", lambda e: self.details.hide())

        self.menu = tk.Menu(self.root, tearoff=0, bg=PANEL, fg=TEXT, activebackground=PANEL_HI,
                            activeforeground=TEXT, bd=0)
        op = tk.Menu(self.menu, tearoff=0, bg=PANEL, fg=TEXT, activebackground=PANEL_HI)
        for pct in (100, 94, 85, 75, 60, 45):
            op.add_command(label=f"%{pct}", command=lambda p=pct: self._set_alpha(p / 100))
        self.menu.add_cascade(label="Saydamlık", menu=op)
        self.topmost = tk.BooleanVar(value=True)
        self.menu.add_checkbutton(label="Her zaman üstte", variable=self.topmost, command=self._set_topmost)
        self.menu.add_separator()
        self.menu.add_command(label="Sadece bu savaşı bitir", command=self._end_fight)
        self.menu.add_command(label="Sıfırla (tüm savaşları sil)", command=self._reset)
        self.menu.add_separator()
        self.menu.add_command(label="Kapat", command=self.root.destroy)
        self.root.bind("<Destroy>", self._save_settings, add="+")

        self.root.after(100, self._tick)

    # ───────── shared helpers ─────────

    def photo(self, url, size):
        key = (url, size)
        ph = self.photos.get(key)
        if ph is not None:
            return ph
        path = self.icons.get(url, size)
        if path is None:
            return None
        try:
            ph = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
        self.photos[key] = ph
        return ph

    def _save_settings(self, e=None):
        if e is not None and e.widget is not self.root:
            return
        try:
            geo = self.root.geometry()
            if self.collapsed and self._full_height:
                # keep the unfolded size, so the window can open back to it
                size, _, pos = geo.partition("+")
                geo = f"{size.split('x')[0]}x{self._full_height}+{pos}"
            data = {"geometry": geo, "alpha": self.alpha, "tab": self.tab, "mode": self.mode,
                    "detail_geometry": self.details.geometry(), "collapsed": self.collapsed,
                    "full_height": self._full_height}
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except (OSError, tk.TclError):
            pass

    def _set_alpha(self, a):
        self.alpha = a
        self.root.attributes("-alpha", a)

    def _set_collapsed(self, on):
        """Fold the window into its header strip, or open it back to its last size."""
        if on == self.collapsed:
            return
        self.root.update_idletasks()
        w, h = self.root.winfo_width(), self.root.winfo_height()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if on:
            self._full_height = h
            self.collapsed = True
            self.root.minsize(self.s(MIN_W), self.s(STRIP_H))
            self.root.geometry(f"{w}x{self.s(STRIP_H)}+{x}+{y}")
        else:
            self.collapsed = False
            self.root.minsize(self.s(MIN_W), self.s(MIN_H))
            self.root.geometry(f"{w}x{max(self._full_height or 0, self.s(MIN_H))}+{x}+{y}")
        self.scroll = 0
        self.redraw(force=True)

    def _set_topmost(self):
        on = self.topmost.get()
        self.root.attributes("-topmost", on)
        self.details.win.attributes("-topmost", on)

    # ───────── state ─────────

    def _current_encounter(self):
        encs = self.store.encounters()
        if not encs:
            return None, encs
        if self.pinned is not None:
            for e in encs:
                if e.id == self.pinned:
                    return e, encs
            self.pinned = None
        return encs[0], encs

    def _end_fight(self):
        self.store.reset()
        self.pinned = None
        self.redraw(force=True)

    def _reset(self):
        self.store.clear_history()
        self.pinned = None
        self.scroll = 0
        self.redraw(force=True)

    def _toggle_pause(self):
        self.store.set_paused(not self.store.paused)
        self.pinned = None
        self.redraw(force=True)

    def _set_tab(self, tab):
        self.tab = tab
        self.scroll = 0
        self.redraw(force=True)

    def _set_mode(self, mode):
        self.mode = mode
        self.redraw(force=True)

    def _step(self, encs, cur, delta):
        ids = [e.id for e in encs]
        i = ids.index(cur.id) + delta
        if 0 <= i < len(ids):
            self.pinned = None if i == 0 else ids[i]
            self.scroll = 0
            self.redraw(force=True)

    def _on_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    # ───────── loop ─────────

    def _tick(self):
        try:
            self.redraw()
        finally:
            self.root.after(REFRESH_MS, self._tick)

    def redraw(self, force=False):
        st = self.dispatcher.status()
        sig = (self.store.generation, st["locked"], self.tab, self.mode, self.pinned, self.scroll,
               self.icons.done, self.store.local_identity(), self.store.paused, self.collapsed,
               int(st.get("silent_ms", 0) > 10_000))
        if not force and sig == self._last_sig:
            return
        self._last_sig = sig
        self.canvas.delete("all")
        self.hits = []
        self.enc, encs = self._current_encounter()
        self.view = build_view(self.store.view(self.enc), self.mode) if self.enc is not None else None
        if self.collapsed:
            self._draw_strip(st)
        else:
            self._draw(st, encs)
        self.details.redraw(force=True)

    def _draw_strip(self, st):
        """The folded window: one line with your DPS, the party's and the fight time."""
        c = self.canvas
        s = self.s
        W, H = c.winfo_width(), c.winfo_height()
        if W < 10:
            return
        pad = s(10)
        c.create_rectangle(0, 0, W, H, fill=PANEL, outline="")
        c.create_text(pad, H / 2, text="AION2", anchor="w", font=self.f_title, fill=ACCENT)
        x = W - s(8)
        for label, cb in (("✕", self.root.destroy), ("+", lambda: self._set_collapsed(False))):
            bw = s(22)
            self._button(x - bw, s(7), x, s(27), label, False, cb, self.f_glyph)
            x -= bw + s(4)
        view = self.view
        if self.store.paused:
            dot, text = WARN, "durduruldu"
        elif not st["locked"]:
            dot, text = WARN, "oyun bağlantısı aranıyor"
        elif view is None:
            dot, text = FAINT, "savaş bekleniyor"
        else:
            rows = visible_rows(view, "party")
            mine = next((r for r in rows if r["is_local"]), None)
            parts = []
            if mine:
                parts.append(f"sen {fmt_num(mine['dps'])}")
            if len(rows) > 1 or not mine:
                label = "parti" if view["party_known"] else "toplam"
                parts.append(f"{label} {fmt_num(sum(r['dps'] for r in rows))}")
            parts.append(fmt_time(view["duration_ms"]))
            live = self.enc.frozen is None
            dot, text = (LIVE if live else FAINT), "  ·  ".join(parts)
        tx = pad + self.f_title.measure("AION2") + s(12)
        c.create_oval(tx, H / 2 - s(3), tx + s(7), H / 2 + s(4), fill=dot, outline="")
        c.create_text(tx + s(13), H / 2, text=self._ellipsize(text, self.f_num_b, x - tx - s(20)), anchor="w",
                      font=self.f_num_b, fill=TEXT)

    # ───────── drawing ─────────

    def _draw(self, st, encs):
        c = self.canvas
        s = self.s
        W, H = c.winfo_width(), c.winfo_height()
        if W < 10:
            return
        pad = s(10)
        enc, view = self.enc, self.view
        top = s(68) + (s(22) if view is not None else 0) + (s(8) if view and view["hp"] else 0)
        bottom = H - s(22)
        self._ctop, self._cbot = top, bottom

        # content first, so the chrome drawn afterwards covers whatever scrolls under it
        self._content = True
        y0 = top + s(6) - self.scroll
        if view is None:
            if self.store.paused:
                self._empty(top, bottom, W, "Durduruldu", "Saymaya devam etmek için Başlat'a bas.")
            else:
                self._empty(top, bottom, W, "Savaş bekleniyor…",
                            "Bir moba vurduğunda hasar burada görünür." if st["locked"]
                            else "Oyun bağlantısı aranıyor (oyunda hareket etmen yeterli).")
            end_y = top
        elif self.tab == "me":
            end_y = self._draw_me(view, y0, W, top, bottom)
        else:
            end_y = self._draw_party(view, y0, W, top, bottom)
        self._content = False
        self._clamp_scroll(end_y, top, bottom)

        # header (drag area)
        c.create_rectangle(0, 0, W, top, fill=BG, outline="")
        c.create_rectangle(0, 0, W, s(34), fill=PANEL, outline="")
        c.create_text(pad, s(17), text="AION2", anchor="w", font=self.f_title, fill=ACCENT)
        c.create_text(pad + self.f_title.measure("AION2 "), s(17), text="DPS", anchor="w",
                      font=self.f_title, fill=TEXT)
        tx = pad + self.f_title.measure("AION2 DPS") + s(10)
        self._button(tx, s(7), tx + s(44), s(27), "Ben", self.tab == "me", lambda: self._set_tab("me"),
                     self.f_tab)
        self._button(tx + s(48), s(7), tx + s(98), s(27), "Parti", self.tab == "party",
                     lambda: self._set_tab("party"), self.f_tab)
        x = W - s(8)
        paused = self.store.paused
        for label, active, cb, font, fg in (
                ("✕", False, self.root.destroy, self.f_glyph, None),
                ("–", False, lambda: self._set_collapsed(True), self.f_glyph, None),
                ("Sıfırla", False, self._reset, self.f_tab, None),
                ("▶ Başlat" if paused else "❚❚ Durdur", paused, self._toggle_pause, self.f_tab,
                 ACCENT if paused else None)):
            bw = max(s(22), font.measure(label) + s(14))
            self._button(x - bw, s(7), x, s(27), label, active, cb, font, fg=fg)
            x -= bw + s(4)

        # mode + history bar
        y = s(40)
        half = s(92)
        self._button(pad, y, pad + half, y + s(20), "Tüm hedefler", self.mode == MODE_ALL,
                     lambda: self._set_mode(MODE_ALL), self.f_small)
        self._button(pad + half + s(4), y, pad + 2 * half + s(4), y + s(20), "Ana hedef",
                     self.mode == MODE_TARGET, lambda: self._set_mode(MODE_TARGET), self.f_small)
        if enc is not None and len(encs) > 1:
            i = [e.id for e in encs].index(enc.id)
            c.create_text(W - pad - s(33), y + s(10), text=f"{len(encs) - i}/{len(encs)}",
                          font=self.f_small, fill=MUTED)
            if i < len(encs) - 1:
                self._button(W - pad - s(66), y, W - pad - s(48), y + s(20), "‹", False,
                             lambda: self._step(encs, enc, 1), self.f_bold)
            if i > 0:
                self._button(W - pad - s(18), y, W - pad, y + s(20), "›", False,
                             lambda: self._step(encs, enc, -1), self.f_bold)

        # encounter line
        if view is not None:
            ly = s(68)
            live = enc.frozen is None
            c.create_oval(pad, ly + s(5), pad + s(7), ly + s(12), fill=LIVE if live else FAINT, outline="")
            state = "canlı" if live else END_REASONS.get(view["end_reason"], "bitti")
            right = f"{fmt_time(view['duration_ms'])} · {state}"
            if view["hp"] and view["hp"][0] > 0:
                right = f"HP {fmt_pct(view['hp'][0] / view['hp'][1] * 100)} · " + right
            rw = self.f_small.measure(right)
            c.create_text(W - pad, ly + s(8), text=right, anchor="e", font=self.f_small, fill=MUTED)
            title = self._ellipsize(view["title"], self.f_bold, W - 2 * pad - rw - s(20))
            c.create_text(pad + s(12), ly + s(8), text=title, anchor="w", font=self.f_bold, fill=TEXT)
            if view["hp"]:
                cur, mx = view["hp"]
                by = ly + s(19)
                c.create_rectangle(pad, by, W - pad, by + s(5), fill=PANEL_HI, outline="")
                c.create_rectangle(pad, by, pad + (W - 2 * pad) * cur / mx, by + s(5), fill=BAD, outline="")
        c.create_line(0, top, W, top, fill=LINE)
        self._footer(st, W, H, bottom)

    def _empty(self, top, bottom, W, title, sub):
        c = self.canvas
        mid = (top + bottom) / 2
        c.create_text(W / 2, mid - self.s(10), text=title, font=self.f_bold, fill=TEXT)
        c.create_text(W / 2, mid + self.s(10), text=sub, font=self.f_small, fill=MUTED,
                      width=W - self.s(40), justify="center")

    def _footer(self, st, W, H, bottom):
        c = self.canvas
        s = self.s
        c.create_rectangle(0, bottom, W, H, fill=PANEL, outline="")
        if self.store.paused:
            color, text = WARN, "durduruldu · hasar sayılmıyor"
        elif not st["locked"]:
            color, text = WARN, "oyun bağlantısı aranıyor…"
        elif st.get("silent_ms", 0) > 10_000:
            color, text = WARN, "bağlantı sessiz (yükleme ekranı?)"
        else:
            color, text = LIVE, "bağlı"
        if st.get("dropped"):
            color, text = BAD, f"{text} · {st['dropped']} paket kaçırıldı"
        c.create_oval(s(10), bottom + s(8), s(16), bottom + s(14), fill=color, outline="")
        c.create_text(s(21), bottom + s(11), text=text, anchor="w", font=self.f_small, fill=MUTED)
        lid, lname = self.store.local_identity()
        if lid is None:
            who = "sen: vurmaya başlayınca tanınır"
        else:
            who = f"sen: {lname or f'#{lid}'}"
            if self.store.local_is_guess():
                who += " (tahmini)"
        c.create_text(W - s(20), bottom + s(11), text=who, anchor="e", font=self.f_small, fill=MUTED)
        self._grip(W, H)

    # party list ---------------------------------------------------------

    def _draw_party(self, view, y, W, top, bottom):
        c = self.canvas
        s = self.s
        pad = s(10)
        rows = visible_rows(view, "party")
        notes = []
        if not view["party_known"] and rows:
            notes.append("Partide değilsin · etraftaki tüm oyuncular")
        if any(r["name"].startswith("#") for r in rows):
            notes.append("#numara: meter açılmadan önce yanındaydı, adı görüş alanına girince gelir")
        for note in notes:
            c.create_text(pad, y + s(7), text=self._ellipsize(note, self.f_small, W - 2 * pad),
                          anchor="w", font=self.f_small, fill=FAINT)
            y += s(16)
        if notes:
            y += s(2)
        if not rows:
            self._empty(top, bottom, W, "Henüz oyuncu hasarı yok", "")
            return y
        total = sum(r["total"] for r in rows)
        total_dps = sum(r["dps"] for r in rows)
        c.create_text(pad, y + s(8), text="Parti toplam · ayrıntı için oyuncuya tıkla", anchor="w",
                      font=self.f_small, fill=MUTED)
        c.create_text(W - pad, y + s(8), text=f"{fmt_num(total_dps)}/sn · {fmt_num(total)}",
                      anchor="e", font=self.f_small, fill=MUTED)
        y += s(20)
        best = rows[0]["total"] or 1
        rh = s(38)
        for i, r in enumerate(rows):
            if y + rh >= top and y <= bottom:
                self._party_row(r, i + 1, y, W, rh, best)
            y += rh + s(3)
        return y

    def _party_row(self, r, rank, y, W, rh, best):
        c = self.canvas
        s = self.s
        pad = s(8)
        color = CLASS_COLORS.get(r["job"], NO_CLASS)
        x0, x1 = pad, W - pad
        selected = self.details.visible and self.details.key == r["key"]
        c.create_rectangle(x0, y, x1, y + rh, fill=PANEL,
                           outline=ACCENT if r["is_local"] else (color if selected else ""))
        c.create_rectangle(x0, y, x0 + (x1 - x0) * (r["total"] / best), y + rh,
                           fill=_blend(PANEL, color, 0.28), outline="")
        c.create_rectangle(x0, y, x0 + s(3), y + rh, fill=color, outline="")
        name = r["name"] + ("  (sen)" if r["is_local"] else "")
        dps = fmt_num(r["dps"])
        dps_w = self.f_num_b.measure(dps)
        c.create_text(x1 - s(8), y + s(12), text=dps, anchor="e", font=self.f_num_b, fill=TEXT)
        c.create_text(x0 + s(12), y + s(12),
                      text=self._ellipsize(f"{rank}. {name}", self.f_bold, x1 - x0 - dps_w - s(40)),
                      anchor="w", font=self.f_bold, fill=TEXT)
        c.create_text(x0 + s(12), y + s(27), text=CLASSES.get(r["job"], "?"), anchor="w",
                      font=self.f_small, fill=color)
        c.create_text(x1 - s(8), y + s(27),
                      text=f"{fmt_num(r['total'])} · {fmt_pct(r['pct'])} · krit {fmt_pct(r['crit_rate'] * 100, 0)}",
                      anchor="e", font=self.f_small, fill=MUTED)
        key = r["key"]
        self._hit(x0, y, x1, y + rh, lambda: self.details.show(key))

    # me tab -------------------------------------------------------------------

    def _draw_me(self, view, y, W, top, bottom):
        mine = [r for r in view["rows"].values() if r["is_local"]]
        if not mine:
            lid, _ = self.store.local_identity()
            if lid is None:
                self._empty(top, bottom, W, "Karakterin henüz tanınmadı",
                            "Birkaç saniye vurunca tanınırsın. Teleport ya da zindan girişi de "
                            "oyunun karakter kaydını göndermesini sağlar.")
            else:
                self._empty(top, bottom, W, "Bu savaşta hasarın yok", "Bir hedefe vurduğunda burada görünür.")
            return y
        r = mine[0]
        c = self.canvas
        s = self.s
        pad = s(10)
        color = CLASS_COLORS.get(r["job"], NO_CLASS)

        ch = s(78)
        c.create_rectangle(pad, y, W - pad, y + ch, fill=PANEL, outline="")
        c.create_rectangle(pad, y, pad + s(3), y + ch, fill=color, outline="")
        c.create_text(pad + s(12), y + s(14), text=self._ellipsize(r["name"], self.f_bold, W / 2),
                      anchor="w", font=self.f_bold, fill=TEXT)
        c.create_text(pad + s(12), y + s(30), text=CLASSES.get(r["job"], "?"), anchor="w",
                      font=self.f_small, fill=color)
        c.create_text(W - pad - s(10), y + s(22), text=fmt_num(r["dps"]), anchor="e", font=self.f_big, fill=TEXT)
        c.create_text(W - pad - s(10), y + s(44), text="DPS", anchor="e", font=self.f_small, fill=MUTED)
        stats = (f"Toplam {fmt_full(r['total'])}  ·  Krit {fmt_pct(r['crit_rate'] * 100)}"
                 f"  ·  Parti payı {fmt_pct(party_share(view, r))}")
        c.create_text(pad + s(12), y + s(62), text=self._ellipsize(stats, self.f_small, W - 2 * pad - s(110)),
                      anchor="w", font=self.f_small, fill=MUTED)
        key = r["key"]
        self._button(W - pad - s(96), y + ch - s(26), W - pad - s(8), y + ch - s(6), "Ayrıntılar ↗",
                     False, lambda: self.details.show(key), self.f_small)
        y += ch + s(10)

        skills = skill_rows(r, self.gd, r["seconds"])
        best = skills[0]["total"] if skills else 1
        rh = s(44)
        for sk in skills:
            if y + rh >= top and y <= bottom:
                self._skill_row(sk, y, W, rh, best, color)
            y += rh + s(2)
        return y

    def _skill_row(self, sk, y, W, rh, best, color):
        c = self.canvas
        s = self.s
        pad = s(10)
        isz = s(32)
        c.create_rectangle(pad, y, W - pad, y + rh, fill=PANEL, outline="")
        ix, iy = pad + s(6), y + (rh - isz) // 2
        kind, url = sk["icon"]
        self._icon(self, kind, url, ix, iy, isz, self.f_glyph)
        tx = ix + isz + s(8)
        right = W - pad - s(8)
        val = fmt_num(sk["total"])
        pct = fmt_pct(sk["pct"])
        vw = self.f_num_b.measure(val)
        c.create_text(right, y + s(13), text=val, anchor="e", font=self.f_num_b, fill=TEXT)
        c.create_text(tx, y + s(13), text=self._ellipsize(sk["name"], self.f_bold, right - tx - vw - s(10)),
                      anchor="w", font=self.f_bold, fill=DOT if sk["is_dot"] else TEXT)
        parts = [f"x{sk['hits']}"]
        if not sk["is_dot"]:
            parts.append(f"krit {fmt_pct(sk['crit'], 0)}")
            if sk["back"]:
                parts.append(f"arka {fmt_pct(sk['back'], 0)}")
        parts.append(f"maks {fmt_num(sk['max'])}")
        pw = self.f_small.measure(pct)
        c.create_text(right, y + s(29), text=pct, anchor="e", font=self.f_small, fill=MUTED)
        c.create_text(tx, y + s(29), text=self._ellipsize(" · ".join(parts), self.f_small, right - tx - pw - s(10)),
                      anchor="w", font=self.f_small, fill=MUTED)
        c.create_rectangle(tx, y + rh - s(5), tx + (right - tx) * (sk["total"] / best if best else 0),
                           y + rh - s(3), fill=color, outline="")

    def run(self):
        self.root.mainloop()


# ═════════════════════════ details window ═════════════════════════

class DetailWindow(_Surface):
    """Everything about one player in the selected fight: summary, targets, a full skill table."""

    drag_height = 40

    def __init__(self, app):
        self.app = app
        win = tk.Toplevel(app.root)
        win.withdraw()
        win.title("AION2 DPS - Ayrıntılar")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 1.0)  # a reading window: nothing should show through
        win.configure(bg=BG)
        self._init_surface(win, app.k)
        geo = app.settings.get("detail_geometry")
        if not geo:
            w, h = self.s(640), self.s(760)
            x = max(0, app.root.winfo_x() - w - self.s(12))
            geo = f"{w}x{h}+{x}+{max(0, app.root.winfo_y())}"
        win.geometry(geo)
        win.minsize(self.s(460), self.s(320))
        self._geo = geo
        self.key = None
        self.expanded = set()
        self.visible = False
        self.canvas.bind("<Configure>", self._on_configure)
        win.bind("<Escape>", lambda e: self.hide())

    def _on_configure(self, _e):
        if self.visible:
            try:
                self._geo = self.win.geometry()
            except tk.TclError:
                pass
        self.redraw(force=True)

    def geometry(self):
        return self._geo

    def show(self, key):
        if self.key != key:
            self.expanded.clear()
            self.scroll = 0
        self.key = key
        self.visible = True
        self.win.deiconify()
        self.win.lift()
        self.app.redraw(force=True)

    def hide(self):
        self.visible = False
        self.win.withdraw()
        self.app.redraw(force=True)

    def _select(self, key):
        self.key = key
        self.expanded.clear()
        self.scroll = 0
        self.redraw(force=True)
        self.app.redraw(force=True)

    def _toggle(self, skill_key):
        if skill_key in self.expanded:
            self.expanded.discard(skill_key)
        else:
            self.expanded.add(skill_key)
        self.redraw(force=True)

    def redraw(self, force=False):
        if not self.visible:
            return
        self.canvas.delete("all")
        self.hits = []
        self._draw()

    # ───────── drawing ─────────

    def _draw(self):
        a = self.app
        c = self.canvas
        s = self.s
        W, H = c.winfo_width(), c.winfo_height()
        if W < 10:
            return
        pad = s(14)
        view = a.view
        rows = visible_rows(view, "party") if view else []
        row = view["rows"].get(self.key) if view else None

        # chips (one per player), laid out first so the content knows where it starts
        chips = []
        x, y = pad, s(48)
        ch = s(26)
        for r in rows:
            label = r["name"] + (" (sen)" if r["is_local"] else "")
            w = a.fd_bold.measure(label) + s(26)
            if x + w > W - pad and x > pad:
                x = pad
                y += ch + s(6)
            chips.append((r, x, y, w))
            x += w + s(6)
        top = (y + ch + s(10)) if chips else s(52)
        bottom = H - s(8)
        self._ctop, self._cbot = top, bottom

        self._content = True
        cy = top + s(8) - self.scroll
        if view is None:
            c.create_text(W / 2, (top + bottom) / 2, text="Savaş bekleniyor…", font=a.fd_head, fill=MUTED)
            end = top
        elif row is None:
            c.create_text(W / 2, (top + bottom) / 2, text="Bu savaşta bu oyuncunun hasarı yok",
                          font=a.fd_head, fill=MUTED)
            end = top
        else:
            end = self._draw_player(view, row, cy, W, top, bottom, pad)
        self._content = False
        self._clamp_scroll(end, top, bottom)

        # chrome
        c.create_rectangle(0, 0, W, top, fill=BG, outline="")
        c.create_rectangle(0, 0, W, s(40), fill=PANEL, outline="")
        c.create_text(pad, s(20), text="Ayrıntılar", anchor="w", font=a.fd_head, fill=ACCENT)
        if view is not None:
            live = a.enc.frozen is None
            state = "canlı" if live else END_REASONS.get(view["end_reason"], "bitti")
            info = f"{view['title']}  ·  {fmt_time(view['duration_ms'])}  ·  {state}"
            info += "  ·  " + ("tüm hedefler" if a.mode == MODE_ALL else "ana hedef")
            lx = pad + a.fd_head.measure("Ayrıntılar") + s(14)
            c.create_text(lx, s(20), text=self._ellipsize(info, a.fd_small, W - lx - s(50)), anchor="w",
                          font=a.fd_small, fill=MUTED)
        self._button(W - s(34), s(9), W - s(10), s(31), "✕", False, self.hide, a.fd_glyph)
        for r, x, y, w in chips:
            color = CLASS_COLORS.get(r["job"], NO_CLASS)
            sel = r["key"] == self.key
            label = r["name"] + (" (sen)" if r["is_local"] else "")
            c.create_rectangle(x, y, x + w, y + ch, fill=PANEL_HI if sel else PANEL,
                               outline=color if sel else LINE, width=2 if sel else 1)
            c.create_rectangle(x, y, x + s(4), y + ch, fill=color, outline="")
            c.create_text(x + s(14), y + ch / 2, text=label, anchor="w", font=a.fd_bold,
                          fill=TEXT if sel else MUTED)
            key = r["key"]
            self._hit(x, y, x + w, y + ch, lambda k=key: self._select(k))
        c.create_line(0, top, W, top, fill=LINE)
        self._grip(W, H)

    def _draw_player(self, view, r, y, W, top, bottom, pad):
        a = self.app
        c = self.canvas
        s = self.s
        color = CLASS_COLORS.get(r["job"], NO_CLASS)
        summ = row_summary(r, a.gd)

        # summary card
        card_h = s(168)
        c.create_rectangle(pad, y, W - pad, y + card_h, fill=PANEL, outline="")
        c.create_rectangle(pad, y, pad + s(4), y + card_h, fill=color, outline="")
        c.create_text(pad + s(18), y + s(22), text=self._ellipsize(r["name"], a.fd_title, W / 2),
                      anchor="w", font=a.fd_title, fill=TEXT)
        sub = CLASSES.get(r["job"], "?")
        if r.get("level"):
            sub += f"  ·  Seviye {r['level']}"
        if r.get("combat_power"):
            sub += f"  ·  Savaş gücü {fmt_full(r['combat_power'])}"
        if r["is_local"]:
            sub += "  ·  sen"
        c.create_text(pad + s(18), y + s(44), text=sub, anchor="w", font=a.fd_small, fill=color)
        c.create_text(W - pad - s(16), y + s(30), text=fmt_num(r["dps"]), anchor="e", font=a.fd_big, fill=TEXT)
        if view["shared_time"]:
            basis = f"parti savaş süresiyle · kendi süresiyle {fmt_num(r['dps_own'])}"
        else:
            basis = f"kendi vuruş süresiyle · savaş süresiyle {fmt_num(r['dps_fight'])}"
        c.create_text(W - pad - s(16), y + s(58), text=basis, anchor="e", font=a.fd_small, fill=MUTED)

        cells = [
            ("Toplam hasar", fmt_full(r["total"])),
            ("Süre (kendi / savaş)", f"{fmt_time(r['active_ms'])} / {fmt_time(view['duration_ms'])}"),
            ("Vuruş", f"{summ['direct_hits']}" + (f" + {summ['dot_ticks']} DoT" if summ["dot_ticks"] else "")),
            ("Parti payı", fmt_pct(party_share(view, r))),
            ("Kritik", fmt_pct(summ["crit"])),
            ("Arkadan", fmt_pct(summ["back"])),
            ("Mükemmel / Çift", f"{fmt_pct(summ['perfect'])} / {fmt_pct(summ['double'])}"),
            ("En büyük vuruş", fmt_full(summ["max_hit"])),
        ]
        gx0, gw = pad + s(18), (W - 2 * pad - s(36)) / 4
        for i, (label, value) in enumerate(cells):
            cx = gx0 + (i % 4) * gw
            cy = y + s(80) + (i // 4) * s(44)
            c.create_text(cx, cy, text=label, anchor="w", font=a.fd_small, fill=FAINT)
            c.create_text(cx, cy + s(19), text=self._ellipsize(value, a.fd_num_b, gw - s(8)), anchor="w",
                          font=a.fd_num_b, fill=TEXT)
        if summ["max_hit_skill"]:
            c.create_text(W - pad - s(16), y + card_h - s(10),
                          text=self._ellipsize(f"en büyük vuruş: {summ['max_hit_skill']}", a.fd_small, gw * 2),
                          anchor="e", font=a.fd_small, fill=MUTED)
        y += card_h + s(14)

        # damage by target
        targets = summ["targets"]
        if targets:
            c.create_text(pad, y + s(8), text="Hedeflere göre", anchor="w", font=a.fd_bold, fill=MUTED)
            y += s(22)
            best_t = targets[0][1] or 1
            for (tname, is_boss), dmg in targets[:6]:
                c.create_rectangle(pad, y, W - pad, y + s(24), fill=PANEL, outline="")
                c.create_rectangle(pad, y, pad + (W - 2 * pad) * dmg / best_t, y + s(24),
                                   fill=_blend(PANEL, BAD if is_boss else color, 0.22), outline="")
                label = ("★ " if is_boss else "") + tname
                right = f"{fmt_full(dmg)}   {fmt_pct(dmg / (r['total'] or 1) * 100)}"
                c.create_text(W - pad - s(10), y + s(12), text=right, anchor="e", font=a.fd_num, fill=TEXT)
                c.create_text(pad + s(10), y + s(12),
                              text=self._ellipsize(label, a.fd_body, W - 2 * pad - a.fd_num.measure(right) - s(30)),
                              anchor="w", font=a.fd_body, fill=TEXT)
                y += s(27)
            if len(targets) > 6:
                c.create_text(pad, y + s(6), text=f"+{len(targets) - 6} hedef daha", anchor="w",
                              font=a.fd_small, fill=FAINT)
                y += s(16)
            y += s(10)

        # skill table
        skills = skill_rows(r, a.gd, r["seconds"])
        cols = self._columns(W, pad)
        c.create_text(pad, y + s(8), text=f"Skill'ler ({len(skills)})  ·  ayrıntı için skill'e tıkla",
                      anchor="w", font=a.fd_bold, fill=MUTED)
        y += s(24)
        c.create_rectangle(pad, y, W - pad, y + s(22), fill=PANEL_HI, outline="")
        for label, _, x_right, _ in cols:
            c.create_text(x_right, y + s(11), text=label, anchor="e", font=a.fd_small, fill=MUTED)
        c.create_text(pad + s(54), y + s(11), text="Skill", anchor="w", font=a.fd_small, fill=MUTED)
        y += s(26)
        best = skills[0]["total"] if skills else 1
        for sk in skills:
            y = self._skill(sk, y, W, pad, cols, best, color, top, bottom)
        return y + s(10)

    def _columns(self, W, pad):
        s = self.s
        spec = [  # label, field, width, formatter
            ("Hasar", "total", 84, fmt_full),
            ("Pay", "pct", 56, fmt_pct),
            ("DPS", "dps", 64, fmt_num),
            ("Vuruş", "hits", 50, str),
            ("Ort.", "avg", 64, fmt_num),
            ("Maks", "max", 66, fmt_num),
            ("Krit", "crit", 50, lambda v: fmt_pct(v, 0)),
            ("Arka", "back", 50, lambda v: fmt_pct(v, 0)),
        ]
        name_min = s(170)
        avail = W - 2 * pad - s(54) - name_min
        for drop in ("back", "avg", "dps", "max"):
            if sum(s(w) for _, _, w, _ in spec) <= avail:
                break
            spec = [c for c in spec if c[1] != drop]
        cols = []
        x = W - pad - s(10)
        for label, field, w, fmt in reversed(spec):
            cols.append((label, field, x, fmt))
            x -= s(w)
        cols.reverse()
        self._name_right = x
        return cols

    def _skill(self, sk, y, W, pad, cols, best, color, top, bottom):
        a = self.app
        c = self.canvas
        s = self.s
        rh = s(52)
        open_ = sk["key"] in self.expanded
        items = self._skill_items(sk) if open_ else []
        ext = (math.ceil(len(items) / 4) * s(40) + s(12)) if open_ else 0
        if y + rh + ext >= top and y <= bottom:
            c.create_rectangle(pad, y, W - pad, y + rh + ext, fill=PANEL, outline=color if open_ else "")
            isz = s(38)
            ix, iy = pad + s(8), y + (rh - isz) // 2
            kind, url = sk["icon"]
            self._icon(a, kind, url, ix, iy, isz, a.fd_glyph)
            tx = ix + isz + s(10)
            name_w = self._name_right - tx - s(8)
            c.create_text(tx, y + s(17), text=self._ellipsize(sk["name"], a.fd_bold, name_w), anchor="w",
                          font=a.fd_bold, fill=DOT if sk["is_dot"] else TEXT)
            c.create_text(tx, y + s(35), text=self._ellipsize(self._subline(sk), a.fd_small, name_w), anchor="w",
                          font=a.fd_small, fill=MUTED)
            for _, field, x_right, fmt in cols:
                f = a.fd_num_b if field == "total" else a.fd_num
                c.create_text(x_right, y + s(26), text=fmt(sk[field]), anchor="e", font=f,
                              fill=TEXT if field in ("total", "dps") else MUTED)
            c.create_rectangle(tx, y + rh - s(6), tx + (W - pad - s(10) - tx) * (sk["total"] / best if best else 0),
                               y + rh - s(3), fill=color, outline="")
            if open_:
                gx0 = pad + s(16)
                gw = (W - 2 * pad - s(32)) / 4
                c.create_rectangle(pad + s(8), y + rh, W - pad - s(8), y + rh + ext - s(6), fill=PANEL_HI,
                                   outline="")
                for i, (label, value) in enumerate(items):
                    cx = gx0 + (i % 4) * gw
                    cy = y + rh + s(14) + (i // 4) * s(40)
                    c.create_text(cx, cy, text=label, anchor="w", font=a.fd_small, fill=FAINT)
                    c.create_text(cx, cy + s(17), text=self._ellipsize(value, a.fd_num_b, gw - s(8)), anchor="w",
                                  font=a.fd_num_b, fill=TEXT)
        key = sk["key"]
        self._hit(pad, y, W - pad, y + rh + ext, lambda: self._toggle(key))
        return y + rh + ext + s(4)

    @staticmethod
    def _subline(sk):
        if sk["is_dot"]:
            return f"zamanla hasar · {sk['hits']} tik · tik başı {fmt_num(sk['avg'])}"
        parts = []
        for field, label in (("perfect", "mükemmel"), ("double", "çift"), ("front", "önden"), ("parry", "sıyrık")):
            if sk[field + "_n"]:
                parts.append(f"{label} {fmt_pct(sk[field], 0)}")
        if sk["mh_hits"]:
            parts.append(f"çoklu vuruş +{sk['mh_hits']}")
        parts.append(f"en düşük {fmt_num(sk['min'])}")
        return " · ".join(parts)

    @staticmethod
    def _skill_items(sk):
        def tag(field):
            return f"{sk[field + '_n']}  ({fmt_pct(sk[field], 0)})"
        items = [
            ("Vuruş sayısı" if not sk["is_dot"] else "Tik sayısı", str(sk["hits"])),
            ("Toplam hasar", fmt_full(sk["total"])),
            ("Saniyede hasar", fmt_full(sk["dps"])),
            ("Hasar payı", fmt_pct(sk["pct"])),
            ("Ortalama", fmt_full(sk["avg"])),
            ("En düşük", fmt_full(sk["min"])),
            ("En yüksek", fmt_full(sk["max"])),
        ]
        if sk["is_dot"]:
            return items
        items.append(("Çoklu vuruş", f"+{sk['mh_hits']} vuruş · {fmt_num(sk['mh_damage'])}" if sk["mh_hits"] else "-"))
        items += [("Kritik", tag("crit")), ("Arkadan", tag("back")), ("Önden", tag("front")),
                  ("Mükemmel", tag("perfect")), ("Çift vuruş", tag("double")), ("Sıyrık (parry)", tag("parry"))]
        if sk["smite_n"]:
            items.append(("Smite", tag("smite")))
        if sk["powershard_n"]:
            items.append(("Güç kristali", tag("powershard")))
        return items


def run_ui(store, dispatcher, gamedata, tab=None):
    ui = MeterUI(store, dispatcher, gamedata)
    ui.tab = tab or ui.settings.get("tab", "party")
    if ui.settings.get("mode") in (MODE_ALL, MODE_TARGET):
        ui.mode = ui.settings["mode"]
    if ui.settings.get("collapsed"):
        ui.root.after(50, lambda: ui._set_collapsed(True))
    ui.run()
