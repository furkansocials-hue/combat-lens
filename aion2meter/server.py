"""The UI's local web server: static pages, skill icons and a small JSON API, on 127.0.0.1 only.

Only this machine can reach it, and the API also wants the per-run token the
windows are opened with, so another web page open in a browser cannot read or
drive the meter.
"""
import json
import mimetypes
import os
import re
import secrets
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .gamedata import ICON_BASE
from .paths import APP_ID, resource, user_path

WEB_DIR = resource("web")
ICON_DIR = os.path.dirname(user_path("cache", "icons_web", "x"))
_ICON_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,80}\.png$")
_STATIC_EXT = {".html", ".css", ".js", ".png", ".svg", ".ico", ".woff2", ".json"}


class IconStore:
    """Game icons straight from the CDN, kept on disk after the first fetch."""

    def __init__(self, folder=ICON_DIR):
        self.dir = folder
        self.lock = threading.Lock()
        self.inflight = {}
        self.missing = set()

    def get(self, name):
        path = os.path.join(self.dir, name)
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            pass
        if name in self.missing:
            return None
        with self.lock:
            ev = self.inflight.get(name)
            owner = ev is None
            if owner:
                ev = self.inflight[name] = threading.Event()
        if not owner:
            ev.wait(15)
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                return None
        data = None
        try:
            req = urllib.request.Request(f"{ICON_BASE}/{name}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                data = None
        except Exception:
            data = None
        if data:
            tmp = path + ".tmp"
            try:
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, path)
            except OSError:
                pass
        else:
            self.missing.add(name)
        with self.lock:
            self.inflight.pop(name, None)
        ev.set()
        return data


class _Handler(BaseHTTPRequestHandler):
    server_version = APP_ID
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    # ── plumbing ──
    def _send(self, code, body, ctype, cache=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache or "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=_jsonable).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorised(self, query):
        tok = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(tok, self.server.token)

    # ── routes ──
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        try:
            if path.startswith("/api/"):
                if not self._authorised(query):
                    return self._json({"error": "token"}, 403)
                q = {k: v[0] for k, v in query.items()}
                out = self.server.app.api_get(path[5:], q)
                if out is _NOT_FOUND:
                    return self._json({"error": "not found"}, 404)
                return self._json(out)
            if path.startswith("/icon/"):
                name = path[6:]
                if not _ICON_NAME.match(name):
                    return self._send(404, b"", "text/plain")
                data = self.server.icons.get(name)
                if not data:
                    return self._send(404, b"", "text/plain", cache="max-age=600")
                return self._send(200, data, "image/png", cache="max-age=31536000, immutable")
            return self._static(path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # keep the server alive; the page shows the error state
            try:
                self._json({"error": str(e)}, 500)
            except OSError:
                pass

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        if not url.path.startswith("/api/") or not self._authorised(urllib.parse.parse_qs(url.query)):
            return self._json({"error": "token"}, 403)
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
            body = json.loads(self.rfile.read(n) or b"{}")
            out = self.server.app.api_post(url.path[5:], body)
            self._json(out if out is not None else {"ok": True})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._json({"error": str(e)}, 500)
            except OSError:
                pass

    def _static(self, path):
        if path in ("", "/"):
            path = "/overlay.html"
        rel = os.path.normpath(urllib.parse.unquote(path).lstrip("/"))
        full = os.path.join(WEB_DIR, rel)
        if (rel.startswith("..") or os.path.isabs(rel) or os.path.splitext(rel)[1].lower() not in _STATIC_EXT
                or not os.path.isfile(full)):
            return self._send(404, b"not found", "text/plain")
        with open(full, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, data, ctype, cache="no-cache")


_NOT_FOUND = object()


def _jsonable(o):
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


class UIServer:
    def __init__(self, app):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = app
        self.httpd.token = secrets.token_urlsafe(24)
        self.httpd.icons = IconStore()
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="ui-server", daemon=True)

    @property
    def token(self):
        return self.httpd.token

    def url(self, page, **params):
        params["t"] = self.token
        return f"http://127.0.0.1:{self.port}/{page}?" + urllib.parse.urlencode(params)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


NOT_FOUND = _NOT_FOUND
