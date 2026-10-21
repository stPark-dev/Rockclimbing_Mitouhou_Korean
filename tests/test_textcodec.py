import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import textcodec as tc  # noqa: E402

KWAMENU = Path(__file__).resolve().parent.parent / "work" / "files" / "KWAMENU.BIN"

# △（Ｒ１）ボタン（右手）  as stored at KWAMENU.BIN 0x17928 (docs/survey.md §3.2)
SAMPLE = bytes.fromhex("f3ff1b34021cebb3d11bf207f03d1c")
SAMPLE_GLYPHS = [1262, 26, 51, 1, 27, 234, 178, 208, 26, 758, 300, 27]


def test_decode_known_bytes():
    assert tc.decode(SAMPLE) == [("g", k) for k in SAMPLE_GLYPHS]


def test_encode_known_glyphs():
    assert tc.encode([("g", k) for k in SAMPLE_GLYPHS]) == SAMPLE


@pytest.mark.parametrize("k,b", [(0, "01"), (31, "20"), (238, "ef"), (239, "f000"), (300, "f03d"), (1347, "f454")])
def test_code_boundaries(k, b):
    assert tc.code(k) == bytes.fromhex(b)
    assert tc.decode(bytes.fromhex(b)) == [("g", k)]


def test_controls_round_trip():
    raw = bytes.fromhex("fd2021fe5f60ff")
    toks = tc.decode(raw)
    assert toks == [("page",), ("g", 31), ("g", 32), ("nl",), ("g", 94), ("g", 95), ("end",)]
    assert tc.encode(toks) == raw


@pytest.mark.parametrize("k", [-1, 1348])
def test_glyph_out_of_font_is_refused(k):
    with pytest.raises(ValueError):
        tc.code(k)


@pytest.mark.parametrize("raw", ["00", "f5", "fc", "f0", "f455"])
def test_unknown_or_truncated_bytes_are_refused(raw):
    with pytest.raises(ValueError):
        tc.decode(bytes.fromhex(raw))


def test_read_page_treats_ff_after_lead_byte_as_glyph():
    raw = bytes.fromhex("fdf3ff20ff00")  # △。 then end; F3 FF is △, not the end marker
    toks, end = tc.read_page(raw, 0)
    assert toks == [("page",), ("g", 1262), ("g", 31), ("end",)]
    assert end == 5


def test_read_page_without_end_raises():
    with pytest.raises(ValueError):
        tc.read_page(bytes.fromhex("fd2021"), 0)


@pytest.mark.skipif(not KWAMENU.exists(), reason="extracted KWAMENU.BIN not available")
def test_corpus_database_page_round_trips():
    data = KWAMENU.read_bytes()
    start = 0x1790C
    _, end = tc.read_page(data, start)
    page = data[start:end]
    assert end == 0x17975  # the page holding the four button lines ends after 。 FE FF
    assert tc.encode(tc.decode(page)) == page
    assert tc.decode(page)[0] == ("page",) and tc.decode(page)[-1] == ("end",)
