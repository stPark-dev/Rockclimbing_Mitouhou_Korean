import struct
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import graphics  # noqa: E402
import lz74  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MENU = ROOT / "work" / "files" / "MENU" / "KWAMENU.BIN"
needs_files = pytest.mark.skipif(not MENU.exists(), reason="extracted disc files are not in the repository")


def test_tim_image_round_trip_8bpp():
    clut = struct.pack("<256H", *range(256))
    pix = bytes(range(256)) * 2  # 16 x 32? use 32 x 16
    tim = (struct.pack("<II", 0x10, 9) + struct.pack("<IHHHH", 12 + 512, 0, 480, 256, 1) + clut
           + struct.pack("<IHHHH", 12 + len(pix), 512, 0, 16, 16) + pix)
    w, h, data = graphics.image(tim)
    assert (w, h) == (32, 16) and data == pix
    assert graphics.palette(tim)[3] == (24, 0, 0)  # 0x0003 -> red 3<<3
    new = graphics.with_image(tim, bytes(len(pix)))
    assert graphics.image(new)[2] == bytes(len(pix)) and new[:20 + 512] == tim[:20 + 512]


@needs_files
def test_title_logo_replaces_three_pieces_in_place():
    menu = bytearray(MENU.read_bytes())
    before = bytes(menu)
    first, _ = lz74.decode_stream(before, graphics.LOGO_PIECES[0][0])
    art = Image.new("RGB", (288, 88), graphics.palette(first)[30])  # a colour of the shared CLUT
    report = graphics.replace_title_logo(menu, art)
    assert len(menu) == len(before)
    changed = [i for i in range(len(menu)) if menu[i] != before[i]]
    lo = min(off for off, _, _ in graphics.LOGO_PIECES)
    hi = max(off + slot for off, _, slot in ((o, x, graphics.slot(before, o)) for o, x, _ in graphics.LOGO_PIECES))
    assert changed and lo <= changed[0] and changed[-1] < hi
    for off, x0, w in graphics.LOGO_PIECES:
        old, _ = lz74.decode_stream(before, off)
        new, used = lz74.decode_stream(bytes(menu), off)
        assert used <= graphics.slot(before, off)
        assert graphics.palette(new) == graphics.palette(old)  # CLUT shared with the background is kept
        nw, nh, px = graphics.image(new)
        assert (nw, nh) == (w, 88) and len(set(px)) == 1
    assert report["pieces"] == 3


@needs_files
def test_title_logo_refuses_wrong_size_and_unsupported_disc():
    menu = bytearray(MENU.read_bytes())
    with pytest.raises(ValueError):
        graphics.replace_title_logo(menu, Image.new("RGB", (100, 50)), resize=False)
    menu[graphics.LOGO_PIECES[0][0]] ^= 0xFF
    with pytest.raises(ValueError):
        graphics.replace_title_logo(menu, Image.new("RGB", (288, 88)))


@needs_files
def test_title_logo_edges_fade_into_the_original_picture():
    menu = bytearray(MENU.read_bytes())
    before = bytes(menu)
    first, _ = lz74.decode_stream(before, graphics.LOGO_PIECES[0][0])
    pal = graphics.palette(first)
    graphics.replace_title_logo(menu, Image.new("RGB", (288, 88), pal[30]), feather=8)
    old, _ = lz74.decode_stream(before, graphics.LOGO_PIECES[0][0])
    new, _ = lz74.decode_stream(bytes(menu), graphics.LOGO_PIECES[0][0])
    w, h, po = graphics.image(old)
    _, _, pn = graphics.image(new)
    row = (h - 1) * w
    diff = sum(sum(abs(a - b) for a, b in zip(pal[pn[row + x]], pal[po[row + x]])) for x in range(w)) / w
    assert diff < 40  # bottom row stays the original picture (dithering may pick a neighbouring colour)
    assert pn[44 * w + 64] == 30  # the middle is the new picture


def test_label_cells_keep_their_border_and_hold_the_text():
    w, h = 64, 32
    rows = [[1 if y in (0, 14) or x == 0 else 4 for x in range(w)] for y in range(16)] + [[5] * w for _ in range(16)]
    font = graphics.label_font()
    graphics.draw_label(rows, (0, 0, 31, 16), "결정", font)
    assert all(rows[0][x] == 1 and rows[14][x] == 1 for x in range(31))  # top and bottom border
    assert all(rows[y][0] == 1 for y in range(15))
    ink = [(x, y) for y in range(16) for x in range(31) if rows[y][x] == graphics.TEXT and 0 < y < 14 and x > 0]
    assert ink and min(x for x, _ in ink) >= 2 and max(x for x, _ in ink) <= 29
    assert rows[20][5] == 5  # outside the cell untouched
    with pytest.raises(ValueError):
        graphics.draw_label(rows, (0, 0, 15, 16), "다음 스테이지 개요", font)


def test_label_table_rows_all_fit_their_cells():
    font = graphics.label_font()
    for row in graphics.label_table():
        if row["ko"] != "=":
            assert graphics.fit(row["ko"], font, row["w"]) is not None, row


def test_label_glyphs_are_not_clipped():
    rows = [[1 if y in (0, 14) or x == 0 else 4 for x in range(64)] for y in range(16)]
    font = graphics.label_font()
    graphics.draw_label(rows, (0, 0, 64, 16), "릉", font)  # tall syllable with a bottom consonant
    ink_rows = [y for y in range(1, 14) if graphics.TEXT in rows[y][1:63]]  # inside (border is also 1)
    import kfont
    g = font[0]["릉"]
    assert ink_rows[-1] - ink_rows[0] + 1 == g["bbx"][1]  # first to last bitmap row reached the cell


FILES = ROOT / "work" / "files"


@needs_files
def test_label_pictures_are_redrawn_in_every_copy():
    files = {}
    for group in graphics.copies().values():
        for c in group:
            files.setdefault(c["file"], bytearray((FILES / c["file"]).read_bytes()))
    before = {n: bytes(d) for n, d in files.items()}
    report = graphics.replace_labels(files)
    assert report == {"A": 15, "B": 2, "H": 13, "H1": 13, "I": 1}
    for pic, group in graphics.copies().items():
        drawn = set()
        for c in group:
            off = int(c["offset"], 16)
            tim, used = lz74.decode_stream(bytes(files[c["file"]]), off)
            assert used <= graphics.slot(before[c["file"]], off)
            old, _ = lz74.decode_stream(before[c["file"]], off)
            assert graphics.palette(tim) == graphics.palette(old) and tim[:20] == old[:20]
            drawn.add(graphics.image(tim)[2])
        if pic == "A":
            assert len(drawn) == 1  # every copy of the button atlas ends up identical
    with pytest.raises(ValueError):
        graphics.replace_labels(files)  # already replaced: the originals are gone


@needs_files
def test_label_cells_match_the_borders_in_the_pictures():
    # every table cell starts on a left border (or the cell inside) and ends on a right border
    files = {c["file"]: (FILES / c["file"]).read_bytes() for g in graphics.copies().values() for c in g}
    first = {pic: g[0] for pic, g in graphics.copies().items()}
    for r in graphics.label_table():
        c = first[r["pic"]]
        tim, _ = lz74.decode_stream(files[c["file"]], int(c["offset"], 16))
        rows = graphics._rows(tim)
        inside = rows[r["y"] + 1]
        right = r["x"] + r["w"] - 1
        if right == len(inside) - 1:  # the cell runs past the picture's right edge (フリー)
            continue
        assert inside[right] == 1 and inside[right - 1] == graphics.BG, r  # right border, then the inside
        shared = any(o["pic"] == r["pic"] and o["y"] == r["y"] and o["x"] == right for o in graphics.label_table())
        assert shared or right + 1 >= len(inside) or inside[right + 1] != graphics.BG, r  # nothing of the cell past it


@needs_files
def test_button_layout_boxes_continue_across_the_strip():
    files = {graphics.CONFIG_FILE: bytearray((FILES / graphics.CONFIG_FILE).read_bytes())}
    before = bytes(files[graphics.CONFIG_FILE])
    assert graphics.replace_button_layout(files) == {"pictures": 4}
    data = bytes(files[graphics.CONFIG_FILE])
    pics = {o: graphics._rows(lz74.decode_stream(data, o)[0]) for o in graphics.PAD_SHA1}
    old = {o: graphics._rows(lz74.decode_stream(before, o)[0]) for o in graphics.PAD_SHA1}
    pa, pb = pics[graphics.PAD_A], pics[graphics.PAD_B]
    assert pa[100][175:189] == old[graphics.PAD_A][100][175:189]  # type A button icons kept
    assert pb[50][173:193] == old[graphics.PAD_B][50][173:193]  # type B L2/R2 icons kept
    assert pa[0] == old[graphics.PAD_A][0] and pb[45] == old[graphics.PAD_B][45]  # frames kept
    for strip, y in ((graphics.STRIP_A, 92), (graphics.STRIP_B, 46), (graphics.STRIP_B, 161)):
        rows = pics[strip]
        assert graphics.PAD_INK in sum((rows[y + r][0:45] for r in range(15)), []), (hex(strip), y)
    for o in graphics.PAD_SHA1:
        assert lz74.decode_stream(data, o)[1] <= graphics.slot(before, o)


@needs_files
def test_button_layout_clears_every_old_glyph_next_to_the_icons():
    files = {graphics.CONFIG_FILE: bytearray((FILES / graphics.CONFIG_FILE).read_bytes())}
    graphics.replace_button_layout(files)
    pb = graphics._rows(lz74.decode_stream(bytes(files[graphics.CONFIG_FILE]), graphics.PAD_B)[0])
    # between the L2 icon (ends at x 46) and the first Korean letter nothing of the old 左 is left
    assert all(pb[y][47] == graphics.PAD_BG for y in range(48, 72))


@needs_files
def test_small_glyphs_of_the_time_frame_are_replaced_in_every_copy():
    group = graphics.copies()["G"]
    files = {c["file"]: bytearray((FILES / c["file"]).read_bytes()) for c in group}
    before = {n: bytes(d) for n, d in files.items()}
    assert graphics.replace_small_glyphs(files) == {"G": 95}
    seen = set()
    for c in group:
        off = int(c["offset"], 16)
        tim, used = lz74.decode_stream(bytes(files[c["file"]]), off)
        assert used <= graphics.slot(before[c["file"]], off)
        old = graphics._rows(lz74.decode_stream(before[c["file"]], off)[0])
        rows = graphics._rows(tim)
        seen.add(graphics.image(tim)[2])
        assert rows[:220] == old[:220] and rows[247:] == old[247:]  # only the time labels change
        assert rows[227:236] != old[227:236]
    assert len(seen) == 1


@needs_files
def test_hud_regions_are_redrawn_inside_their_boxes():
    files = {graphics.HUD_FILE: bytearray((FILES / graphics.HUD_FILE).read_bytes())}
    before = bytes(files[graphics.HUD_FILE])
    assert graphics.replace_hud(files) == {"regions": len(graphics.HUD_REGIONS)}
    new = graphics._rows(lz74.decode_stream(bytes(files[graphics.HUD_FILE]), graphics.HUD_OFF)[0])
    old = graphics._rows(lz74.decode_stream(before, graphics.HUD_OFF)[0])
    inside = {(x, y) for x0, y0, x1, y1, *_ in graphics.HUD_REGIONS for y in range(y0, y1) for x in range(x0, x1)}
    changed = {(x, y) for y in range(len(new)) for x in range(len(new[0])) if new[y][x] != old[y][x]}
    assert changed and changed <= inside
    assert lz74.decode_stream(bytes(files[graphics.HUD_FILE]), graphics.HUD_OFF)[1] <= graphics.slot(before, graphics.HUD_OFF)


@needs_files
def test_alps_title_is_redrawn_only_inside_its_box():
    files = {graphics.ALPS_FILE: bytearray((FILES / graphics.ALPS_FILE).read_bytes())}
    before = bytes(files[graphics.ALPS_FILE])
    assert graphics.replace_alps_title(files) == {"title": 1}
    new = graphics._rows(lz74.decode_stream(bytes(files[graphics.ALPS_FILE]), graphics.ALPS_OFF)[0])
    old = graphics._rows(lz74.decode_stream(before, graphics.ALPS_OFF)[0])
    x0, y0, x1, y1 = graphics.ALPS_BOX
    changed = {(x, y) for y in range(len(new)) for x in range(len(new[0])) if new[y][x] != old[y][x]}
    assert changed and all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in changed)


def test_free_climbing_button_reads_through_the_covered_cell():
    # the game draws the フェースクライミング cell and covers its first 24 px with the フリー piece
    rows = [[1 if y in (0, 14) or x == 0 else 4 for x in range(80)] for y in range(16)]
    graphics.draw_split_label(rows, (0, 0, 79, 16), graphics.SPLIT_LABELS[("B", 0, 160)], graphics.label_font())
    ink = [x for y in range(1, 14) for x in range(80) if rows[y][x] == graphics.TEXT and x > 0]
    head = [x for x in ink if x < graphics.FREE_COVER]
    tail = [x for x in ink if x >= graphics.FREE_COVER]
    assert head and max(head) <= graphics.FREE_COVER - 1 and tail and min(tail) >= graphics.FREE_COVER + 3


@needs_files
def test_weather_labels_stay_inside_the_icon_bottoms():
    files = {graphics.WEATHER_FILE: bytearray((FILES / graphics.WEATHER_FILE).read_bytes())}
    before = bytes(files[graphics.WEATHER_FILE])
    assert graphics.replace_weather(files) == {"icons": 10}
    new = graphics._rows(lz74.decode_stream(bytes(files[graphics.WEATHER_FILE]), graphics.WEATHER_OFF)[0])
    old = graphics._rows(lz74.decode_stream(before, graphics.WEATHER_OFF)[0])
    for y in range(len(new)):
        for x in range(len(new[0])):
            if new[y][x] != old[y][x]:
                assert 22 <= y % 32 < 30 and 2 <= x % 32 < 30 and (y // 32) * 8 + x // 32 < 10
