"""Passive packet capture through Npcap (wpcap.dll), via ctypes.

Read-only: packets are copied off the network adapters; nothing is sent to the
game or its server and the game process is never touched.
"""
import ctypes as C
import os
import struct
import threading

DEFAULT_FILTER = b"tcp and not port 443 and not port 80"


class _sockaddr(C.Structure):
    _fields_ = [("sa_family", C.c_ushort), ("sa_data", C.c_char * 14)]


class _pcap_addr(C.Structure):
    pass


_pcap_addr._fields_ = [
    ("next", C.POINTER(_pcap_addr)),
    ("addr", C.POINTER(_sockaddr)),
    ("netmask", C.POINTER(_sockaddr)),
    ("broadaddr", C.POINTER(_sockaddr)),
    ("dstaddr", C.POINTER(_sockaddr)),
]


class _pcap_if(C.Structure):
    pass


_pcap_if._fields_ = [
    ("next", C.POINTER(_pcap_if)),
    ("name", C.c_char_p),
    ("description", C.c_char_p),
    ("addresses", C.POINTER(_pcap_addr)),
    ("flags", C.c_uint),
]


class _timeval(C.Structure):
    _fields_ = [("tv_sec", C.c_long), ("tv_usec", C.c_long)]


class _pkthdr(C.Structure):
    _fields_ = [("ts", _timeval), ("caplen", C.c_uint32), ("len", C.c_uint32)]


class _bpf_program(C.Structure):
    _fields_ = [("bf_len", C.c_uint), ("bf_insns", C.c_void_p)]


class NpcapError(RuntimeError):
    pass


def _load():
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidates = [os.path.join(sysroot, "System32", "Npcap", "wpcap.dll"),
                  os.path.join(sysroot, "System32", "wpcap.dll")]
    for path in candidates:
        if os.path.exists(path):
            try:
                os.add_dll_directory(os.path.dirname(path))
            except (OSError, AttributeError):
                pass
            lib = C.CDLL(path)
            break
    else:
        raise NpcapError("Npcap bulunamadı. https://npcap.com adresinden kurun "
                         "(kurulumda 'WinPcap API-compatible Mode' işaretli olsun).")

    lib.pcap_findalldevs.argtypes = [C.POINTER(C.POINTER(_pcap_if)), C.c_char_p]
    lib.pcap_findalldevs.restype = C.c_int
    lib.pcap_freealldevs.argtypes = [C.POINTER(_pcap_if)]
    lib.pcap_open_live.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_char_p]
    lib.pcap_open_live.restype = C.c_void_p
    lib.pcap_datalink.argtypes = [C.c_void_p]
    lib.pcap_datalink.restype = C.c_int
    lib.pcap_compile.argtypes = [C.c_void_p, C.POINTER(_bpf_program), C.c_char_p, C.c_int, C.c_uint32]
    lib.pcap_compile.restype = C.c_int
    lib.pcap_setfilter.argtypes = [C.c_void_p, C.POINTER(_bpf_program)]
    lib.pcap_setfilter.restype = C.c_int
    lib.pcap_freecode.argtypes = [C.POINTER(_bpf_program)]
    lib.pcap_next_ex.argtypes = [C.c_void_p, C.POINTER(C.POINTER(_pkthdr)), C.POINTER(C.POINTER(C.c_ubyte))]
    lib.pcap_next_ex.restype = C.c_int
    lib.pcap_close.argtypes = [C.c_void_p]
    lib.pcap_geterr.argtypes = [C.c_void_p]
    lib.pcap_geterr.restype = C.c_char_p
    if hasattr(lib, "pcap_setbuff"):
        lib.pcap_setbuff.argtypes = [C.c_void_p, C.c_int]
        lib.pcap_setbuff.restype = C.c_int
    return lib


_lib = None


def lib():
    global _lib
    if _lib is None:
        _lib = _load()
    return _lib


def list_devices():
    """[(name, description, has_ipv4)] for every capture-capable adapter."""
    L = lib()
    head = C.POINTER(_pcap_if)()
    err = C.create_string_buffer(256)
    if L.pcap_findalldevs(C.byref(head), err) != 0:
        raise NpcapError(err.value.decode(errors="replace"))
    out = []
    node = head
    while node:
        d = node.contents
        name = (d.name or b"").decode(errors="replace")
        desc = (d.description or b"").decode(errors="replace")
        has_v4 = False
        a = d.addresses
        while a:
            sa = a.contents.addr
            if sa and sa.contents.sa_family == 2:
                has_v4 = True
            a = a.contents.next
        out.append((name, desc, has_v4))
        node = d.next
    L.pcap_freealldevs(head)
    return out


def _skip_device(name, desc):
    text = (name + " " + desc).lower()
    return any(s in text for s in ("bluetooth", "wan miniport", "ndiswan", "etw", "hyper-v virtual switch"))


def is_loopback(dev):
    return "loopback" in dev.lower()


# DLT values
_DLT_NULL, _DLT_EN10MB, _DLT_RAW, _DLT_RAW2, _DLT_LOOP, _DLT_RAW3, _DLT_SLL, _DLT_SLL2 = 0, 1, 12, 14, 108, 101, 113, 276


def _ip_offset(frame, linktype):
    if linktype == _DLT_EN10MB:
        if len(frame) < 14:
            return -1
        off = 12
        eth = (frame[off] << 8) | frame[off + 1]
        while eth in (0x8100, 0x88A8) and off + 6 <= len(frame):
            off += 4
            eth = (frame[off] << 8) | frame[off + 1]
        return off + 2 if eth == 0x0800 else -1
    if linktype in (_DLT_NULL, _DLT_LOOP):
        return 4
    if linktype in (_DLT_RAW, _DLT_RAW2, _DLT_RAW3):
        return 0
    if linktype == _DLT_SLL:
        return 16
    if linktype == _DLT_SLL2:
        return 20
    for off in (0, 4, 14, 16):
        if len(frame) > off and frame[off] >> 4 == 4:
            return off
    return -1


def parse_tcp(frame, linktype):
    """(src_ip, src_port, dst_ip, dst_port, seq, flags, payload) or None."""
    o = _ip_offset(frame, linktype)
    if o < 0 or len(frame) < o + 20 or frame[o] >> 4 != 4:
        return None
    ihl = (frame[o] & 0x0F) * 4
    if frame[o + 9] != 6 or ihl < 20:
        return None
    if ((frame[o + 6] & 0x1F) << 8 | frame[o + 7]) != 0:
        return None  # IP fragment (not expected for game traffic)
    total = (frame[o + 2] << 8) | frame[o + 3]
    end = o + total if total >= ihl + 20 else len(frame)  # 0 with segmentation offload
    end = min(end, len(frame))
    t = o + ihl
    if t + 20 > end:
        return None
    sport, dport, seq = struct.unpack_from("!HHI", frame, t)
    doff = (frame[t + 12] >> 4) * 4
    flags = frame[t + 13]
    src = bytes(frame[o + 12:o + 16])
    dst = bytes(frame[o + 16:o + 20])
    return src, sport, dst, dport, seq, flags, bytes(frame[t + doff:end])


class Capture:
    """One reader thread per adapter; calls `sink(device, ts_ms, tcp_tuple)` for each TCP segment."""

    def __init__(self, sink, bpf=DEFAULT_FILTER, log=print):
        self.sink = sink
        self.bpf = bpf
        self.log = log
        self.running = False
        self.threads = []
        self.handles = []
        self.devices = []

    def start(self):
        L = lib()
        self.running = True
        for name, desc, has_v4 in list_devices():
            if _skip_device(name, desc):
                continue
            if not has_v4 and not is_loopback(name + desc):
                continue
            err = C.create_string_buffer(256)
            h = L.pcap_open_live(name.encode(), 65535, 0, 50, err)
            if not h:
                self.log(f"açılamadı: {desc or name}: {err.value.decode(errors='replace')}")
                continue
            if hasattr(L, "pcap_setbuff"):
                L.pcap_setbuff(h, 16 * 1024 * 1024)
            prog = _bpf_program()
            if L.pcap_compile(h, C.byref(prog), self.bpf, 1, 0xFFFFFFFF) == 0:
                L.pcap_setfilter(h, C.byref(prog))
                L.pcap_freecode(C.byref(prog))
            label = desc or name
            if is_loopback(name):
                label = "Loopback " + label
            self.handles.append(h)
            self.devices.append(label)
            th = threading.Thread(target=self._run, args=(h, label), daemon=True, name=f"cap:{label}")
            self.threads.append(th)
            th.start()
        if not self.handles:
            raise NpcapError("Hiçbir ağ bağdaştırıcısı açılamadı (Npcap yüklü mü? Yönetici olarak deneyin).")
        return self.devices

    def _run(self, h, label):
        L = lib()
        linktype = L.pcap_datalink(h)
        hdr = C.POINTER(_pkthdr)()
        data = C.POINTER(C.c_ubyte)()
        sink = self.sink
        while self.running:
            r = L.pcap_next_ex(h, C.byref(hdr), C.byref(data))
            if r == 1:
                hd = hdr.contents
                frame = C.string_at(data, hd.caplen)
                tcp = parse_tcp(frame, linktype)
                if tcp is not None:
                    sink(label, hd.ts.tv_sec * 1000 + hd.ts.tv_usec // 1000, tcp)
            elif r == 0:
                continue
            else:
                if self.running:
                    msg = L.pcap_geterr(h)
                    self.log(f"yakalama durdu ({label}): {(msg or b'').decode(errors='replace')}")
                break

    def stop(self):
        self.running = False
        for th in self.threads:
            th.join(timeout=1.0)
        L = lib()
        for h in self.handles:
            L.pcap_close(h)
        self.handles.clear()
        self.threads.clear()
