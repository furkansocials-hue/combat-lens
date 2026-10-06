"""Skill icons: fetched once from the game's CDN, shrunk with a box filter, cached on disk.

The CDN serves 256x256 PNGs; Tk can only point-sample (subsample), which looks
ragged at 32 px, so this does a proper area average in pure Python.
"""
import hashlib
import os
import queue
import struct
import threading
import urllib.request
import zlib

from .paths import user_path

CACHE_DIR = os.path.dirname(user_path("cache", "icons", "x"))
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(data):
    """-> (width, height, RGBA bytearray). 8-bit, non-interlaced PNGs only."""
    if data[:8] != _PNG_SIG:
        raise ValueError("not a PNG")
    pos = 8
    idat = []
    palette = trns = None
    w = h = depth = ctype = interlace = None
    while pos + 8 <= len(data):
        ln, = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif typ == b"PLTE":
            palette = body
        elif typ == b"tRNS":
            trns = body
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 3, 4, 6):
        raise ValueError("unsupported PNG")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    px = bytearray(h * stride)
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        if f == 1:
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                left = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                left = line[x - ch] if x >= ch else 0
                upleft = prev[x - ch] if x >= ch else 0
                line[x] = (line[x] + _paeth(left, prev[x], upleft)) & 255
        px[y * stride:(y + 1) * stride] = line
        prev = line

    if ctype == 6:
        return w, h, px
    out = bytearray(w * h * 4)
    for j in range(w * h):
        if ctype == 2:
            r, g, b = px[j * 3:j * 3 + 3]
            a = 255
        elif ctype == 0:
            r = g = b = px[j]
            a = 255
        elif ctype == 4:
            r = g = b = px[j * 2]
            a = px[j * 2 + 1]
        else:
            k = px[j]
            r, g, b = palette[k * 3:k * 3 + 3]
            a = trns[k] if trns and k < len(trns) else 255
        out[j * 4:j * 4 + 4] = bytes((r, g, b, a))
    return w, h, out


def downscale(w, h, rgba, size, radius=0):
    """Area-average to size x size (premultiplied), optionally with rounded corners."""
    out = bytearray(size * size * 4)
    for oy in range(size):
        y0, y1 = oy * h // size, max(oy * h // size + 1, (oy + 1) * h // size)
        for ox in range(size):
            x0, x1 = ox * w // size, max(ox * w // size + 1, (ox + 1) * w // size)
            r = g = b = a = 0
            for y in range(y0, y1):
                row = y * w * 4
                for x in range(x0, x1):
                    k = row + x * 4
                    al = rgba[k + 3]
                    r += rgba[k] * al
                    g += rgba[k + 1] * al
                    b += rgba[k + 2] * al
                    a += al
            n = (y1 - y0) * (x1 - x0)
            k = (oy * size + ox) * 4
            if a:
                out[k] = r // a
                out[k + 1] = g // a
                out[k + 2] = b // a
                out[k + 3] = a // n
    if radius:
        for oy in range(size):
            for ox in range(size):
                dx = max(radius - ox - 0.5, ox + 0.5 - (size - radius), 0)
                dy = max(radius - oy - 0.5, oy + 0.5 - (size - radius), 0)
                d = (dx * dx + dy * dy) ** 0.5
                if d > radius - 1:
                    cover = max(0.0, min(1.0, radius - d))
                    k = (oy * size + ox) * 4 + 3
                    out[k] = int(out[k] * cover)
    return out


def encode_png(w, h, rgba):
    def chunk(t, body):
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))
    return (_PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class IconCache:
    """get(url, size) -> local PNG path or None (queued for download)."""

    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.q = queue.Queue()
        self.pending = set()
        self.failed = set()
        self.done = 0  # finished downloads; the UI redraws when this moves
        self.lock = threading.Lock()
        threading.Thread(target=self._worker, daemon=True, name="icons").start()

    def _path(self, url, size):
        name = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        tag = hashlib.md5(url.encode()).hexdigest()[:6]
        return os.path.join(CACHE_DIR, f"{name}_{tag}_{size}.png")

    def get(self, url, size):
        path = self._path(url, size)
        if os.path.exists(path):
            return path
        key = (url, size)
        with self.lock:
            if key not in self.pending and key not in self.failed:
                self.pending.add(key)
                self.q.put(key)
        return None

    def is_failed(self, url, size):
        return (url, size) in self.failed

    def _worker(self):
        while True:
            url, size = self.q.get()
            path = self._path(url, size)
            try:
                src = os.path.join(CACHE_DIR, url.rsplit("/", 1)[-1])
                if os.path.exists(src):
                    with open(src, "rb") as f:
                        data = f.read()
                else:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 aion2meter"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        data = r.read()
                    with open(src, "wb") as f:
                        f.write(data)
                w, h, rgba = decode_png(data)
                small = downscale(w, h, rgba, size, radius=max(2, size // 8))
                tmp = path + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(encode_png(size, size, small))
                os.replace(tmp, path)
            except Exception:
                with self.lock:
                    self.failed.add((url, size))
            finally:
                with self.lock:
                    self.pending.discard((url, size))
                    self.done += 1
