"""Small Win32 helpers: global hotkeys, the overlay's shape and click-through, one running copy."""
import ctypes
import ctypes.wintypes as W
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_LAYERED = 0x20, 0x80000
LWA_ALPHA = 0x2
ERROR_ALREADY_EXISTS = 183

_MODS = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL, "SHIFT": MOD_SHIFT, "ALT": MOD_ALT, "WIN": MOD_WIN}
_KEYS = {f"F{i}": 0x6F + i for i in range(1, 13)}
_KEYS.update({"HOME": 0x24, "END": 0x23, "INSERT": 0x2D, "DELETE": 0x2E, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
              "PAUSE": 0x13, "SCROLLLOCK": 0x91})

user32.RegisterHotKey.argtypes = [W.HWND, ctypes.c_int, W.UINT, W.UINT]
user32.UnregisterHotKey.argtypes = [W.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
user32.PostThreadMessageW.argtypes = [W.DWORD, W.UINT, W.WPARAM, W.LPARAM]
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.GetDpiForWindow.argtypes = [W.HWND]
user32.GetDpiForWindow.restype = W.UINT
user32.SetWindowRgn.argtypes = [W.HWND, W.HRGN, W.BOOL]
user32.SetLayeredWindowAttributes.argtypes = [W.HWND, W.COLORREF, W.BYTE, W.DWORD]
user32.FindWindowW.argtypes = [W.LPCWSTR, W.LPCWSTR]
user32.FindWindowW.restype = W.HWND
user32.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [W.HWND]
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateRoundRectRgn.restype = W.HRGN
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, W.BOOL, W.LPCWSTR]
kernel32.CreateMutexW.restype = W.HANDLE
if ctypes.sizeof(ctypes.c_void_p) == 8:
    _get_ex = user32.GetWindowLongPtrW
    _set_ex = user32.SetWindowLongPtrW
    _get_ex.restype = _set_ex.restype = ctypes.c_ssize_t
    _get_ex.argtypes = [W.HWND, ctypes.c_int]
    _set_ex.argtypes = [W.HWND, ctypes.c_int, ctypes.c_ssize_t]
else:
    _get_ex = user32.GetWindowLongW
    _set_ex = user32.SetWindowLongW


def parse_hotkey(text):
    """'Ctrl+Shift+R' -> (modifiers, virtual key), or None."""
    mods, vk = 0, None
    for part in (text or "").upper().replace(" ", "").split("+"):
        if part in _MODS:
            mods |= _MODS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part)
        elif part in _KEYS:
            vk = _KEYS[part]
        else:
            return None
    return (mods, vk) if vk is not None else None


class Hotkeys(threading.Thread):
    """Registers global hotkeys on its own thread and calls `on_key(name)` when one is pressed."""

    def __init__(self, bindings, on_key):
        super().__init__(name="hotkeys", daemon=True)
        self.bindings = dict(bindings)
        self.on_key = on_key
        self.failed = []
        self.tid = None
        self.ready = threading.Event()

    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        names = {}
        for i, (name, text) in enumerate(self.bindings.items(), 1):
            key = parse_hotkey(text)
            if key is None or not user32.RegisterHotKey(None, i, key[0] | MOD_NOREPEAT, key[1]):
                self.failed.append(name)
                continue
            names[i] = name
        self.ready.set()
        msg = W.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in names:
                try:
                    self.on_key(names[msg.wParam])
                except Exception:
                    pass
        for i in names:
            user32.UnregisterHotKey(None, i)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


def set_clickthrough(hwnd, on):
    """Mouse clicks pass through the window to the game underneath (it stays visible)."""
    if not hwnd:
        return False
    old = _get_ex(hwnd, GWL_EXSTYLE)
    ex = (old | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on else (old & ~WS_EX_TRANSPARENT)
    _set_ex(hwnd, GWL_EXSTYLE, ex)
    if on and not old & WS_EX_LAYERED:
        # a window made layered here (opacity 100%) shows nothing until it gets its alpha
        user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    return True


def round_corners(hwnd, radius):
    """Clip the window to a rounded rectangle (`radius` in CSS px). Clipping, unlike a colour key,
    keeps the whole panel clickable; it has to be redone after every resize."""
    if not hwnd:
        return False
    r = W.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return False
    dpi = user32.GetDpiForWindow(hwnd) or 96
    d = max(2, round(2 * radius * dpi / 96))
    rgn = gdi32.CreateRoundRectRgn(0, 0, r.right - r.left + 1, r.bottom - r.top + 1, d, d)
    return bool(rgn and user32.SetWindowRgn(hwnd, rgn, True))  # the window owns the region now


class SingleInstance:
    """A named mutex: False from `acquire` when the meter is already running."""

    def __init__(self, name):
        self.handle = kernel32.CreateMutexW(None, False, name)
        self.exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def acquire(self):
        return bool(self.handle) and not self.exists


def bring_to_front(title):
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)
