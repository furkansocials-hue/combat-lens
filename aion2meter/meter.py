"""Finds the game connection among captured TCP flows and feeds it, in order, to the parser.

The game stream is recognised by its record terminator (`0E 00 36`, formerly
`06 00 36`), which the server sends many times a second even while idle. A flow
is locked once it shows that rate; a loopback flow (ping reducer / relay) wins
over the external one it duplicates, so nothing is counted twice.

Unlike the reference, segments are put in TCP sequence order and retransmitted
bytes are dropped, so a resent segment can never count its damage twice.
"""
import os
import queue
import threading
import time

from .protocol import StreamProcessor
from .store import Store

SIGNATURES = (b"\x0e\x00\x36", b"\x06\x00\x36")
SIGNATURE_LOCK_THRESHOLD = 12
SIGNATURE_WINDOW_MS = 3_000
LOOPBACK_GRACE_MS = 2_500
ACTIVE_SILENT_SWITCH_MS = 5_000
FLOW_PRUNE_MS = 60_000
MAX_ACC = 2 * 1024 * 1024
# A segment lost on the way comes again when the server's TCP resends it, often after its 300 ms
# minimum timeout and longer when that is lost too. The game waits for it; so must the meter, or
# everything in the hole (and the frames cut by it) is gone for good.
OOO_MAX_SEGMENTS = 4096
OOO_MAX_WAIT_MS = 3_000
GAP_LOG_EVERY_MS = 10_000

TCP_FIN, TCP_SYN, TCP_RST = 0x01, 0x02, 0x04
_MASK32 = 0xFFFFFFFF


def _sdiff(a, b):
    """Signed 32-bit difference a - b."""
    d = (a - b) & _MASK32
    return d - (1 << 32) if d >= (1 << 31) else d


def looks_like_tls(data):
    return len(data) >= 3 and data[0] in (0x14, 0x15, 0x16, 0x17) and data[1] == 0x03 and data[2] <= 0x04


def has_signature(data):
    return any(s in data for s in SIGNATURES)


class Reassembler:
    """In-order TCP payload: drops retransmissions, waits briefly for out-of-order segments."""

    RESET = object()

    def __init__(self):
        self.next_seq = None
        self.pending = {}  # seq -> (payload, ts)
        self.retransmitted = 0
        self.gaps = 0
        self.skipped = 0  # bytes given up on

    def push(self, seq, payload, ts):
        out = []
        if self.next_seq is None:
            self.next_seq = (seq + len(payload)) & _MASK32
            out.append(payload)
            return out
        d = _sdiff(seq, self.next_seq)
        if d > 0:
            self.pending[seq] = (payload, ts)
            oldest = min(t for _, t in self.pending.values())
            if len(self.pending) > OOO_MAX_SEGMENTS or ts - oldest > OOO_MAX_WAIT_MS:
                # The missing bytes are not coming (capture drop): skip the hole.
                self.gaps += 1
                first = min(self.pending, key=lambda s: _sdiff(s, self.next_seq))
                self.skipped += _sdiff(first, self.next_seq)
                self.next_seq = first
                out.append(self.RESET)
                self._drain(out)
            return out
        self._take(seq, payload, out)
        self._drain(out)
        return out

    def _take(self, seq, payload, out):
        d = _sdiff(seq, self.next_seq)
        end = d + len(payload)
        if end <= 0:
            if payload:
                self.retransmitted += 1
            return
        if d < 0:
            payload = payload[-d:]
        out.append(payload)
        self.next_seq = (self.next_seq + len(payload)) & _MASK32

    def _drain(self, out):
        while self.pending:
            ready = [s for s in self.pending if _sdiff(s, self.next_seq) <= 0]
            if not ready:
                return
            for s in sorted(ready, key=lambda x: _sdiff(x, self.next_seq)):
                payload, _ = self.pending.pop(s)
                self._take(s, payload, out)


class Flow:
    def __init__(self, key, ts):
        self.key = key
        self.first_ts = ts
        self.last_ts = ts
        self.sig_count = 0
        self.sig_last = -10 ** 12
        self.qualified = False
        self.tls = False
        self.reasm = Reassembler()
        self.acc = bytearray()
        self.proc = None

    @property
    def device(self):
        return self.key[0]

    def describe(self):
        dev, src, sport, dst, dport = self.key
        ip = ".".join(map(str, src))
        return f"{ip}:{sport} ({dev})"


class Dispatcher:
    def __init__(self, store: Store, gamedata, record_path=None, log=print):
        self.store = store
        self.gd = gamedata
        self.log = log
        self.q = queue.Queue(maxsize=500_000)
        self.flows = {}
        self.active = None
        self.first_candidate_ts = None
        self.clock = 0
        self.running = False
        self.thread = None
        self.dropped = 0
        self.packets = 0
        self.game_bytes = 0
        self.locked_at = None
        self.live = True
        self._record = None
        if record_path:
            os.makedirs(os.path.dirname(os.path.abspath(record_path)), exist_ok=True)
            self._record = open(record_path, "a", encoding="ascii", buffering=1)
        self._last_prune = 0
        self._gaps_logged = (0, 0, 0)  # gaps, bytes, when

    # ----- capture side (any thread) -----

    def sink(self, device, ts, tcp):
        try:
            self.q.put_nowait((device, ts, tcp))
        except queue.Full:
            self.dropped += 1

    # ----- processing thread -----

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True, name="dispatcher")
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self._record:
            self._record.close()
            self._record = None

    def _run(self):
        last_tick = 0.0
        while self.running:
            try:
                item = self.q.get(timeout=0.25)
            except queue.Empty:
                item = None
            if item is not None:
                try:
                    self.handle(*item)
                except Exception as e:  # never let one odd packet stop the meter
                    self.log(f"paket işlenemedi: {e!r}")
            now = time.monotonic()
            if now - last_tick >= 0.5:
                last_tick = now
                f = self.flows.get(self.active) if self.active is not None else None
                if f is not None:
                    self._log_gaps(f.reasm, self.clock)  # the holes not yet told
                with self.store.lock:
                    self.store.now = max(self.store.now, int(time.time() * 1000))
                    self.store.tick()

    def handle(self, device, ts, tcp):
        src, sport, dst, dport, seq, flags, payload = tcp
        self.packets += 1
        if ts > self.clock:
            self.clock = ts
        key = (device, src, sport, dst, dport)

        if flags & (TCP_FIN | TCP_RST) and self.active is not None:
            a = self.active
            if key == a or (device, dst, dport, src, sport) == a:
                self.log(f"oyun bağlantısı kapandı: {self.flows[a].describe() if a in self.flows else a}")
                self._unlock()
        if flags & TCP_SYN:
            self.flows.pop(key, None)
        if not payload:
            return

        f = self.flows.get(key)
        if f is None:
            f = self.flows[key] = Flow(key, ts)
        f.last_ts = ts

        if key == self.active:
            self._feed(f, ts, seq, payload)
            return

        if not f.qualified and not f.tls:
            if looks_like_tls(payload):
                f.tls = True
            elif has_signature(payload):
                if ts - f.sig_last > SIGNATURE_WINDOW_MS:
                    f.sig_count = 0
                f.sig_count += 1
                f.sig_last = ts
                if f.sig_count >= SIGNATURE_LOCK_THRESHOLD:
                    f.qualified = True
                    if self.first_candidate_ts is None:
                        self.first_candidate_ts = ts
        if f.qualified:
            self._consider_lock(f, ts)

        if ts - self._last_prune > 10_000:
            self._last_prune = ts
            for k in [k for k, fl in self.flows.items() if ts - fl.last_ts > FLOW_PRUNE_MS and k != self.active]:
                del self.flows[k]

    def _consider_lock(self, f, ts):
        from .capture import is_loopback
        a = self.flows.get(self.active) if self.active is not None else None
        if a is not None:
            if ts - a.last_ts < ACTIVE_SILENT_SWITCH_MS:
                return  # the locked flow is alive; this is a duplicate (relay) or a stray
            if is_loopback(a.device) and not is_loopback(f.device) and ts - a.last_ts < 15_000:
                return
        if not is_loopback(f.device) and self.first_candidate_ts is not None \
                and ts - self.first_candidate_ts < LOOPBACK_GRACE_MS and a is None:
            return  # give a loopback relay a moment to show up
        self._lock(f)

    def _lock(self, f):
        self.active = f.key
        f.reasm = Reassembler()
        f.acc = bytearray()
        f.proc = StreamProcessor(self.store, self.gd)
        self.locked_at = f.last_ts
        self.log(f"oyun bağlantısı bulundu: {f.describe()}")

    def _unlock(self):
        self.active = None
        self.first_candidate_ts = None
        self.locked_at = None

    def _feed(self, f, ts, seq, payload):
        for chunk in f.reasm.push(seq, payload, ts):
            if chunk is Reassembler.RESET:
                f.acc.clear()
                self._log_gaps(f.reasm, ts)
                continue
            self.feed_chunk(f, ts, chunk)

    def _log_gaps(self, reasm, ts):
        """Holes in the game stream mean damage the meter never saw: say so in the log, at most every
        few seconds."""
        gaps, skipped, when = self._gaps_logged
        if reasm.gaps < gaps:
            gaps = skipped = 0  # a new connection
        if reasm.gaps == gaps or ts - when < GAP_LOG_EVERY_MS:
            return
        self.log(f"oyun verisinde boşluk: {reasm.gaps - gaps} kez, {reasm.skipped - skipped} bayt gelmedi")
        self._gaps_logged = (reasm.gaps, reasm.skipped, ts)

    def feed_chunk(self, f, ts, chunk):
        self.game_bytes += len(chunk)
        if self._record:
            self._record.write(f"{ts}|{f.key[2]}|{chunk.hex()}\n")
        f.acc += chunk
        with self.store.lock:
            self.store.now = ts
            while f.acc:
                buf = bytes(f.acc)
                consumed = f.proc.consume_stream(buf)
                if consumed <= 0:
                    break
                del f.acc[:consumed]
        if len(f.acc) > MAX_ACC:
            f.acc.clear()

    # ----- status -----

    def status(self):
        f = self.flows.get(self.active) if self.active is not None else None
        s = {
            "locked": f is not None,
            "flow": f.describe() if f else None,
            "packets": self.packets,
            "game_bytes": self.game_bytes,
            "dropped": self.dropped,
            "candidates": sum(1 for fl in list(self.flows.values()) if fl.qualified),
        }
        if f is not None and f.proc is not None:
            s.update(f.proc.stats)
            s["retransmitted"] = f.reasm.retransmitted
            s["gaps"] = f.reasm.gaps
            s["silent_ms"] = max(0, int(time.time() * 1000) - f.last_ts) if self.live else 0
        return s


def replay(path, store, gamedata, log=print):
    """Feed a recorded stream (`ts|port|hex` lines) through the parser, as fast as possible."""
    d = Dispatcher(store, gamedata, log=log)
    d.live = False
    flows = {}
    with open(path, encoding="ascii", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            ts_s, key, hexdata = parts
            try:
                ts = int(ts_s)
                chunk = bytes.fromhex(hexdata)
            except ValueError:
                continue
            f = flows.get(key)
            if f is None:
                f = flows[key] = Flow(("replay", b"\0\0\0\0", int(key) if key.isdigit() else 0, b"", 0), ts)
                f.proc = StreamProcessor(store, gamedata)
                d.flows[f.key] = f
                d.active = f.key
            f.last_ts = ts
            d.feed_chunk(f, ts, chunk)
            with store.lock:
                store.tick()
    return d


def default_record_path():
    from .paths import user_path
    return user_path("kayitlar", time.strftime("aion2_%Y%m%d_%H%M%S.txt"))
