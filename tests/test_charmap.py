import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import charmap  # noqa: E402
import textcodec as tc  # noqa: E402

TABLE = Path(__file__).resolve().parent.parent / "tables" / "charmap.tsv"
KWAMENU = Path(__file__).resolve().parent.parent / "work" / "files" / "KWAMENU.BIN"


def test_table_covers_every_glyph_once():
    cm = charmap.load(TABLE)
    assert sorted(cm) == list(range(tc.GLYPHS))
    assert {s for _, s in cm.values()} <= {"visual", "context", "unverified"}


@pytest.mark.parametrize("k,c", [(0, "０"), (31, "。"), (86, "あ"), (243, "ー"), (300, "手"), (758, "右"), (1262, "△")])
def test_glyphs_confirmed_on_screen(k, c):
    # characters seen uploaded to VRAM on the database screen (docs/survey.md §3)
    assert charmap.load(TABLE)[k][0] == c


def test_load_rejects_duplicates_and_gaps(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("0\ta\tvisual\n0\tb\tvisual\n")
    with pytest.raises(ValueError):
        charmap.load(p, size=2)
    p.write_text("0\ta\tvisual\n")
    with pytest.raises(ValueError):
        charmap.load(p, size=2)


def test_text_renders_tokens():
    cm = {0: ("あ", "visual"), 1: ("い", "visual")}
    assert charmap.text([("page",), ("g", 0), ("nl",), ("g", 1), ("end",)], cm) == "あ\nい"


@pytest.mark.skipif(not KWAMENU.exists(), reason="extracted KWAMENU.BIN not available")
def test_corpus_database_line_reads_as_japanese():
    data = KWAMENU.read_bytes()
    toks, _ = tc.read_page(data, 0x1790C)
    first = charmap.text(toks, charmap.load(TABLE)).split("\n")[0]
    assert first == "まず、移動しようと思う手や足を選びます。"
