"""Graphics compression of the game (block types 0x73, 0x74 and stored 0xFF), from the EXE decoder.

Stream (0x8001214C): blocks until a 0x00 type byte; block k expands at dst + k*0x2000, and a block
may consume at most 0x2003 source bytes. Block decoder 0x80011CC0 dispatches on the first byte.

0x74 (0x800123F4): count n, n escape bytes, n little-endian pairs; afterwards every escape byte read
expands to its pair, low byte first (0x80012340). 0x73 is the same LZ read byte by byte:
  00 end | 7F lo hi v: run of lo|hi<<8 | 7E c v: run of c+4 | 1LLLLDDD d: copy L+3 from DDDd+1 back
  (zeros before the block start) | 0nnnnnnn: n literals.
0xFF (0x80011E48): lo hi, then that many stored bytes. 0x40: one value repeated lo|hi<<8 times.
"""

BLOCK = 0x2000
MAX_USED = 0x2003
MAX_PAIRS = 16  # escape keys at 0x80060408 and pairs at 0x80060418 hold 16 each


class Reader:
    def __init__(self, data, pos, pairs):
        self.data, self.pos, self.pairs, self.pending = data, pos, pairs, None

    def byte(self):
        if self.pending is not None:
            b, self.pending = self.pending, None
            return b
        b = self.data[self.pos]
        self.pos += 1
        if b in self.pairs:
            pair = self.pairs[b]
            self.pending = pair >> 8
            return pair & 0xFF
        return b


def decode_block(data, pos=0):
    """Decode one block at data[pos]; return (output bytes, source bytes used)."""
    kind = data[pos]
    if kind == 0xFF:
        n = data[pos + 1] | data[pos + 2] << 8
        if pos + 3 + n > len(data):
            raise ValueError(f"stored block at {pos:#x} is cut short")
        return bytes(data[pos + 3:pos + 3 + n]), n + 3
    if kind == 0x40:  # 0x80011FE0: value, lo hi count
        return bytes([data[pos + 1]]) * (data[pos + 2] | data[pos + 3] << 8), 4
    if kind not in (0x73, 0x74):
        raise ValueError(f"unsupported block type {kind:#x} at {pos:#x}")
    p, pairs = pos + 1, {}
    if kind == 0x74:
        n = data[p]
        if n > MAX_PAIRS:
            raise ValueError(f"0x74 block at {pos:#x} has {n} pairs, the game holds {MAX_PAIRS}")
        keys = data[p + 1:p + 1 + n]
        vals = [data[p + 1 + n + 2 * i] | data[p + 2 + n + 2 * i] << 8 for i in range(n)]
        pairs = dict(zip(keys, vals))
        p += 1 + 3 * n
    r = Reader(data, p, pairs)
    out = bytearray()
    while True:
        b = r.byte()
        if b == 0:
            break
        if b == 0x7F:
            n = r.byte() | r.byte() << 8
            out += bytes([r.byte()]) * n
        elif b == 0x7E:
            n = r.byte() + 4
            out += bytes([r.byte()]) * n
        elif b & 0x80:
            n = ((b >> 3) & 0xF) + 3
            dist = ((b & 7) << 8 | r.byte()) + 1
            for _ in range(n):
                out.append(out[-dist] if dist <= len(out) else 0)
        else:
            out += bytes(r.byte() for _ in range(b & 0x7F))
    return bytes(out), r.pos - pos


def decode_stream(data, pos=0):
    """Decode blocks until a 0x00 type byte; return (output, source bytes used including the 0x00)."""
    out, start = bytearray(), pos
    while data[pos] != 0:
        block, used = decode_block(data, pos)
        if used > MAX_USED:
            raise ValueError(f"block at {pos:#x} uses {used:#x} bytes, the game stops at 0x2004")
        if len(block) > BLOCK:
            raise ValueError(f"block at {pos:#x} expands to {len(block):#x} bytes, more than 0x2000")
        if len(out) % BLOCK:
            raise ValueError("only the last block may be shorter than 0x2000")
        out += block
        pos += used
    return bytes(out), pos - start + 1


def _tokens(raw):
    out, lits, i, n = bytearray(), bytearray(), 0, len(raw)
    heads = {}

    def flush():
        for k in range(0, len(lits), 0x7D):
            chunk = lits[k:k + 0x7D]
            out.append(len(chunk))
            out.extend(chunk)
        lits.clear()

    while i < n:
        run = 1
        while i + run < n and raw[i + run] == raw[i] and run < 0xFFFF:
            run += 1
        best_len, best_dist = 0, 0
        if i + 3 <= n:
            for j in reversed(heads.get(raw[i:i + 3], [])[-256:]):
                if i - j > 2048:
                    break
                k = 0
                while k < 18 and i + k < n and raw[j + k] == raw[i + k]:
                    k += 1
                if k > best_len:
                    best_len, best_dist = k, i - j
        if run >= 4 and run >= best_len:
            flush()
            if run <= 259:
                out += bytes([0x7E, run - 4, raw[i]])
            else:
                out += bytes([0x7F, run & 0xFF, run >> 8, raw[i]])
            step = run
        elif best_len >= 3:
            flush()
            d = best_dist - 1
            out += bytes([0x80 | (best_len - 3) << 3 | d >> 8, d & 0xFF])
            step = best_len
        else:
            lits.append(raw[i])
            step = 1
        for k in range(i, min(i + step, n - 2)):
            heads.setdefault(raw[k:k + 3], []).append(k)
        i += step
    flush()
    return bytes(out)


def _pairs(tokens):
    """Byte-pair substitution for a 0x74 block: free byte values stand for frequent pairs of other
    bytes (the decoder expands one level only). Returns (escape keys, pair values, new stream)."""
    free = [b for b in range(1, 256) if b not in set(tokens)]
    keys, vals, stream = [], [], list(tokens)
    while free and len(keys) < MAX_PAIRS:
        esc = set(keys)
        count = {}
        i = 0
        while i < len(stream) - 1:
            a, b = stream[i], stream[i + 1]
            if a not in esc and b not in esc:
                count[(a, b)] = count.get((a, b), 0) + 1
            i += 1
        if not count:
            break
        pair, n = max(count.items(), key=lambda kv: kv[1])
        if n < 4:
            break
        k = free.pop(0)
        out, i = [], 0
        while i < len(stream):
            if i + 1 < len(stream) and (stream[i], stream[i + 1]) == pair:
                out.append(k)
                i += 2
            else:
                out.append(stream[i])
                i += 1
        if len(stream) - len(out) <= 3:
            free.insert(0, k)
            break
        keys.append(k)
        vals.append(pair[0] | pair[1] << 8)
        stream = out
    return keys, vals, bytes(stream)


def encode_block(raw):
    """Encode at most 0x2000 bytes as the smallest of a 0x74, 0x73 or stored block."""
    assert len(raw) <= BLOCK
    tokens = _tokens(raw) + b"\x00"
    keys, vals, stream = _pairs(tokens)
    cands = [bytes([0x73]) + tokens]
    if keys:
        cands.append(bytes([0x74, len(keys)]) + bytes(keys)
                     + b"".join(bytes([v & 0xFF, v >> 8]) for v in vals) + stream)
    cands.append(bytes([0xFF, len(raw) & 0xFF, len(raw) >> 8]) + raw)
    return min((c for c in cands if len(c) <= MAX_USED), key=len)


def encode_stream(raw):
    return b"".join(encode_block(raw[k:k + BLOCK]) for k in range(0, len(raw), BLOCK)) + b"\x00"
