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
