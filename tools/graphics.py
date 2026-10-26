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


# ---- database / training explanation photos (D11): the SELECT menu shot at 128 x 96, 8bpp ------
DB_PHOTO_FILE = "MENU/MENUDB.BIN"
DB_PHOTOS = {0x59B64: "e0c44554d64f4788", 0x6A070: "1ec0935df70ad9bf"}  # 하켄 submenu, 특수 등반 submenu


def replace_db_photos(files, screens):
    """Shrink two 320 x 240 screens (any size of that ratio) into the photos, keeping each CLUT."""
    from PIL import Image
    if len(screens) != len(DB_PHOTOS):
        raise ValueError(f"{len(DB_PHOTOS)} screens are needed, got {len(screens)}")
    data = files[DB_PHOTO_FILE]
    for (off, sha1), screen in zip(DB_PHOTOS.items(), screens):
        tim, _ = lz74.decode_stream(bytes(data), off)
        if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != sha1:
            raise ValueError(f"{DB_PHOTO_FILE} {off:#x} is not the supported original picture")
        w, h, _ = image(tim)
        pal = palette(tim)
        small = screen.convert("RGB").resize((w, h), Image.LANCZOS)
        room = slot(bytes(data), off)
        for rows in (quantize(small, pal), _undithered(small, pal)):  # dithering may not fit
            packed = lz74.encode_stream(with_image(tim, bytes(v for r in rows for v in r)))
            if len(packed) <= room:
                break
        else:
            raise ValueError(f"{DB_PHOTO_FILE} {off:#x} needs {len(packed)} bytes, slot is {room}")
        data[off:off + room] = packed + bytes(room - len(packed))
    return {"photos": len(screens)}


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
        if not any(r["pic"] == pic for r in table):
            continue  # drawn by another routine (SMALL_GLYPHS)
        for c in group:
            data, off = files[c["file"]], int(c["offset"], 16)
            tim, _ = lz74.decode_stream(bytes(data), off)
            if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != c["pixels_sha1"]:
                raise ValueError(f"{c['file']} {off:#x} is not the supported original picture")
            room = slot(bytes(data), off)
            rows = _rows(tim)
            for r in rows_for:
                split = SPLIT_LABELS.get((pic, r["x"], r["y"]))
                if split:
                    draw_split_label(rows, (r["x"], r["y"], r["w"], r["h"]), split, fonts)
                else:
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


# ---- small 8 px letters (group G: the time frame on the mountain screen, SUZU/*/SU_IG_*.BIN) -----
# white letters (0) with a dark outline (1) on the window colour (2); Galmuri7 Hangul is 7 x 7.
SMALL_FONT = "Galmuri7"
SMALL_BG, SMALL_INK, SMALL_EDGE = 2, 0, 1
SMALL_GLYPHS = {
    "G": {"clear": ((26, 226, 37, 247), (63, 226, 73, 247), (86, 226, 99, 247), (112, 226, 124, 247)),
          "glyphs": ((27, 227, "예"), (27, 237, "실"), (64, 227, "일"), (64, 237, "일"),
                     (88, 227, "시"), (88, 237, "시"), (113, 227, "분"), (113, 237, "분"))},
    # move scene: the same box drawn 18 px further left (SU_IG 0x1842C, SU_MG 0x1E5B4)
    "G2": {"clear": ((8, 226, 19, 247), (45, 226, 55, 247), (67, 226, 81, 247), (94, 226, 106, 247)),
           "glyphs": ((9, 227, "예"), (9, 237, "실"), (46, 227, "일"), (46, 237, "일"),
                      (70, 227, "시"), (70, 237, "시"), (95, 227, "분"), (95, 237, "분"))},
}


def _small_glyph(rows, x, y, ch, font):
    g = _glyph(font, ch)
    gw, gh, xo, yo = g["bbx"]
    ox = x + (9 - gw) // 2
    pts = [(ox + xo + c, y + 1 + (7 - (yo + gh)) + r) for r, bits in enumerate(g["bits"])
           for c in range(gw) if bits >> (gw - 1 - c) & 1]
    for px, py in pts:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if rows[py + dy][px + dx] == SMALL_BG:
                    rows[py + dy][px + dx] = SMALL_EDGE
    for px, py in pts:
        rows[py][px] = SMALL_INK


def replace_small_glyphs(files, root=GALMURI):
    import kfont
    font = kfont.load_bdf(root / f"{SMALL_FONT}.bdf")
    groups = copies()
    report = {}
    for pic, spec in SMALL_GLYPHS.items():
        for c in groups[pic]:
            data, off = files[c["file"]], int(c["offset"], 16)
            tim, _ = lz74.decode_stream(bytes(data), off)
            if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != c["pixels_sha1"]:
                raise ValueError(f"{c['file']} {off:#x} is not the supported original picture")
            rows = _rows(tim)
            for x0, y0, x1, y1 in spec["clear"]:
                for y in range(y0, y1):
                    for x in range(x0, x1):
                        if rows[y][x] in (SMALL_INK, SMALL_EDGE):
                            rows[y][x] = SMALL_BG
            for x, y, ch in spec["glyphs"]:
                _small_glyph(rows, x, y, ch, font)
            room = slot(bytes(data), off)
            packed = lz74.encode_stream(with_image(tim, _pack4(rows)))
            if len(packed) > room:
                raise ValueError(f"{c['file']} {off:#x} needs {len(packed)} bytes, slot is {room}")
            data[off:off + room] = packed + bytes(room - len(packed))
            report[pic] = report.get(pic, 0) + 1
    return report


# ---- free text regions (group F: climbing screen parts in X/X1.BIN) ------------------------------
# (x0, y0, x1, y1, fill, text, font, ink, shade, align): the region is filled, the text drawn with
# its Hangul box top at y0 (+1 for 8 px rows), shade right of each letter pixel when not None.
HUD_FILE, HUD_OFF, HUD_PIXELS_SHA1 = "X/X1.BIN", 0xFD9C, "a14e7efa578e3358"
HUD_REGIONS = (
    (2, 98, 30, 126, 0, "기술", "Galmuri11-Bold", 2, 3, "centre"),       # 技 icon tile
    (162, 130, 191, 141, 13, "경사", "Galmuri11", 1, 3, "left"),    # 傾斜 label (rows 130-140)
    (216, 152, 248, 160, 11, "노랑", "Galmuri7", 1, None, "right"),  # イエロー + アラーム
    (216, 160, 248, 168, 11, "경보", "Galmuri7", 1, None, "left"),
    (216, 168, 240, 176, 11, "빨강", "Galmuri7", 1, None, "right"),  # レッド (+ アラーム)
    (216, 176, 232, 184, 11, "남은", "Galmuri7", 1, None, "left"),   # あと ○分 ○秒 pieces
    (232, 176, 240, 184, 11, "초", "Galmuri7", 1, None, "left"),
    (240, 176, 248, 184, 11, "분", "Galmuri7", 1, None, "left"),
    (160, 232, 224, 240, 11, "노랑 경보", "Galmuri7", 1, None, "left"),
    (160, 240, 216, 248, 11, "빨강 경보", "Galmuri7", 1, None, "left"),
    (160, 248, 176, 256, 11, "남은", "Galmuri7", 1, None, "left"),
    (184, 248, 192, 256, 11, "분", "Galmuri7", 1, None, "left"),
    (208, 248, 218, 256, 11, "초", "Galmuri7", 1, None, "left"),
)


def draw_region(rows, region, fonts_by_name):
    x0, y0, x1, y1, fill, text, fname, ink, shade, align = region
    font = fonts_by_name[fname]
    import kfont
    box_h = kfont.hangul_box(font)[1]
    w = text_width(text, font)
    if w > x1 - x0 or box_h > y1 - y0:
        raise ValueError(f"{text!r} does not fit region {region[:4]}")
    for y in range(y0, y1):
        for x in range(x0, x1):
            rows[y][x] = fill
    x = {"left": x0, "right": x1 - w, "centre": x0 + (x1 - x0 - w) // 2}[align]
    top = y0 + (y1 - y0 - box_h) // 2
    canvas = [r[:] for r in rows]
    draw_text(canvas, x, top, text, font, ink)
    for y in range(y0, y1):
        for xx in range(x0, x1):
            if canvas[y][xx] == ink and rows[y][xx] != ink:
                rows[y][xx] = ink
                if shade is not None:
                    for dx, dy in ((1, 0), (0, 1), (1, 1)):
                        nx, ny = xx + dx, y + dy
                        if x0 <= nx < x1 and y0 <= ny < y1 and canvas[ny][nx] != ink:
                            rows[ny][nx] = shade
    return rows


def replace_hud(files, root=GALMURI):
    import kfont
    names = {r[6] for r in HUD_REGIONS}
    fonts = {n: kfont.load_bdf(root / f"{n}.bdf") for n in names}
    data = files[HUD_FILE]
    tim, _ = lz74.decode_stream(bytes(data), HUD_OFF)
    if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != HUD_PIXELS_SHA1:
        raise ValueError(f"{HUD_FILE} {HUD_OFF:#x} is not the supported original picture")
    rows = _rows(tim)
    for r in HUD_REGIONS:
        draw_region(rows, r, fonts)
    room = slot(bytes(data), HUD_OFF)
    packed = lz74.encode_stream(with_image(tim, _pack4(rows)))
    if len(packed) > room:
        raise ValueError(f"{HUD_FILE} {HUD_OFF:#x} needs {len(packed)} bytes, slot is {room}")
    data[HUD_OFF:HUD_OFF + room] = packed + bytes(room - len(packed))
    return {"regions": len(HUD_REGIONS)}


# ---- Alps history title over the photo (group E: MENU/KWAMENU.BIN 0x26DC8, 4bpp sepia) -----------
ALPS_FILE, ALPS_OFF, ALPS_SHA1 = "MENU/KWAMENU.BIN", 0x26DC8, "c92fcd8eec2a1b3f"
ALPS_BOX = (117, 22, 237, 39)  # the title and its shadow sit on the sky band
ALPS_TEXT, ALPS_FONT = "알프스 등반사", "Galmuri14"
ALPS_LETTERS = {2, 8, 9, 10, 11, 12, 13, 14, 15}  # dark letter and shadow colours
ALPS_INK, ALPS_EDGE = 15, 12


def replace_alps_title(files, root=GALMURI):
    import kfont
    font = kfont.load_bdf(root / f"{ALPS_FONT}.bdf")
    data = files[ALPS_FILE]
    tim, _ = lz74.decode_stream(bytes(data), ALPS_OFF)
    if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != ALPS_SHA1:
        raise ValueError(f"{ALPS_FILE} {ALPS_OFF:#x} is not the supported original picture")
    rows = _rows(tim)
    x0, y0, x1, y1 = ALPS_BOX
    for y in range(y0, y1):  # sky: take the nearest sky pixel of the same parity in the row
        row = rows[y]
        sky = [x for x in range(x0 - 8, x1 + 1) if row[x] not in ALPS_LETTERS]
        for x in range(x0, x1):
            if row[x] in ALPS_LETTERS:
                src = min((s for s in sky if (s - x) % 2 == 0), key=lambda s: abs(s - x))
                row[x] = rows[y][src]
    w = text_width(ALPS_TEXT, font) + 1
    box_h = kfont.hangul_box(font)[1]
    tx, ty = x1 - 3 - w, y0 + (y1 - y0 - box_h - 1) // 2
    canvas = [[None] * len(rows[0]) for _ in rows]
    draw_text(canvas, tx, ty, ALPS_TEXT, font, 1)
    draw_text(canvas, tx + 1, ty, ALPS_TEXT, font, 1)  # one pixel bolder, like the original
    for y in range(y0, y1):
        for x in range(x0, x1):
            if canvas[y][x]:
                if not canvas[y + 1][x + 1]:
                    rows[y + 1][x + 1] = ALPS_EDGE  # shadow down-right
    for y in range(y0, y1):
        for x in range(x0, x1):
            if canvas[y][x]:
                rows[y][x] = ALPS_INK
    room = slot(bytes(data), ALPS_OFF)
    packed = lz74.encode_stream(with_image(tim, _pack4(rows)))
    if len(packed) > room:
        raise ValueError(f"{ALPS_FILE} {ALPS_OFF:#x} needs {len(packed)} bytes, slot is {room}")
    data[ALPS_OFF:ALPS_OFF + room] = packed + bytes(room - len(packed))
    return {"title": 1}


# Cells the game shows partly covered: DB 「フリークライミング」 = the フェースクライミング cell with its
# first 24 px covered by the フリー piece (pixel-matched on screen, 2026-10-23). The cell keeps
# 「페이스」 inside the covered part and 「등반」 after it: alone 「페이스 등반」, covered 「프리 등반」.
FREE_COVER = 24
SPLIT_LABELS = {("B", 0, 160): (("페이스", 1, 1), ("등반", 0, FREE_COVER + 4)),  # (text, font index, x)
                # pitch submenu: the game prints the pitch number over the first 13 px of
                # 「このピッチの概要」 (「1のピッチの概要」), so the Korean leaves that part empty
                ("H", 72, 144): (("피치 개요", 0, 15),),
                # SELECT menu counts: the game prints the number over the left of the 枚/本 cells,
                # whose glyphs sit in columns 26-37
                ("I", 160, 128): (("개", 0, 26),),
                ("I", 200, 128): (("개", 0, 26),)}


def draw_split_label(rows, cell, parts, fonts):
    x0, y0, w, h = cell
    for y in range(y0 + 1, y0 + h - 2):
        for x in range(x0 + 1, x0 + w - 1):
            rows[y][x] = BG
    import kfont
    for text, fi, x in parts:
        font = fonts[fi]
        box_h = kfont.hangul_box(font)[1]
        draw_text(rows, x0 + x, y0 + 1 + (h - 3 - box_h + 1) // 2, text, font, TEXT)
    return rows


# ---- weather icons (group J: X/X1.BIN 0xD764, 8 x 2 icons of 32 px) -------------------------------
# The label sits on the bottom-left of each icon: white (11) with a black outline (0), rows 22-29.
# It is replaced by a black band (0) holding the Korean label in white; the band covers the old label and
# row 21 above it, so art in the label colour (the snow of 날린눈) does not touch the letter tops.
WEATHER_FILE, WEATHER_OFF, WEATHER_SHA1 = "X/X1.BIN", 0xD764, "b5624501bb775231"
WEATHER = ("맑음", "흐림", "안개", "진눈비", "날린눈", "폭풍설", "눈보라", "우박", "벼락", "강풍")
WEATHER_ROWS, WEATHER_INK, WEATHER_BAND = (21, 30), 11, 0  # band rows; the letters start one row lower
# the move scene keeps its own はれ·くもり icons (copies group J2), black there is index 2 (0 is clear)
MOVE_WEATHER_BAND = 2


def _weather_labels(rows, texts, font, band):
    y0, y1 = WEATHER_ROWS
    for i, text in enumerate(texts):
        ix, iy = (i % 8) * 32, (i // 8) * 32
        old_end = max(x for x in range(ix + 2, ix + 30) for y in range(iy + y0, iy + y1) if rows[y][x] == band)
        w = text_width(text, font)
        if w > 26:
            raise ValueError(f"{text!r} is wider than the icon")
        end = min(ix + 29, max(old_end, ix + 3 + w))
        for y in range(iy + y0, iy + y1):
            for x in range(ix + 2, end + 1):
                rows[y][x] = band
        draw_text(rows, ix + 3, iy + y0 + 1, text, font, WEATHER_INK)


def _replace_weather_picture(data, off, sha1, texts, font, band, name):
    tim, _ = lz74.decode_stream(bytes(data), off)
    if hashlib.sha1(image(tim)[2]).hexdigest()[:16] != sha1:
        raise ValueError(f"{name} {off:#x} is not the supported original picture")
    rows = _rows(tim)
    _weather_labels(rows, texts, font, band)
    room = slot(bytes(data), off)
    packed = lz74.encode_stream(with_image(tim, _pack4(rows)))
    if len(packed) > room:
        raise ValueError(f"{name} {off:#x} needs {len(packed)} bytes, slot is {room}")
    data[off:off + room] = packed + bytes(room - len(packed))


def replace_weather(files, root=GALMURI):
    import kfont
    font = kfont.load_bdf(root / "Galmuri7.bdf")
    _replace_weather_picture(files[WEATHER_FILE], WEATHER_OFF, WEATHER_SHA1, WEATHER, font, WEATHER_BAND, WEATHER_FILE)
    move = copies()["J2"]
    for c in move:
        _replace_weather_picture(files[c["file"]], int(c["offset"], 16), c["pixels_sha1"], WEATHER[:2], font,
                                 MOVE_WEATHER_BAND, c["file"])
    return {"icons": len(WEATHER), "move_icons": len(move)}
