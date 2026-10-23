"""Picture replacement for compressed TIMs (D1, D11), docs/graphics_text.md.

TIMs here are 4bpp or 8bpp with one CLUT block. A replacement keeps the header, the CLUT and the
VRAM position, changes only the pixel indices, and is recompressed (tools/lz74.py) into the
original slot of the stream, which is checked against the original bytes first.
"""

import hashlib
import struct

import lz74

# title logo on MENU/KWAMENU.BIN: three 8bpp pieces drawn side by side at (15, 31), sharing the
# background's 256-colour CLUT (0, 480). (stream offset, x in the 288 x 88 logo, width)
LOGO_PIECES = ((0x56D24, 0, 128), (0x59A54, 128, 128), (0x59128, 256, 32))
LOGO_SIZE = (288, 88)
LOGO_SHA1 = {0x56D24: "955d5b18351cd2c1", 0x59A54: "916dad0d6ad711d5", 0x59128: "d9157241122744a1"}


def _blocks(tim):
    flag = struct.unpack_from("<I", tim, 4)[0]
    p = 8
    clut = None
    if flag & 8:
        clut = p
        p += struct.unpack_from("<I", tim, p)[0]
    return flag & 3, clut, p


def image(tim):
    """(width in pixels, height, pixel bytes as stored)."""
    bpp, _, p = _blocks(tim)
    blen, _, _, w, h = struct.unpack_from("<IHHHH", tim, p)
    return w * (4, 2, 1)[bpp], h, bytes(tim[p + 12:p + blen])


def palette(tim):
    _, c, _ = _blocks(tim)
    blen = struct.unpack_from("<I", tim, c)[0]
    vals = struct.unpack_from(f"<{(blen - 12) // 2}H", tim, c + 12)
    return [((v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3) for v in vals]


def with_image(tim, pixels):
    _, _, p = _blocks(tim)
    blen = struct.unpack_from("<I", tim, p)[0]
    if len(pixels) != blen - 12:
        raise ValueError(f"{len(pixels)} pixel bytes for an image of {blen - 12}")
    return bytes(tim[:p + 12]) + bytes(pixels) + bytes(tim[p + blen:])


def slot(data, off):
    """Bytes the stream at off may take: its length plus the zero padding before the next data."""
    _, used = lz74.decode_stream(data, off)
    end = off + used
    while end < len(data) and data[end] == 0:
        end += 1
    return end - off


def quantize(art, pal, size=None):
    """RGB picture -> palette indices (Floyd-Steinberg), as a list of rows."""
    from PIL import Image
    if size:
        art = art.convert("RGB").resize(size, Image.LANCZOS)
    p = Image.new("P", (1, 1))
    p.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 3 * len(pal)))
    q = art.convert("RGB").quantize(palette=p, dither=Image.FLOYDSTEINBERG)
    w, h = q.size
    flat = list(q.getdata())
    return [flat[y * w:(y + 1) * w] for y in range(h)]


def _undithered(art, pal):
    from PIL import Image
    p = Image.new("P", (1, 1))
    p.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 3 * len(pal)))
    q = art.convert("RGB").quantize(palette=p, dither=Image.NONE)
    w, h = q.size
    flat = list(q.getdata())
    return [flat[y * w:(y + 1) * w] for y in range(h)]


def original_logo(menu):
    """The current 288 x 88 logo as an RGB picture."""
    from PIL import Image
    out = Image.new("RGB", LOGO_SIZE)
    for off, x0, w in LOGO_PIECES:
        tim, _ = lz74.decode_stream(bytes(menu), off)
        pw, ph, px = image(tim)
        pal = palette(tim)
        piece = Image.new("RGB", (pw, ph))
        piece.putdata([pal[v] for v in px])
        out.paste(piece, (x0, 0))
    return out


def feathered(art, base, feather):
    """art over base, fading linearly to base within `feather` pixels of the edges."""
    from PIL import Image
    w, h = art.size
    mask = Image.new("L", (w, h))
    mask.putdata([min(255, 255 * min(x, y, w - 1 - x, h - 1 - y) // feather)
                  for y in range(h) for x in range(w)])
    return Image.composite(art, base, mask)


def replace_title_logo(menu, art, resize=True, feather=0):
    """Write a 288 x 88 RGB picture over the title logo in MENU/KWAMENU.BIN (bytearray).
    feather > 0 blends the outer pixels into the original logo, so the box does not show on the
    background it sits on."""
    from PIL import Image
    for off, _, _ in LOGO_PIECES:
        _, used = lz74.decode_stream(bytes(menu), off)
        if hashlib.sha1(bytes(menu[off:off + used])).hexdigest()[:16] != LOGO_SHA1[off]:
            raise ValueError(f"title logo piece at {off:#x} is not the supported original")
    if art.size != LOGO_SIZE:
        if not resize:
            raise ValueError(f"title logo must be {LOGO_SIZE}, got {art.size}")
        art = art.convert("RGB").resize(LOGO_SIZE, Image.LANCZOS)
    first, _ = lz74.decode_stream(bytes(menu), LOGO_PIECES[0][0])
    pal = palette(first)
    if feather:
        art = feathered(art.convert("RGB"), original_logo(menu), feather)
    rows = quantize(art, pal)
    flat_rows = None
    written = 0
    for off, x0, w in LOGO_PIECES:
        room = slot(bytes(menu), off)
        tim, _ = lz74.decode_stream(bytes(menu), off)
        for source in ("dithered", "flat"):
            src = rows
            if source == "flat":  # dithering compresses badly; fall back to plain nearest colours
                flat_rows = flat_rows or _undithered(art, pal)
                src = flat_rows
            px = bytes(v for r in src for v in r[x0:x0 + w])
            packed = lz74.encode_stream(with_image(tim, px))
            if len(packed) <= room:
                break
        else:
            raise ValueError(f"title logo piece at {off:#x} needs {len(packed)} bytes, slot is {room}")
        menu[off:off + room] = packed + bytes(room - len(packed))
        written += 1
    return {"pieces": written}


# ---- button and tab labels (atlases A-G, docs/graphics_text.md) ---------------------------------
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
LABELS = _ROOT / "tables" / "graphics_ko.tsv"
GALMURI = _ROOT.parent / "galmuri"
BG, TEXT = 4, 1  # cell inside, letters. The original kanji have a 1 px shadow (3); Hangul at 12 px reads
# better without it (compared on the atlas, 2026-10-23)
FONTS = ("Galmuri11", "Galmuri11-Condensed")  # wide first; condensed when the cell is too narrow
ALIAS = {"＆": "&", "－": "-", "・": "·"}


def label_font(root=GALMURI):
    import kfont
    return [kfont.load_bdf(root / f"{n}.bdf") for n in FONTS]


def label_table(path=LABELS):
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        pic, x, y, w, h, ja, ko = line.split("\t")
        out.append({"pic": pic, "x": int(x), "y": int(y), "w": int(w), "h": int(h), "ja": ja, "ko": ko})
    return out


def _glyph(font, ch):
    g = font.get(ch) or font.get(ALIAS.get(ch, ch))
    if g is None:
        raise ValueError(f"font has no glyph for {ch!r}")
    return g


def _advance(g):
    w, _, xo, _ = g["bbx"]
    return xo + w + 1


def text_width(text, font):
    return sum(4 if ch == " " else _advance(_glyph(font, ch)) for ch in text)


def fit(text, fonts, cell_w):
    """The first font in which the text fits inside the cell (the border is 1 px, the letters keep 1 px off it)."""
    for f in fonts:
        if text_width(text, f) <= cell_w - 3:  # at least 1 px between the letters and the border
            return f
    return None


def draw_label(rows, cell, text, fonts, bg=None, ink=None):
    """Clear the inside of a cell (x, y, w, h: top/left border included, bottom border at y+h-2)
    and draw the text centred."""
    bg = BG if bg is None else bg
    ink = TEXT if ink is None else ink
    x0, y0, w, h = cell
    font = fit(text, fonts, w)
    if font is None:
        raise ValueError(f"{text!r} does not fit a {w} px cell")
    for y in range(y0 + 1, y0 + h - 2):
        for x in range(x0 + 1, x0 + w - 1):
            rows[y][x] = bg
    import kfont
    box_h = kfont.hangul_box(font)[1]
    tx = x0 + (w - text_width(text, font) - 1) // 2
    base = y0 + 1 + (h - 3 - box_h + 1) // 2 + box_h  # centre the font's Hangul box in rows y0+1 .. y0+h-3
    for ch in text:
        if ch == " ":
            tx += 4
            continue
        g = _glyph(font, ch)
        gw, gh, xo, yo = g["bbx"]
        top = base - (yo + gh)
        for r, bits in enumerate(g["bits"]):
            for c in range(gw):
                if bits >> (gw - 1 - c) & 1:
                    x, y = tx + xo + c, top + r
                    if y0 < y < y0 + h - 2 and x0 < x < x0 + w - 1:
                        rows[y][x] = ink
        tx += _advance(g)
    return rows


COPIES = _ROOT / "tables" / "graphics_copies.json"


def copies(path=COPIES):
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(tim):
    w, h, px = image(tim)
    bpp = _blocks(tim)[0]
    if bpp != 0:
        raise ValueError("label pictures are 4bpp")
    return [[px[(y * w + x) // 2] >> 4 * (x & 1) & 15 for x in range(w)] for y in range(h)]


def _pack4(rows):
    out = bytearray()
    for r in rows:
        for x in range(0, len(r), 2):
            out.append(r[x] | r[x + 1] << 4)
    return bytes(out)


def replace_labels(files, table=None, groups=None, fonts=None):
    """Redraw every label of tables/graphics_ko.tsv in every copy listed in tables/graphics_copies.json."""
    table = table or label_table()
    groups = groups or copies()
    fonts = fonts or label_font()
    report = {}
    for pic, group in groups.items():
        rows_for = [r for r in table if r["pic"] == pic and r["ko"] != "="]
        for c in group:
            data, off = files[c["file"]], int(c["offset"], 16)
            tim, _ = lz74.decode_stream(bytes(data), off)
            if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != c["pixels_sha1"]:
                raise ValueError(f"{c['file']} {off:#x} is not the supported original picture")
            room = slot(bytes(data), off)
            rows = _rows(tim)
            for r in rows_for:
                draw_label(rows, (r["x"], r["y"], r["w"], r["h"]), r["ko"], fonts)
            packed = lz74.encode_stream(with_image(tim, _pack4(rows)))
            if len(packed) > room:
                raise ValueError(f"{c['file']} {off:#x} needs {len(packed)} bytes, slot is {room}")
            data[off:off + room] = packed + bytes(room - len(packed))
            report[pic] = report.get(pic, 0) + 1
    return report


def draw_text(rows, x, top, text, font, ink):
    """Draw one line with the Hangul box's top at `top`; returns the x after the text."""
    import kfont
    box_h = kfont.hangul_box(font)[1]
    for ch in text:
        if ch == " ":
            x += 4
            continue
        g = _glyph(font, ch)
        gw, gh, xo, yo = g["bbx"]
        y_top = top + box_h - (yo + gh)
        for r, bits in enumerate(g["bits"]):
            for c in range(gw):
                if bits >> (gw - 1 - c) & 1:
                    rows[y_top + r][x + xo + c] = ink
        x += _advance(g)
    return x


# ---- button layout screen (X_HUMAN/X_CONFIG.BIN, group C/D) --------------------------------------
# type A pastes 0xEC0C with the strip 0x10398 on its right, type B pastes 0x105B4 (stored with 0x20
# blocks) with the strip 0x11BEC. A box may run from the main picture into the strip; its text is
# drawn on the joined boxes and cut back into the pictures. Button icons at the left of a box stay.
CONFIG_FILE = "X_HUMAN/X_CONFIG.BIN"
PAD_A, PAD_B, STRIP_A, STRIP_B = 0xEC0C, 0x105B4, 0x10398, 0x11BEC
PAD_SHA1 = {PAD_A: "9d32c7b896d14fe7", PAD_B: "eee92b6cc57c9c1b",
            STRIP_A: "cd9931856ca551b6", STRIP_B: "36497db1f4c4905e"}
PAD_BG, PAD_INK = 4, 6
GRAB = "잡기/놓기"
LIMB = {"右手": "오른손으로 바위", "左手": "왼손으로 바위", "右足": "오른발로 바위", "左足": "왼발로 바위"}
# (segments [(picture, x from, x to)], top row of the box inside, lines), lines: 1 centred or 2
PAD_BOXES = (
    ([(PAD_A, 25, 143)], 46, ("홀드 확인/해제",)), ([(PAD_A, 25, 143)], 66, ("지도 확인/해제",)),
    ([(PAD_A, 172, 218)], 46, ("미사용",)), ([(PAD_A, 172, 218)], 66, ("미사용",)),
    ([(PAD_A, 25, 115)], 181, ("메뉴 표시",)), ([(PAD_A, 45, 115)], 202, ("중심 이동",)),
    ([(PAD_A, 189, 256), (STRIP_A, 0, 45)], 92, (LIMB["右手"], GRAB)),
    ([(PAD_A, 189, 256), (STRIP_A, 0, 45)], 126, (LIMB["左手"], GRAB)),
    ([(PAD_A, 189, 256), (STRIP_A, 0, 45)], 160, (LIMB["右足"], GRAB)),
    ([(PAD_A, 189, 256), (STRIP_A, 0, 45)], 194, (LIMB["左足"], GRAB)),
    ([(PAD_B, 47, 157)], 46, (LIMB["左足"], GRAB)), ([(PAD_B, 47, 156)], 81, (LIMB["左手"], GRAB)),
    ([(PAD_B, 192, 256), (STRIP_B, 0, 46)], 46, (LIMB["右足"], GRAB)),
    ([(PAD_B, 192, 256), (STRIP_B, 0, 46)], 81, (LIMB["右手"], GRAB)),
    ([(PAD_B, 184, 230)], 119, ("미사용",)), ([(PAD_B, 184, 230)], 140, ("미사용",)),
    ([(PAD_B, 184, 256), (STRIP_B, 0, 46)], 161, ("홀드 확인/해제",)),
    ([(PAD_B, 184, 256), (STRIP_B, 0, 46)], 182, ("지도 확인/해제",)),
    ([(PAD_B, 26, 116)], 205, ("메뉴 표시",)), ([(PAD_B, 126, 196)], 205, ("중심 이동",)),
)


def _box_canvas(width, lines, font):
    h = 15 if len(lines) == 1 else 28
    rows = [[PAD_BG] * width for _ in range(h)]
    if any(text_width(t, font) > width - 2 for t in lines):
        raise ValueError(f"{lines} do not fit a {width} px box")
    if len(lines) == 1:
        draw_text(rows, (width - text_width(lines[0], font)) // 2, 2, lines[0], font, PAD_INK)
    else:
        draw_text(rows, 1, 2, lines[0], font, PAD_INK)
        draw_text(rows, width - 1 - text_width(lines[1], font), 15, lines[1], font, PAD_INK)
    return rows


def replace_button_layout(files, fonts=None):
    fonts = fonts or label_font()
    data = files[CONFIG_FILE]
    pics = {}
    for off, sha in PAD_SHA1.items():
        tim, _ = lz74.decode_stream(bytes(data), off)
        if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != sha:
            raise ValueError(f"{CONFIG_FILE} {off:#x} is not the supported original picture")
        pics[off] = (tim, _rows(tim))
    for segments, y, lines in PAD_BOXES:
        width = sum(x1 - x0 for _, x0, x1 in segments)
        cv = _box_canvas(width, lines, fonts[0])
        at = 0
        for pic, x0, x1 in segments:
            rows = pics[pic][1]
            for r, line in enumerate(cv):
                rows[y + r][x0:x1] = line[at:at + x1 - x0]
            at += x1 - x0
    for off in PAD_SHA1:
        room = slot(bytes(data), off)
        tim, rows = pics[off]
        packed = lz74.encode_stream(with_image(tim, _pack4(rows)))
        if len(packed) > room:
            raise ValueError(f"{CONFIG_FILE} {off:#x} needs {len(packed)} bytes, slot is {room}")
        data[off:off + room] = packed + bytes(room - len(packed))
    return {"pictures": len(pics)}
