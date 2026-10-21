import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import kfont  # noqa: E402
import poc_db  # noqa: E402
import textcodec as tc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GALMURI = os.environ.get("GALMURI11_BDF") or str(ROOT.parent / "galmuri" / "Galmuri11.bdf")
FILES = ROOT / "work" / "files"
need_galmuri = pytest.mark.skipif(not Path(GALMURI).exists(), reason="Galmuri11.bdf not available")
need_files = pytest.mark.skipif(not (FILES / "KWAMENU.BIN").exists(), reason="extracted files not available")


def test_line_fills_the_original_span_exactly():
    line = poc_db.korean_line()
    assert len(line) == poc_db.LINE_END - poc_db.LINE_START
    toks = tc.decode(line)
    assert all(t[0] == "g" for t in toks)
    # both code widths are exercised
    assert any(k <= 0xEE for _, k in toks) and any(k > 0xEE for _, k in toks)
    # no wider than the original line (20 glyphs)
    assert len(toks) <= 20


def test_every_slot_is_used_and_distinct():
    slots = [k for _, k in poc_db.SLOTS]
    assert len(set(slots)) == len(slots)
    used = {k for _, k in tc.decode(poc_db.korean_line())}
    assert used == set(slots) | {31}  # 。 keeps its original glyph


@need_files
def test_patch_text_changes_only_the_line():
    src = (FILES / "KWAMENU.BIN").read_bytes()
    out = poc_db.patch_text(src)
    assert len(out) == len(src)
    diff = [i for i in range(len(src)) if src[i] != out[i]]
    assert diff and min(diff) >= poc_db.LINE_START and max(diff) < poc_db.LINE_END
    toks, end = tc.read_page(out, 0x1790C)
    assert end == 0x17975


@need_files
def test_patch_text_refuses_unexpected_source():
    src = bytearray((FILES / "KWAMENU.BIN").read_bytes())
    src[poc_db.LINE_START] ^= 1
    with pytest.raises(ValueError):
        poc_db.patch_text(bytes(src))


@need_files
@need_galmuri
def test_patch_font_changes_only_listed_slots():
    src = (FILES / "MENU" / "KWAMENU.BIN").read_bytes()
    out = poc_db.patch_font(src, kfont.load_bdf(GALMURI))
    changed = {i // 72 for i in range(len(src)) if src[i] != out[i]}
    assert changed <= {k for _, k in poc_db.SLOTS}
    blank = [k for ch, k in poc_db.SLOTS if ch == " "][0]
    assert out[blank * 72 : blank * 72 + 72] == bytes(72)


def _exe_with_table(table):
    exe = bytearray(poc_db.WIDTH_OFFSET + len(table) + 16)
    exe[poc_db.WIDTH_OFFSET : poc_db.WIDTH_OFFSET + len(table)] = table
    return bytes(exe)


@pytest.mark.parametrize("k,idx", [(0, 0), (238, 238), (239, 240), (1250, 1251), (1346, 1347)])
def test_width_index_is_off_by_one_for_two_byte_codes(k, idx):
    # renderer 0x80017CCC computes ((b - 0xEF) << 8) - 0x10 + lo for the advance lookup
    assert poc_db.width_index(k) == idx


def test_width_index_of_last_cell_is_past_the_table():
    with pytest.raises(ValueError):
        poc_db.width_index(1347)


def test_patch_widths_sets_listed_slots_only():
    table = bytearray([13] * 1348)
    for i, w in poc_db.ORIGINAL_WIDTHS.items():
        table[i] = w
    out = poc_db.patch_widths(_exe_with_table(table))
    got = out[poc_db.WIDTH_OFFSET : poc_db.WIDTH_OFFSET + 1348]
    want = dict(enumerate(table))
    for ch, k in poc_db.SLOTS:
        want[poc_db.width_index(k)] = poc_db.SPACE_WIDTH if ch == " " else poc_db.HANGUL_WIDTH
    assert list(got) == [want[i] for i in range(1348)]


def test_patch_widths_refuses_unexpected_source():
    table = bytearray([13] * 1348)
    with pytest.raises(ValueError):
        poc_db.patch_widths(_exe_with_table(table))  # slot 60 is 13 instead of a's 8


@need_files
def test_original_width_table_matches_survey():
    exe = (FILES / "SLPS_006.62").read_bytes()
    t = exe[poc_db.WIDTH_OFFSET : poc_db.WIDTH_OFFSET + 1348]
    assert list(t[0:10]) == [10] * 10 and t[301] == 13 and t[68] == 3  # digits, 手 (2-byte: k+1), i
    assert all(t[k] == w for k, w in poc_db.ORIGINAL_WIDTHS.items())


def _cue(tmp_path, names):
    cue = tmp_path / "src" / "game.cue"
    cue.parent.mkdir()
    cue.write_text("".join(f'FILE "{n}" BINARY\n  TRACK 01 MODE2/2352\n' for n in names))
    return cue


def test_write_cue_points_track1_at_output_and_audio_at_originals(tmp_path):
    cue = _cue(tmp_path, ["g (Track 01).bin", "g (Track 02).bin"])
    out = tmp_path / "build" / "poc.bin"
    out.parent.mkdir()
    text = poc_db.write_cue(cue, out).read_text()
    assert 'FILE "poc.bin" BINARY' in text
    assert 'FILE "../src/g (Track 02).bin" BINARY' in text


@pytest.mark.parametrize("names", [["g (Track 1).bin"], ["a (Track 01).bin", "b (Track 01).bin"]])
def test_write_cue_requires_exactly_one_track1(tmp_path, names):
    out = tmp_path / "poc.bin"
    with pytest.raises(ValueError):
        poc_db.write_cue(_cue(tmp_path, names), out)


def test_check_source_refuses_other_images():
    with pytest.raises(ValueError):
        poc_db.check_source(b"\0" * 2352)


def test_check_paths_refuses_overwriting_source(tmp_path):
    src = tmp_path / "t.bin"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        poc_db.check_paths(src, tmp_path / "." / "t.bin")
