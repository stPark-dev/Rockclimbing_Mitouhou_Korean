"""Game text bytes <-> glyph-index tokens.

Established on the menu module's database page (docs/survey.md §3.2):
  01-EF        glyph b - 1 (0-238)
  F0-F4 xx     glyph 0xEF + ((b - 0xF0) << 8 | xx) (239 and up)
  FE           line break            -> ("nl",)
  FD           page start (inferred) -> ("page",)
  FF           page end              -> ("end",)
Glyph indices stop at the font's 1348 cells. 00 and F5-FC have no
established meaning inside text and are refused.
"""

GLYPHS = 1348
_CONTROL = {0xFE: ("nl",), 0xFD: ("page",), 0xFF: ("end",)}
_BYTE = {v: k for k, v in _CONTROL.items()}


def code(k):
    if not 0 <= k < GLYPHS:
        raise ValueError(f"glyph {k} is outside the {GLYPHS}-cell font")
    if k <= 0xEE:
        return bytes([k + 1])
    v = k - 0xEF
    return bytes([0xF0 + (v >> 8), v & 0xFF])


def decode(raw):
    toks, i = [], 0
    while i < len(raw):
        b = raw[i]
        if b in _CONTROL:
            toks.append(_CONTROL[b])
            i += 1
        elif 0x01 <= b <= 0xEF:
            toks.append(("g", b - 1))
            i += 1
        elif 0xF0 <= b <= 0xF4:
            if i + 1 >= len(raw):
                raise ValueError(f"lead byte {b:02X} at {i} has no second byte")
            k = 0xEF + ((b - 0xF0) << 8 | raw[i + 1])
            if k >= GLYPHS:
                raise ValueError(f"code {b:02X}{raw[i + 1]:02X} at {i} is past the font")
            toks.append(("g", k))
            i += 2
        else:
            raise ValueError(f"byte {b:02X} at {i} has no established text meaning")
    return toks


def read_page(raw, start):
    """Tokens from `start` through the page-end FF, and the offset after it.

    FF is also the second byte of codes such as F3 FF (△), so the end can only
    be found by reading token by token."""
    i = start
    toks = []
    while i < len(raw):
        b = raw[i]
        n = 2 if 0xF0 <= b <= 0xF4 else 1
        toks += decode(raw[i : i + n])
        i += n
        if toks[-1] == ("end",):
            return toks, i
    raise ValueError(f"no page end after {start:#x}")


def encode(toks):
    out = bytearray()
    for t in toks:
        out += code(t[1]) if t[0] == "g" else bytes([_BYTE[t]])
    return bytes(out)
