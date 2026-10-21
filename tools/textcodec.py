"""Game text bytes <-> glyph-index tokens.

Established from the renderer in the main executable (docs/survey.md §3.2):
  01-EF, F5-F7 glyph b - 1 (0-238, 244-246)
  F0-F4 xx     glyph 0xEF + ((b - 0xF0) << 8 | xx) (239 and up)
  F8 xx, F9 xx, FA xx, FC xx, FB xx yy
               controls, dispatched through the jump tables at 0x800106EC
               (glyph pass) and 0x8001070C (draw pass) -> ("ctl", b, args):
               F8 icon, F9 jump to string table 0x80070E10[xx],
               FA number from table 0x80081F94[xx], FB set draw attribute,
               FC advance xx full-width cells
  FE           line break            -> ("nl",)
  FD           full-width space, advances 13px -> ("sp",)
  FF           string end            -> ("end",)
Glyph indices stop at the font's 1348 cells. 00 has no established meaning
inside text and is refused.
"""

GLYPHS = 1348
_CONTROL = {0xFE: ("nl",), 0xFD: ("sp",), 0xFF: ("end",)}
_BYTE = {v: k for k, v in _CONTROL.items()}
CONTROL_ARGS = {0xF8: 1, 0xF9: 1, 0xFA: 1, 0xFB: 2, 0xFC: 1}


def code(k):
    if not 0 <= k < GLYPHS:
        raise ValueError(f"glyph {k} is outside the {GLYPHS}-cell font")
    if k <= 0xEE:
        return bytes([k + 1])
    v = k - 0xEF
    return bytes([0xF0 + (v >> 8), v & 0xFF])


def token(raw, i):
    """The token starting at raw[i] and the offset after it."""
    b = raw[i]
    if b in _CONTROL:
        return _CONTROL[b], i + 1
    if 0x01 <= b <= 0xEF or 0xF5 <= b <= 0xF7:
        return ("g", b - 1), i + 1
    if 0xF0 <= b <= 0xF4:
        if i + 1 >= len(raw):
            raise ValueError(f"lead byte {b:02X} at {i} has no second byte")
        k = 0xEF + ((b - 0xF0) << 8 | raw[i + 1])
        if k >= GLYPHS:
            raise ValueError(f"code {b:02X}{raw[i + 1]:02X} at {i} is past the font")
        return ("g", k), i + 2
    if b in CONTROL_ARGS:
        n = CONTROL_ARGS[b]
        if i + n >= len(raw):
            raise ValueError(f"control {b:02X} at {i} is missing its {n}-byte argument")
        return ("ctl", b, bytes(raw[i + 1 : i + 1 + n])), i + 1 + n
    raise ValueError(f"byte {b:02X} at {i} has no established text meaning")


def decode(raw):
    toks, i = [], 0
    while i < len(raw):
        t, i = token(raw, i)
        toks.append(t)
    return toks


def read_page(raw, start):
    """Tokens from `start` through the page-end FF, and the offset after it.

    FF is also the second byte of codes such as F3 FF (△) and can be a control
    argument, so the end can only be found by reading token by token."""
    i, toks = start, []
    while i < len(raw):
        t, i = token(raw, i)
        toks.append(t)
        if t == ("end",):
            return toks, i
    raise ValueError(f"no page end after {start:#x}")


def encode(toks):
    out = bytearray()
    for t in toks:
        if t[0] == "g":
            out += code(t[1])
        elif t[0] == "ctl":
            if len(t[2]) != CONTROL_ARGS[t[1]]:
                raise ValueError(f"control {t[1]:02X} needs {CONTROL_ARGS[t[1]]} argument bytes")
            out += bytes([t[1]]) + t[2]
        else:
            out += bytes([_BYTE[t]])
    return bytes(out)
