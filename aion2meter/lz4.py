"""LZ4 block decompression, pure Python.

AION 2 bundles carry raw LZ4 blocks (no frame header). The outer framing hands
us one byte more than the block strictly needs, so the decoder stops as soon as
the declared size is reached instead of insisting the input ends exactly there.
"""


def decompress_block(src: bytes, size: int):
    """Decompress an LZ4 block into at most `size` bytes. Returns None if malformed."""
    out = bytearray()
    ip = 0
    n = len(src)
    while ip < n:
        token = src[ip]
        ip += 1

        lit = token >> 4
        if lit == 15:
            while True:
                if ip >= n:
                    return None
                b = src[ip]
                ip += 1
                lit += b
                if b != 255:
                    break
        if ip + lit > n:
            return None
        out += src[ip:ip + lit]
        ip += lit

        if ip >= n or len(out) >= size:
            break
        if ip + 2 > n:
            return None

        offset = src[ip] | (src[ip + 1] << 8)
        ip += 2
        if offset == 0 or offset > len(out):
            return None

        match_len = token & 15
        if match_len == 15:
            while True:
                if ip >= n:
                    return None
                b = src[ip]
                ip += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4

        start = len(out) - offset
        if match_len <= offset:
            out += out[start:start + match_len]
        else:
            # Overlapping copy: the match repeats the last `offset` bytes.
            chunk = bytes(out[start:])
            reps, rem = divmod(match_len, offset)
            out += chunk * reps + chunk[:rem]

        if len(out) > size:
            return None
    return bytes(out)
