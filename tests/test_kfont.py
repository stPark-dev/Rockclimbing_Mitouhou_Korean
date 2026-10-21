import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import kfont  # noqa: E402

GALMURI = os.environ.get("GALMURI11_BDF") or str(Path(__file__).resolve().parents[2] / "galmuri" / "Galmuri11.bdf")
FONT_FILE = Path(__file__).resolve().parent.parent / "work" / "files" / "MENU" / "KWAMENU.BIN"


def test_pixels_decode_low_nibble_is_left_pixel():
    g = bytearray(72)
    g[0] = 0x31  # row 0: x0 = 1, x1 = 3
    g[6 * 11 + 5] = 0x20  # row 11: x11 = 2
    px = kfont.pixels(bytes(g))
    assert px[0][0] == 1 and px[0][1] == 3 and px[11][11] == 2
    assert sum(v for row in px for v in row) == 6


def test_encode_is_inverse_of_pixels():
    rows = [[(x * 7 + y * 3) % 4 for x in range(12)] for y in range(12)]
    assert kfont.pixels(kfont.encode(rows)) == rows


def test_encode_rejects_values_above_3():
    rows = [[0] * 12 for _ in range(12)]
    rows[3][4] = 4
    with pytest.raises(ValueError):
        kfont.encode(rows)


def _glyph(bbx, rows):
    w = bbx[0]
    return {"code": 0xAC00, "bbx": bbx, "bits": rows, "rows": []}


def test_render_places_box_top_left_at_ink_value_3():
    # 2x2 glyph at xoff 1, yoff 0 inside an 11x11 box: rows 9-10, cols 1-2
    g = _glyph((2, 2, 1, 0), [0b11, 0b10])
    px = kfont.pixels(kfont.render(g, (11, 11)))
    on = {(x, y) for y in range(12) for x in range(12) if px[y][x]}
    assert on == {(1, 9), (2, 9), (1, 10)}
    assert {px[y][x] for x, y in on} == {3}


def test_render_rejects_box_larger_than_cell():
    with pytest.raises(ValueError):
        kfont.render(_glyph((1, 1, 0, 0), [1]), (13, 11))


def test_render_rejects_pixel_outside_cell():
    with pytest.raises(ValueError):
        kfont.render(_glyph((3, 1, 10, 0), [0b111]), (11, 11))


@pytest.mark.skipif(not Path(GALMURI).exists(), reason="Galmuri11.bdf not available")
def test_galmuri_hangul_fits_like_original_kanji():
    font = kfont.load_bdf(GALMURI)
    box = kfont.hangul_box(font)
    assert box == (11, 11)
    for ch in "가한뷁읆":
        px = kfont.pixels(kfont.render(font[ch], box))
        assert not any(px[11])  # bottom row stays empty, as in the game's kanji
        assert not any(row[11] for row in px)  # 1px gap on the right


@pytest.mark.skipif(not FONT_FILE.exists(), reason="extracted MENU/KWAMENU.BIN not available")
def test_original_kanji_cell_extent():
    data = FONT_FILE.read_bytes()
    assert len(data) >= kfont.GLYPHS * kfont.GLYPH_BYTES
    px = kfont.pixels(data[300 * 72 : 301 * 72])  # 手
    assert max(v for row in px for v in row) == 3
    assert not any(px[11])
