"""AION 2 wire protocol: framing, LZ4 bundles and the records a meter needs.

Ported from the A2Tools DPS Meter parser (GPL-3.0,
github.com/taengu/A2Tools-DPS-Meter, src-tauri/src/capture/framing.rs and
stream_processor.rs), which is checked against the game's own combat log.
Opcodes are the post-June-2026 layout; older leading bytes are still accepted
where the reference accepts them.

Wire shape of the server->client TCP stream:

    00 ...                                padding, skipped
    <varint len> <payload>                a packet; physical size is len - 3
    <varint len> FF FF <u32 size> <lz4>   a compressed bundle of further packets
"""
import re
from collections import OrderedDict

from .lz4 import decompress_block

MAX_PACKET_BYTES = 65535
MAX_FRAGMENT_WAIT_BYTES = 16384
MAX_DECOMPRESSED_BYTES = 1_000_000
MAX_BUNDLE_DEPTH = 6

PACKET, BUNDLE = 0, 1

# Special damage tags (attack quality / position).
CRIT, BACK, FRONT, PARRY, PERFECT, DOUBLE, SMITE, POWERSHARD = (
    "crit", "back", "front", "parry", "perfect", "double", "smite", "powershard")

_RE_IDENTITY = re.compile(rb"[\x33\x44\x45]\x36", re.S)
_RE_SPAWN = re.compile(rb"[\x40\x41\x44\x45]\x36", re.S)

_U32_MASK = 0xFFFFFFFF


# ───────────────────────── varints ─────────────────────────

def read_varint(b, off):
    """(value, length); (-1, -1) when incomplete or longer than 32 bits."""
    value = 0
    shift = 0
    count = 0
    n = len(b)
    while True:
        if off + count >= n:
            return -1, -1
        bv = b[off + count]
        count += 1
        value |= (bv & 0x7F) << shift
        if not bv & 0x80:
            value &= _U32_MASK
            if value >= 0x80000000:
                value -= 0x100000000
            return value, count
        shift += 7
        if shift >= 32:
            return -1, -1


def tvi(b, off):
    """try_read_varint: (value or None, new_offset). Advances even when the value is negative."""
    v, n = read_varint(b, off)
    if n <= 0:
        return None, off
    return (v if v >= 0 else None), off + n


def can_read_varint(b, off):
    if off >= len(b):
        return False
    end = min(len(b), off + 5)
    for i in range(off, end):
        if not b[i] & 0x80:
            return True
    return False


def varint_ending_at(data, end, min_start, lo, hi):
    """The varint that ends right before `end`, preferring one not preceded by a continuation byte."""
    fallback = None
    for v_len in (1, 2, 3):
        v_start = end - v_len
        if v_start < 0:
            break
        if v_start < min_start or not can_read_varint(data, v_start):
            continue
        v, n = read_varint(data, v_start)
        if n != v_len or not lo <= v <= hi:
            continue
        continued = v_start > 0 and data[v_start - 1] & 0x80
        if not continued:
            return v
        if fallback is None:
            fallback = v
    return fallback


def u32le(b, off):
    return b[off] | (b[off + 1] << 8) | (b[off + 2] << 16) | (b[off + 3] << 24)


def u16le(b, off):
    return b[off] | (b[off + 1] << 8)


# ───────────────────────── names ─────────────────────────

NAME_FIELD_MIN, NAME_FIELD_MAX = 1, 48


def exact_name(field):
    """A character name: 1-12 letters/digits in any script, at least one letter."""
    try:
        name = bytes(field).decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not 1 <= len(name) <= 12:
        return None
    if not all(ch.isalnum() for ch in name):
        return None
    if not any(ch.isalpha() for ch in name):
        return None
    return name


def is_placeholder_name(raw):
    """Unnamed tutorial characters are called `$` + random letters/digits."""
    if not raw.startswith("$"):
        return False
    rest = raw[1:]
    return len(rest) >= 4 and rest.isascii() and rest.isalnum()


# ───────────────────────── framing ─────────────────────────

def walk(buf):
    """Split a TCP stream buffer into frames. Returns (frames, consumed)."""
    frames = []
    off = 0
    n = len(buf)
    while off < n:
        if buf[off] == 0:
            off += 1
            continue
        value, length = read_varint(buf, off)
        if length <= 0 or value <= 0:
            if off + 5 > n:
                break
            off += 1
            continue
        total = value - 3
        if total <= 0 or total > MAX_PACKET_BYTES:
            off += 1
            continue
        if off + total > n:
            if total > MAX_FRAGMENT_WAIT_BYTES:
                off += 1
                continue
            break  # a TCP fragment: wait for more bytes
        ps = length
        if ps + 1 < total and buf[off + ps] == 0xFF and buf[off + ps + 1] == 0xFF:
            size = total + 1  # an outer bundle is one byte longer than declared
            if off + size > n:
                break
            frames.append((BUNDLE, off, off + size, ps))
            off += size
        else:
            frames.append((PACKET, off, off + total, ps))
            off += total
    return frames, off


def walk_inner(buf):
    """Frames inside a decompressed bundle. Stops instead of resyncing."""
    frames = []
    off = 0
    n = len(buf)
    while off < n:
        if buf[off] == 0:
            off += 1
            continue
        value, length = read_varint(buf, off)
        if length <= 0 or value <= 0:
            break
        if value <= 3:
            off += 1
            continue
        total = value - 3
        end = off + total
        if end > n:
            break
        ps = length
        nested = total > ps + 1 and buf[off + ps] == 0xFF and buf[off + ps + 1] == 0xFF
        frames.append((BUNDLE if nested else PACKET, off, end, ps))
        off += total  # no +1 here, unlike the outer walk
    return frames, off


def decompress_bundle(payload):
    """`FF FF <u32 size LE> <lz4 block>` -> bytes, or None."""
    if len(payload) < 7:
        return None
    size = u32le(payload, 2)
    if size == 0 or size > MAX_DECOMPRESSED_BYTES:
        return None
    return decompress_block(payload[6:], size)


# ───────────────────────── helpers from the reference ─────────────────────────

def is_valid_skill_code(code):
    return 1 <= code <= 299_999_999


def should_treat_first_value_as_damage(first, second, and_result, damage_type):
    if not 1_000 <= first <= 99_999_999:
        return False
    if not 0 <= second <= 25:
        return False
    if first > 5_000_000:
        return False
    return and_result == 6 and damage_type == 3


def should_use_repeated_hit_damage(switch_value, encoded, mh_count, first_mh, all_match):
    if first_mh is None or switch_value != 54 or mh_count <= 0 or not all_match:
        return False
    main = encoded - mh_count * first_mh
    if main > first_mh:
        return False
    return encoded // 10 == first_mh


def _is_marker(b, off, n):
    return off + 1 < n and b[off + 1] == 0 and 1 <= b[off] <= 7


def parse_party_roster_at(data, at):
    """Body of a `02 97` party roster. Returns (members, complete, dungeon_id) or None.

    members: list of (name, dict(slot, level, gear_score, combat_power, server_id, job)).
    """
    from .gamedata import job_from_roster_class
    n = len(data)
    o = at + 4  # party_key u32
    if o >= n:
        return None
    name_len = data[o]
    o += 1
    if not 1 <= name_len <= 40 or o + name_len > n:
        return None
    try:
        bytes(data[o:o + name_len]).decode("utf-8")
    except UnicodeDecodeError:
        return None
    o += name_len
    if o >= n:
        return None
    party_size = data[o]
    o += 1
    if not 1 <= party_size <= 12:
        return None
    if o + 4 > n:
        return None
    dungeon_id = u32le(data, o)
    o += 4 + 2 + 8 + 3
    count, clen = read_varint(data, o)
    if clen <= 0 or not 1 <= count <= 12:
        return None
    o += clen

    members = []
    complete = False
    for index in range(count):
        if o + 20 > n:
            break
        slot = data[o + 1]
        o += 2
        if o + 8 > n:
            return None
        dbid = int.from_bytes(bytes(data[o:o + 8]), "little")
        o += 8
        server_id = dbid >> 48
        if o >= n:
            return None
        nick_len = data[o]
        o += 1
        if nick_len == 0:
            complete = True
            break
        if nick_len > 40 or o + nick_len > n:
            break
        try:
            nickname = bytes(data[o:o + nick_len]).decode("utf-8")
        except UnicodeDecodeError:
            break
        o += nick_len
        if o + 12 > n:
            break
        job = job_from_roster_class(u32le(data, o))
        o += 4
        level = u32le(data, o)
        o += 4
        if not 1 <= level <= 200:
            break
        gear_score = u32le(data, o)
        o += 4
        if gear_score > 1_000_000:
            break
        anchor = None
        for i in range(o, min(o + 10, n - 2) + 1):
            if u16le(data, i) == server_id:
                anchor = i
                break
        if anchor is None:
            break
        o = anchor + 2 + 2 + 1
        if o + 8 > n:
            return None
        combat_power = int.from_bytes(bytes(data[o:o + 8]), "little")
        o += 8
        if combat_power > 100_000_000:
            break
        members.append((nickname, {
            "slot": slot, "level": level, "gear_score": gear_score, "dbid": dbid,
            "combat_power": combat_power, "server_id": server_id, "job": job,
        }))
        if index + 1 == count:
            complete = True
            break
        nxt = _find_next_member(data, o, (slot + 1) & 0xFF)
        if nxt is None:
            break
        o = nxt
    if not members:
        return None
    return members, complete, dungeon_id


def _find_next_member(data, start, expected_slot):
    n = len(data)
    end = min(start + 32, n - 12)
    for i in range(start, end + 1):
        if data[i + 1] != expected_slot:
            continue
        server_id = u16le(data, i + 8)
        if server_id == 0 or server_id > 9_999:
            continue
        name_len = data[i + 10]
        if name_len == 0 or name_len > 40 or i + 11 + name_len > n:
            continue
        try:
            bytes(data[i + 11:i + 11 + name_len]).decode("utf-8")
        except UnicodeDecodeError:
            continue
        return i
    return None


def find_spawn_dbid(pkt, start, end=None):
    """The account id in a player spawn, after the name: `01 <dbid u64> 04 CD 00`.

    A dbid is `<account u32> 00 00 <home server u16>`; the server must be a
    real one. Checked against the party roster's dbids on a dungeon capture."""
    end = len(pkt) if end is None else min(end, len(pkt))
    i = start
    while True:
        i = pkt.find(b"\x04\xcd\x00", i, end)
        if i < 0:
            return None
        d = i - 8
        if d - 1 >= start and pkt[d - 1] == 0x01 and pkt[d + 4] == 0 and pkt[d + 5] == 0:
            server = u16le(pkt, d + 6)
            if 1000 <= server <= 9_999 and u32le(pkt, d):
                return int.from_bytes(bytes(pkt[d:d + 8]), "little")
        i += 3


def parse_spawn_owner_block(pkt, at, self_id):
    """`<parent_key u32> <legion_id u32> <u16 0> <u16 server> <len><legion name>` -> parent id."""
    if at + 13 > len(pkt):
        return None
    parent = u32le(pkt, at)
    if parent == 0 or parent > 9_999_999 or parent == self_id:
        return None
    if u16le(pkt, at + 8) != 0:
        return None
    server_id = u16le(pkt, at + 10)
    if server_id == 0 or server_id > 9_999:
        return None
    name_len = pkt[at + 12]
    if name_len > 40 or at + 13 + name_len > len(pkt):
        return None
    try:
        bytes(pkt[at + 13:at + 13 + name_len]).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return parent


class _BoundedSet:
    def __init__(self, cap):
        self.cap = cap
        self.d = OrderedDict()

    def __contains__(self, k):
        return k in self.d

    def add(self, k):
        if k in self.d:
            return
        if len(self.d) >= self.cap:
            self.d.popitem(last=False)
        self.d[k] = None


# ───────────────────────── the stream processor ─────────────────────────

class StreamProcessor:
    """Parses one server->client stream and reports what it finds to a Store."""

    def __init__(self, store, gamedata):
        self.store = store
        self.gd = gamedata
        self.seen_embedded = _BoundedSet(16_384)
        self.pending_compact = None  # (actor_id, skill_raw)
        self.stats = {"frames": 0, "bundles": 0, "bundle_fail": 0, "damage": 0, "dot": 0}
        self.on_record = None  # diagnostics hook: called with the raw fields of each direct hit

    # ----- entry -----

    def consume_stream(self, buf):
        frames, consumed = walk(buf)
        for kind, start, end, ps in frames:
            self.stats["frames"] += 1
            if kind == BUNDLE:
                self.unwrap_bundle(buf[start + ps:end], 0)
            else:
                pkt = buf[start:end]
                self.parse_perfect_packet(pkt)
                self.scan_embedded_bundles_for_identity(pkt)
        if len(buf) >= 4:
            self.scan_for_embedded_04_8d(buf)
            self.scan_for_entity_hp(buf)
        if len(buf) >= 6:
            self.scan_for_embedded_spawns(buf)
        self.scan_masked_identity(buf)
        self.scan_party_roster(buf)
        return consumed

    def unwrap_bundle(self, payload, depth):
        if len(payload) < 7 or depth > MAX_BUNDLE_DEPTH:
            return
        data = decompress_bundle(payload)
        if data is None:
            self.stats["bundle_fail"] += 1
            return
        self.stats["bundles"] += 1
        self.pending_compact = None
        frames, _ = walk_inner(data)
        for kind, start, end, ps in frames:
            if kind == BUNDLE:
                self.unwrap_bundle(data[start + ps:end], depth + 1)
            else:
                pkt = data[start:end]
                ctx = self.extract_pending_compact_skill_context(pkt)
                if ctx is not None:
                    self.pending_compact = ctx
                self.parse_perfect_packet(pkt)
        self.scan_for_embedded_04_8d(data)
        self.scan_for_entity_hp(data)
        self.scan_for_embedded_spawns(data)
        self.scan_masked_identity(data)
        self.scan_party_roster(data)
        self.pending_compact = None

    def scan_embedded_bundles_for_identity(self, pkt):
        """Self records also arrive in bundles nested mid-packet; read identity from those."""
        i = 1
        n = len(pkt)
        while i + 8 < n:
            i = pkt.find(b"\xff\xff", i)
            if i < 0 or i + 8 >= n:
                return
            found = None
            for ln in (3, 2, 1):
                at = i - ln
                if at < 0:
                    continue
                value, length = read_varint(pkt, at)
                if length != ln or value <= 4:
                    continue
                end = at + (value - 3) + 1
                if end > n:
                    continue
                data = decompress_bundle(pkt[i:end])
                if data is not None:
                    found = (end, data)
                    break
            if found:
                end, data = found
                self.scan_masked_identity(data)
                self.scan_party_roster(data)
                i = end
            else:
                i += 1

    def parse_perfect_packet(self, pkt):
        if len(pkt) < 3:
            return False
        parsed_damage = self.parse_damage(pkt, True, False)
        parsed_ownership = self.parse_summon_ownership_packet(pkt)
        parsed_summon = self.parse_summon_packet(pkt)
        parsed_hp = self.parse_hp_update_packet(pkt)
        self.parse_positions(pkt)
        self.parse_party_scope_packet(pkt)
        self.parse_death_packet(pkt)
        self.parse_zone_change_packet(pkt)
        if not (parsed_damage or parsed_summon or parsed_ownership or parsed_hp):
            self.parse_dot_packet(pkt)
        return parsed_damage

    # ----- small fixed records -----

    def _opcode_at(self, pkt):
        """Offset just past the length prefix, or -1."""
        _, n = read_varint(pkt, 0)
        return n if n > 0 else -1

    def parse_hp_update_packet(self, pkt):
        # `<len> 1B 92 <entity> <hp> <max hp>`
        o = self._opcode_at(pkt)
        if o < 0 or o + 1 >= len(pkt) or pkt[o] != 0x1B or pkt[o + 1] != 0x92:
            return False
        pos = o + 2
        actor, n = read_varint(pkt, pos)
        if n <= 0 or not 100 <= actor <= 9_999_999:
            return False
        pos += n
        _, n = read_varint(pkt, pos)
        if n <= 0:
            return False
        pos += n
        mx, n = read_varint(pkt, pos)
        if n <= 0 or not 0 < mx <= 50_000_000:
            return False
        self.store.append_mob_hp(actor, mx)
        return True

    def scan_for_entity_hp(self, data):
        """`8D <entity> 02 01 00 <u32 current HP> 00 00 00 00`: live HP of NPCs.

        The same feed carries `8D <entity> 01 01 01 ...` for the local player
        only: in a 100-player capture it named nobody but you (both of your
        ids across a zone change), and on a training dummy only you, about
        twice a second. That is how you are found before the self record."""
        n = len(data)
        i = 0
        while True:
            i = data.find(b"\x8d", i)
            if i < 0 or i + 1 >= n:
                return
            eid, ln = read_varint(data, i + 1)
            if ln <= 0 or not 100 <= eid <= 9_999_999:
                i += 1
                continue
            d = i + 1 + ln
            if (d + 11 <= n and data[d] == 0x02 and data[d + 1] == 0x01 and data[d + 2] == 0x00
                    and data[d + 7:d + 11] == b"\x00\x00\x00\x00"):
                cur = u32le(data, d + 3)
                if cur <= 100_000_000:
                    self.store.set_mob_current_hp(eid, cur)
                i = d + 11
                continue
            if d + 3 <= n and data[d] == 0x01 and data[d + 1] == 0x01 and data[d + 2] == 0x01:
                self.store.note_self_marker(eid)
                i = d + 3
                continue
            i += 1

    def parse_positions(self, pkt):
        """Positions, used to tie party members (known by account id) to their entities.

        `1C 92 <dbid u64> <16 bytes> <x f32> <y f32> <z f32>` is a party member's
        map marker. Movement records (`1A 37`, `1B 37`, `2F 37`, `2B 38`, ...)
        start `<opcode> <entity varint>` and carry the same x/y floats a few
        bytes later, byte for byte, so a match names the entity. Checked on a
        dungeon capture: all four other members bound to the ids the game's
        own spawn records gave them."""
        o = self._opcode_at(pkt)
        if o < 0 or o + 12 > len(pkt):
            return
        if pkt[o] == 0x1C and pkt[o + 1] == 0x92:
            if o + 34 <= len(pkt):
                dbid = int.from_bytes(bytes(pkt[o + 2:o + 10]), "little")
                self.store.note_party_position(dbid, bytes(pkt[o + 26:o + 34]))
            return
        if pkt[o + 1] not in (0x36, 0x37, 0x38):
            return
        eid, n = read_varint(pkt, o + 2)
        if n <= 0 or not 100 <= eid <= 9_999_999:
            return
        seg = bytes(pkt[o + 2 + n:o + 2 + n + 24])
        note = self.store.note_entity_position
        for k in range(0, len(seg) - 7):
            note(eid, seg[k:k + 8])

    def parse_party_scope_packet(self, pkt):
        # `<len> 06 38 <entity varint>`: sent about you (Global) / your party only.
        o = self._opcode_at(pkt)
        if o < 0 or o + 3 >= len(pkt) or pkt[o] != 0x06 or pkt[o + 1] != 0x38:
            return
        v, n = read_varint(pkt, o + 2)
        if n > 0:
            self.store.note_party_scope(v)

    def parse_zone_change_packet(self, pkt):
        # `<len> 23 36 00 ...`: the local player teleported in (zone load).
        o = self._opcode_at(pkt)
        if o < 0 or o + 2 >= len(pkt):
            return
        if pkt[o] == 0x23 and pkt[o + 1] == 0x36 and pkt[o + 2] == 0x00:
            self.store.note_zone_load()
            self.store.note_zone_change()

    def parse_death_packet(self, pkt):
        # `<len> 42 36 <entity> <0> <flag>`; flag 3 = died in combat.
        o = self._opcode_at(pkt)
        if o < 0 or o + 1 >= len(pkt):
            return
        if pkt[o + 1] != 0x36 or pkt[o] != 0x42:
            return
        pos = o + 2
        entity, n = read_varint(pkt, pos)
        if n <= 0:
            return
        pos += n
        _, n = read_varint(pkt, pos)
        if n <= 0:
            return
        pos += n
        flag, n = read_varint(pkt, pos)
        if n > 0 and flag == 3:
            self.store.mark_dead(entity)

    # ----- DoT -----

    def parse_dot_packet(self, pkt):
        o = self._opcode_at(pkt)
        if o < 0 or len(pkt) <= o + 1:
            return
        if pkt[o] != 0x05 or pkt[o + 1] != 0x38:
            return
        o += 2
        target, n = read_varint(pkt, o)
        if n < 0:
            return
        o += n
        if o >= len(pkt):
            return
        effect = pkt[o]
        o += 1
        # 0x02/0x0A damage; 0x01/0x09 heal; 0x0B HoT. Exact match, not a mask.
        is_heal = effect in (0x01, 0x09, 0x0B)
        if effect not in (0x02, 0x0A) and not is_heal:
            return
        actor, n = read_varint(pkt, o)
        if n < 0 or (actor == target and not is_heal):
            return
        o += n
        _, n = read_varint(pkt, o)
        if n < 0:
            return
        o += n
        if o + 4 > len(pkt):
            return
        raw = u32le(pkt, o)
        if raw >= 0x80000000:
            raw -= 0x100000000
        skill = int(raw / 100)
        o += 4
        if not is_valid_skill_code(skill):
            return
        amount, n = read_varint(pkt, o)
        if n < 0 or amount <= 0 or amount > 99_999_999:
            return
        if is_heal:
            self.store.append_heal(actor, skill, amount, is_hot=effect == 0x0B)
            return
        if skill not in self.gd.dot_ids:
            return
        self.stats["dot"] += 1
        self.store.append_damage(actor=actor, target=target, skill=skill, damage=amount,
                                 is_dot=True)

    # ----- direct damage (04 38) -----

    def _try_embedded_damage(self, pkt):
        if len(pkt) < 6:
            return False
        parsed = False
        so = 0
        n = len(pkt)
        while True:
            so = pkt.find(b"\x04\x38", so)
            if so < 0 or so + 1 >= n:
                break
            key = bytes(pkt[so:so + 64])
            if key in self.seen_embedded:
                so += 1
                continue
            headless = b"\xff\x01" + bytes(pkt[so:])
            if self.parse_damage(headless, False, True):
                self.seen_embedded.add(key)
                parsed = True
                so += 2
            else:
                so += 1
        return parsed

    def parse_damage(self, pkt, allow_embedded, require_trusted):
        _, ln = read_varint(pkt, 0)
        if ln < 0:
            return False
        off = ln
        L = len(pkt)
        if off + 1 >= L:
            return False
        if pkt[off] != 0x04 or pkt[off + 1] != 0x38:
            if allow_embedded:
                return self._try_embedded_damage(pkt)
            return False
        off += 2

        store = self.store
        parsed_any = False
        while off < L:
            chained = False
            if off + 1 < L and pkt[off] == 0x01 and pkt[off + 1] == 0x00:
                off += 2
                chained = True
            if parsed_any and not chained:
                break

            target, off = tvi(pkt, off)
            if target is None or not store.is_plausible_entity_id(target):
                break
            switch, off = tvi(pkt, off)
            if switch is None:
                break
            and_result = switch & 0x0F
            if not 4 <= and_result <= 7:
                break
            unused, off = tvi(pkt, off)
            if unused is None:
                break
            actor, off = tvi(pkt, off)
            if actor is None or not store.is_plausible_entity_id(actor):
                break

            if off + 4 > L:
                break
            skill = u32le(pkt, off)
            off += 4
            if 3_000_000 <= skill <= 3_099_999:  # theostone raw item ids
                skill = skill * 10 + 1
            if not 1 <= skill <= 299_999_999:
                break
            if 1_000_000 <= skill <= 9_999_999:  # 7-digit NPC skills
                break

            if off < L:
                off += 1  # 1-byte uid field
            dummy_type, off = tvi(pkt, off)
            if dummy_type is None:
                break
            damage_type = dummy_type & 0xFF
            temp_v = 12 if and_result == 5 else 10 if and_result == 6 else 14 if and_result == 7 else 8

            specials = []
            mods_byte = pkt[off] if off < L else None
            if and_result in (5, 6, 7) and off < L:
                mods = pkt[off]
                if mods & 0x02:
                    specials.append(PARRY)
                if mods & 0x04:
                    specials.append(PERFECT)
                if mods & 0x08:
                    specials.append(DOUBLE)
                if mods & 0x20:
                    specials.append(SMITE)
                if mods & 0x40:
                    specials.append(POWERSHARD)
                if off + 2 < L:
                    direction = pkt[off + 2]
                    if direction == 0x01:
                        specials.append(BACK)
                    elif direction == 0x02:
                        specials.append(FRONT)
            if damage_type == 3:
                specials.append(CRIT)

            off += temp_v
            if off >= L:
                break

            first, off = tvi(pkt, off)
            if first is None:
                break
            after_first = off
            second, off = tvi(pkt, off)
            if second is None:
                break
            # Post-2026-06: a zero pad and the actor's power scalar precede the value.
            if first == 0:
                after_second = off
                third, off = tvi(pkt, off)
                if third is not None:
                    first = second
                    after_first = after_second
                    second = third

            first_is_damage = should_treat_first_value_as_damage(first, second, and_result, damage_type)
            if not first_is_damage and 1_000 <= first <= 200_000:
                store.note_power_scalar(actor, first)
            if first_is_damage:
                off = after_first
                final = first
            else:
                final = second

            if (switch & 0x30) == 0x30 and off < L:
                _, off = tvi(pkt, off)

            hit_count = 0
            pre_hit = off
            if off < L and not _is_marker(pkt, off, L):
                peek, off = tvi(pkt, off)
                if peek is not None:
                    if 0 <= peek <= 25:
                        hit_count = peek
                    elif not _is_marker(pkt, off, L):
                        actual, off = tvi(pkt, off)
                        if actual is not None:
                            if 0 <= actual <= 25:
                                hit_count = actual
                            else:
                                off = pre_hit

            if final < 0 or final > 99_999_999:
                break

            mh_count = 0
            mh_damage = 0
            first_mh = None
            all_match = True
            if hit_count > 0 and off < L:
                safe_max = min(hit_count, 25)
                cap = max(final, 500_000)
                hits_read = 0
                while hits_read < safe_max and off < L:
                    if _is_marker(pkt, off, L):
                        break
                    if off + 1 < L and pkt[off] == 0x04 and pkt[off + 1] == 0x38:
                        break
                    hv, off = tvi(pkt, off)
                    if hv is None:
                        break
                    if hv > cap or hv < 50:
                        mh_damage = 0
                        first_mh = None
                        all_match = True
                        break
                    if first_mh is None:
                        first_mh = hv
                    elif first_mh != hv:
                        all_match = False
                    mh_damage += hv
                    hits_read += 1
                mh_count = hits_read

            if switch == 54 and hit_count > mh_count and mh_count == 1 and first_mh is not None and all_match:
                mh_count = hit_count
                mh_damage = first_mh * hit_count

            if should_use_repeated_hit_damage(switch, second, mh_count, first_mh, all_match):
                final = first_mh

            if mh_count > 0 and mh_damage > 0 and final > mh_damage:
                final -= mh_damage

            pending = self.pending_compact
            aggregated = (pending is not None and skill == 99_745_942 and actor == pending[0]
                          and hit_count > 1 and mh_damage > 0 and second > mh_damage)
            if aggregated:
                resolved_skill = pending[1]
                final = second - mh_damage
                self.pending_compact = None
            else:
                resolved_skill = self.gd.normalize_skill_id(skill)

            # Life-steal suffix `03 00 <heal varint>` (read past, not counted as damage).
            if off + 1 < L and pkt[off] == 0x03 and pkt[off + 1] == 0x00:
                off += 2
                _, off = tvi(pkt, off)

            if require_trusted and not (actor != target and 1 <= (dummy_type & 0xFF) <= 3
                                        and final > 0 and self.gd.is_known_skill(resolved_skill)):
                break

            if self.on_record is not None:
                self.on_record(dict(actor=actor, target=target, skill=skill, switch=switch,
                                    dtype=dummy_type, mods=mods_byte, damage=final, first=first,
                                    second=second, hit_count=hit_count, mh=mh_damage))
            if actor != target:
                self.stats["damage"] += 1
                store.append_damage(actor=actor, target=target, skill=resolved_skill,
                                    damage=final, multi_hits=mh_count, multi_damage=mh_damage,
                                    specials=specials, is_dot=False)
            elif final > 1 and store.is_known_player(actor):
                # a player's record on themself: an instant self-heal
                store.append_heal(actor, resolved_skill, final)
            parsed_any = True
        return parsed_any

    def extract_pending_compact_skill_context(self, pkt):
        _, ln = read_varint(pkt, 0)
        if ln <= 0 or ln >= len(pkt):
            return None
        body = pkt[ln:]
        bl = len(body)
        marker = None
        for idx in range(0, max(0, bl - 4)):
            if (body[idx] == 0x08 and body[idx + 1] in (0x3B, 0x3D) and body[idx + 2] == 0x38
                    and body[idx + 3] == 0x00 and body[idx + 4] == 0x00):
                marker = idx
                break
        if marker is None:
            return None
        op = body.find(b"\x38", marker + 5)
        if op < 0 or op + 2 >= bl:
            return None
        actor, n = read_varint(body, op + 1)
        if n <= 0 or actor < 100:
            return None
        skill_off = op + 1 + n + 1
        if skill_off + 3 > bl:
            return None
        candidates = []
        if skill_off + 4 <= bl:
            full = u32le(body, skill_off)
            if full >= 0x80000000:
                full -= 0x100000000
            candidates.append(full)
        candidates.append(body[skill_off] | (body[skill_off + 1] << 8) | (body[skill_off + 2] << 16))
        for c in candidates:
            if self.gd.is_known_skill(c):
                return actor, self.gd.normalize_skill_id(c)
        return None

    # ----- summons and spawns -----

    def parse_summon_ownership_packet(self, pkt):
        o = self._opcode_at(pkt)
        if o < 0 or o + 1 >= len(pkt) or pkt[o] != 0x04 or pkt[o + 1] != 0x8D:
            return False
        pos = o + 2
        summon, n = read_varint(pkt, pos)
        if n <= 0 or summon < 100:
            return False
        pos += n
        if pos + 4 > len(pkt):
            return False
        pos += 4
        owner, n = read_varint(pkt, pos)
        if n <= 0 or owner < 100 or owner == summon:
            return False
        if self.store.is_confirmed_summon(summon):
            self.store.append_summon(owner, summon)
        return True

    def scan_for_embedded_04_8d(self, data):
        """`04 8D <entity> <4 bytes> <owner varint> <server u16> <len><name>`: summon/loot owner."""
        store = self.store
        found_any = False
        n = len(data)
        so = 0
        while so + 1 < n:
            idx = data.find(b"\x04\x8d", so)
            if idx < 0:
                break
            so = idx + 2
            if so >= n:
                break
            entity, ln = read_varint(data, so)
            if ln <= 0 or not 100 <= entity <= 9_999_999:
                continue
            fixed = so + ln
            if fixed + 4 > n:
                continue
            after_fixed = fixed + 4
            if after_fixed >= n or data[after_fixed] == 0:
                continue  # all-zero despawn record: no owner
            scan_end = min(n - 2, after_fixed + 128)
            hit = None
            for si in range(after_fixed + 1, scan_end):
                server_id = u16le(data, si)
                if not 1000 <= server_id <= 2999:
                    continue
                owner = varint_ending_at(data, si, after_fixed, 100, 99_999)
                if owner is None or owner == entity:
                    continue
                nl_idx = si + 2
                name_len = data[nl_idx]
                name_end = nl_idx + 1 + name_len
                if not NAME_FIELD_MIN <= name_len <= NAME_FIELD_MAX or name_end > n:
                    continue
                name = exact_name(data[nl_idx + 1:name_end])
                if name:
                    hit = (owner, server_id, name, name_end)
                    break
            if hit is None:
                continue
            owner, server_id, name, name_end = hit
            if store.is_confirmed_summon(entity):
                store.append_summon(owner, entity)
            store.append_nickname(owner, name)
            if not store.is_confirmed_summon(entity) and store.is_damage_target(entity):
                store.note_loot_owner(entity, owner, name)
            found_any = True
            so = name_end
        return found_any

    def scan_for_embedded_spawns(self, data):
        """Spawn records anywhere in the buffer: 41 36 mob/summon, 45 36 player (+pre-June 40/44)."""
        i = 0
        n = len(data)
        while i + 5 < n:
            m = _RE_SPAWN.search(data, i)
            if m is None:
                return
            i = m.start()
            if i + 5 >= n:
                return
            if i > 0 and data[i - 1] == 0x00:
                i += 2
                continue
            op = data[i]
            target, ln = read_varint(data, i + 2)
            if ln > 0 and 100 <= target <= 9_999_999:
                if op in (0x44, 0x45):
                    self.parse_player_spawn_name(data, i + 2)
                else:
                    real = target
                    if real > 1_000_000:
                        real = (real & 0x3FFF) | 0x4000
                    if not self.store.is_mob(real):
                        self.parse_summon_spawn_at(data, i + 2)
            i += 2 + max(ln, 0)

    def parse_summon_packet(self, pkt):
        o = self._opcode_at(pkt)
        if o < 0 or o + 1 >= len(pkt) or pkt[o + 1] != 0x36:
            return False
        if pkt[o] in (0x44, 0x45):
            # A whole spawn frame: its bounds are known, so the account id can be read too.
            self.parse_player_spawn_name(pkt, o + 2, with_dbid=True)
            return False
        if pkt[o] not in (0x40, 0x41):
            return False
        return self.parse_summon_spawn_at(pkt, o + 2)

    def parse_player_spawn_name(self, data, at, with_dbid=False):
        actor, ln = read_varint(data, at)
        if ln <= 0 or not 1 <= actor <= 9_999_999:
            return
        m2 = at + ln + 4
        if m2 + 1 >= len(data) or not data[m2] & 0x01:
            return
        name_len = data[m2 + 1]
        if not NAME_FIELD_MIN <= name_len <= NAME_FIELD_MAX or m2 + 2 + name_len > len(data):
            return
        name = exact_name(data[m2 + 2:m2 + 2 + name_len])
        if not name:
            return
        self.store.note_low_id_entity(actor)
        self.store.append_nickname_authoritative(actor, name)
        if with_dbid:
            dbid = find_spawn_dbid(data, m2 + 2 + name_len)
            if dbid is not None:
                self.store.note_player_dbid(actor, dbid, name)

    def parse_summon_spawn_at(self, pkt, at):
        """`41 36 <entity> <mask u32> <subtrees...> [mask & 0x10] <parent_key>`; kind 0x5F = summon."""
        store = self.store
        off = at
        target, ln = read_varint(pkt, off)
        if ln < 0:
            return False
        off += ln
        real = target
        if real > 1_000_000:
            real = (real & 0x3FFF) | 0x4000
        store.note_summon_spawn(real)
        store.note_low_id_entity(real)
        L = len(pkt)
        if off + 2 >= L:
            self.extract_and_register_mob_type(pkt, off, real)
            return False
        mask = (pkt[off] | (pkt[off + 1] << 8)
                | ((pkt[off + 2] if off + 2 < L else 0) << 16)
                | ((pkt[off + 3] if off + 3 < L else 0) << 24))
        kind = pkt[off]

        def read_name_at(sub):
            g = off + sub
            if g >= L or not pkt[g] & 0x01:
                return None
            cur = g + 1
            if cur >= L:
                return None
            nl = pkt[cur]
            if not NAME_FIELD_MIN <= nl <= NAME_FIELD_MAX or cur + 1 + nl > L:
                return None
            nm = exact_name(pkt[cur + 1:cur + 1 + nl])
            return (nm, cur + 1 + nl) if nm else None

        got = read_name_at(4) or read_name_at(2)
        spawn_name, cursor = got if got else (None, off + 5)

        self.extract_and_register_mob_type(pkt, off, real)

        is_summon = kind == 0x5F
        if is_summon and mask & 0x0010:
            owner = self._find_spawn_parent_key(pkt, cursor, real)
            if owner is not None:
                store.note_low_id_entity(owner)
                store.register_confirmed_summon(real, owner)
                return True

        if spawn_name:
            owner = store.find_id_by_name(spawn_name)
            if owner is not None and owner != real:
                store.register_confirmed_summon(real, owner)
                return True

        if is_summon:
            owner = self._extract_summon_owner_from_spawn(pkt, off)
            if owner > 0 and owner != real and store.is_known_player(owner):
                store.register_confirmed_summon(real, owner)
                return True
        return False

    def _find_spawn_parent_key(self, pkt, search_from, self_id):
        i = max(search_from, 1)
        L = len(pkt)
        while i + 13 <= L:
            if pkt[i - 1] == 0x06:
                parent = parse_spawn_owner_block(pkt, i, self_id)
                if parent is not None:
                    return parent
            i += 1
        return None

    _OWNER_ANCHOR = bytes([0x80, 0x75, 0xD5, 0x2A, 0xBB, 0x03, 0x00, 0x00])

    def _extract_summon_owner_from_spawn(self, pkt, start):
        a = self._OWNER_ANCHOR
        max_search = min(max(len(pkt) - len(a), 0), start + 120)
        idx = pkt.find(a, start, max_search + len(a))
        if idx < 0:
            return -1
        owner, ln = read_varint(pkt, idx + len(a))
        if ln > 0 and 1 <= owner <= 9_999_999:
            return owner
        return -1

    def extract_and_register_mob_type(self, pkt, start, real):
        L = len(pkt)
        max_scan = min(max(L - 2, 0), start + 60)
        so = start
        while so < max_scan:
            if pkt[so] == 0x00 and pkt[so + 1] in (0x40, 0x00) and pkt[so + 2] == 0x02:
                if so >= start + 3:
                    code = pkt[so - 3] | (pkt[so - 2] << 8) | (pkt[so - 1] << 16)
                    self.store.append_mob(real, code)
                    hp = so + 3
                    hp_end = min(max(L - 2, 0), hp + 64)
                    while hp < hp_end:
                        if pkt[hp] == 0x01:
                            cur, n1 = read_varint(pkt, hp + 1)
                            if n1 > 0 and cur > 0:
                                mx, n2 = read_varint(pkt, hp + 1 + n1)
                                if n2 > 0 and mx >= cur:
                                    self.store.append_mob_hp(real, mx, cur)
                                    break
                        hp += 1
                break
            so += 1

    # ----- identity -----

    def scan_masked_identity(self, data):
        """`<33|45 36> <id varint> <mask1 u32> <mask2 u8> [mask2&1] <len><name>`; 33 = you."""
        n = len(data)
        if n < 9:
            return
        store = self.store
        i = 0
        while i + 8 < n:
            m = _RE_IDENTITY.search(data, i)
            if m is None:
                return
            i = m.start()
            if i + 8 >= n:
                return
            is_self = data[i] == 0x33
            ident, ln = read_varint(data, i + 2)
            if ln <= 0 or not 1 <= ident <= 9_999_999:
                i += 1
                continue
            m2 = i + 2 + ln + 4
            if m2 + 1 >= n or not data[m2] & 0x01:
                i += 1
                continue
            name_len = data[m2 + 1]
            if not NAME_FIELD_MIN <= name_len <= NAME_FIELD_MAX or m2 + 2 + name_len > n:
                i += 1
                continue
            field = bytes(data[m2 + 2:m2 + 2 + name_len])
            try:
                raw = field.decode("utf-8")
            except UnicodeDecodeError:
                i += 1
                continue
            if is_self and is_placeholder_name(raw):
                store.set_local_identity(ident, None)
                i = m2 + 2 + name_len
                continue
            name = exact_name(field)
            if not name:
                i += 1
                continue
            store.note_low_id_entity(ident)
            store.append_nickname_authoritative(ident, name)
            if is_self:
                store.set_local_identity(ident, name)
                after = m2 + 2 + name_len
                if after + 6 <= n:
                    from .gamedata import job_from_roster_class
                    server = u16le(data, after)
                    job = job_from_roster_class(u32le(data, after + 2))
                    if 1000 <= server < 3000 and job:
                        level = None
                        if after + 11 <= n:
                            lv = u32le(data, after + 7)
                            if 1 <= lv <= 99:
                                level = lv
                        store.note_self_profile(name, job, level, server)
            i = m2 + 2 + name_len

    def scan_party_roster(self, data):
        n = len(data)
        if n < 32:
            return
        i = 0
        while i + 24 < n:
            i = data.find(b"\x02\x97", i)
            if i < 0 or i + 24 >= n:
                return
            res = parse_party_roster_at(data, i + 2)
            if res:
                members, complete, dungeon = res
                self.store.set_party_roster(members, complete, dungeon)
                i += 2
            else:
                i += 1
