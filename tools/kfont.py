"""Hangul glyphs from a BDF font in the game's 12x12 glyph format.

Game format (established: menu font in MENU/KWAMENU.BIN, glyphs uploaded to
VRAM unchanged, docs/survey.md §3.1): 12 rows of 6 bytes, 4 bits per pixel,
low nibble = left pixel of each pair, values 0-3 (2-bit antialiasing). The
original kanji fill x 0-11, y 0-10. Hangul is drawn at value 3, the font's
Hangul box placed at the top-left of the cell and bottom-aligned on the box
baseline, which leaves the bottom row and the right column empty.

`load_bdf` and `hangul_box` follow the Rurouni Kenshin project's kfont.py.
"""

CELL = 12
GLYPH_BYTES = 72
GLYPHS = 1348
INK = 3


def load_bdf(path):
    glyphs, cur = {}, None
    with open(path, encoding="latin-1") as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == "ENCODING":
                cur = {"code": int(p[1])}
            elif p[0] == "BBX" and cur is not None:
                cur["bbx"] = tuple(map(int, p[1:5]))
            elif p[0] == "BITMAP" and cur is not None:
                cur["rows"] = []
            elif p[0] == "ENDCHAR" and cur is not None:
                if 0 <= cur["code"] < 0x110000 and "bbx" in cur:
                    w = cur["bbx"][0]
                    cur["bits"] = [r >> (len(h) * 4 - w) if len(h) * 4 >= w else r for r, h in cur["rows"]]
                    glyphs[chr(cur["code"])] = cur
                cur = None
            elif cur is not None and "rows" in cur:
                cur["rows"].append((int(p[0], 16), p[0]))
    return glyphs


def hangul_box(font):
    hg = [g for ch, g in font.items() if "가" <= ch <= "힣"]
    if not hg:
        raise ValueError("font has no Hangul syllables")
    return max(g["bbx"][0] for g in hg), max(g["bbx"][1] + g["bbx"][3] for g in hg)


def pixels(glyph_bytes):
    if len(glyph_bytes) != GLYPH_BYTES:
        raise ValueError(f"glyph needs {GLYPH_BYTES} bytes")
    return [[glyph_bytes[y * 6 + x // 2] >> (4 * (x & 1)) & 15 for x in range(CELL)] for y in range(CELL)]


def encode(rows):
    out = bytearray(GLYPH_BYTES)
    for y in range(CELL):
        for x in range(CELL):
            v = rows[y][x]
            if not 0 <= v <= INK:
                raise ValueError(f"pixel value {v} at ({x},{y}) is outside 0-{INK}")
            out[y * 6 + x // 2] |= v << (4 * (x & 1))
    return bytes(out)


def render(glyph, box):
    wmax, hmax = box
    if wmax > CELL or hmax > CELL:
        raise ValueError(f"box {box} exceeds the {CELL}x{CELL} cell")
    w, h, xo, yo = glyph["bbx"]
    top = hmax - (yo + h)
    rows = [[0] * CELL for _ in range(CELL)]
    for r, bits in enumerate(glyph["bits"]):
        for x in range(w):
            if bits >> (w - 1 - x) & 1:
                yy, xx = top + r, xo + x
                if not (0 <= yy < CELL and 0 <= xx < CELL):
                    raise ValueError(f"glyph U+{glyph['code']:04X} pixel ({xx},{yy}) outside the cell")
                rows[yy][xx] = INK
    return encode(rows)
