import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_ko as build  # noqa: E402
import kfont  # noqa: E402
import textcodec as tc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GALMURI = os.environ.get("GALMURI11_BDF") or str(ROOT.parent / "galmuri" / "Galmuri11.bdf")
TRACK = next(iter(sorted((ROOT / "original").glob("*(Track 01).bin"))), None)
need_galmuri = pytest.mark.skipif(not Path(GALMURI).exists(), reason="Galmuri11.bdf not available")
need_disc = pytest.mark.skipif(TRACK is None, reason="original disc image not available")


def test_allocate_puts_planned_hangul_in_one_byte_cells_and_the_rest_in_two_byte_cells():
    cells = build.allocate(hangul={"가", "나", "다"}, one_byte={"가"}, kept=set())
    assert cells["가"] <= 0xEE
    assert cells["나"] > 0xEE and cells["다"] > 0xEE
    assert cells["나"] != 1347 and cells["다"] != 1347  # its advance would be read past the table
    for ch in build.NEW_PUNCT_CELLS:
        assert cells[ch] < 239
    assert len(set(cells.values())) == len(cells)


def test_allocate_keeps_fixed_and_used_kept_glyphs_in_place():
    cells = build.allocate(hangul={"가"}, one_byte=set(), kept={"Ⅰ", "０", "ｃ", "・"})
    assert cells["Ⅰ"] == 1251 and cells["０"] == 0 and cells["ｃ"] == 62
    assert 60 <= cells["・"] <= 0xEE  # moved off cell 245: F6 drew blank at runtime
    assert cells["가"] not in (1251, 0, 62)


def test_allocate_refuses_more_one_byte_hangul_than_cells():
    many = {chr(0xAC00 + i) for i in range(200)}
    with pytest.raises(ValueError):
        build.allocate(hangul=many, one_byte=many, kept=set())


def test_encode_uses_cells_controls_and_aliases():
    cells = {"가": 100, "나": 300, "（": 26, "）": 27, " ": 150}
    raw = build.encode("가(나) {F8:00}\n　{FC:02}", cells)
    toks = tc.decode(raw)
    assert toks[:4] == [("g", 100), ("g", 26), ("g", 300), ("g", 27)]  # ASCII ( ) map to （ ）
    assert ("ctl", 0xF8, b"\x00") in toks and ("nl",) in toks and ("sp",) in toks
    assert toks[-1] == ("end",)


def test_encode_fails_on_unmapped_character():
    with pytest.raises(ValueError):
        build.encode("가?", {"가": 100})


def test_write_string_pads_the_rest_of_the_slot_with_zeros():
    data = bytearray(b"\x11\x22\x33\xff\x00\x00\x00\x00\x99")
    build.write_string(data, 0, 8, b"\x55\xff")
    assert bytes(data) == b"\x55\xff\x00\x00\x00\x00\x00\x00\x99"
    with pytest.raises(ValueError):
        build.write_string(data, 0, 2, b"\x55\x66\xff")


def test_width_index_follows_the_two_byte_rule():
    assert build.width_index(100) == 100 and build.width_index(300) == 301


@need_galmuri
def test_glyph_for_punctuation_and_space():
    bdf = kfont.load_bdf(GALMURI)
    assert build.glyph(" ", bdf) == bytes(72)
    assert any(build.glyph(".", bdf))
    assert build.advance(" ", bdf) == build.SPACE_W and build.advance("가", bdf) == build.HANGUL_W


@need_disc
@need_galmuri
def test_corpus_build_without_translations_reproduces_the_original():
    src = TRACK.read_bytes()
    out, report = build.build(src, {}, kfont.load_bdf(GALMURI), policy="dev")
    assert out == src and report["strings_written"] == 0


@need_disc
@need_galmuri
def test_corpus_dev_build_reads_back_every_selected_translation(tmp_path):
    ko = {}
    for p in sorted((ROOT / "text" / "ko").glob("*.json")):
        ko.update(json.loads(p.read_text(encoding="utf-8")))
    src = TRACK.read_bytes()
    out, report = build.build(src, ko, kfont.load_bdf(GALMURI), policy="dev")
    assert report["distribution"] is False
    assert report["strings_written"] > 0
    # every written string decodes back to its translation through the build's own cell map
    for item in report["written"][:200]:
        data = report["files_out"][item["file"]]
        toks, end = tc.read_page(data, item["offset"])
        assert build.decode_with(toks, report["cells"]) == build.normalize(item["ko"])


@need_disc
@need_galmuri
def test_corpus_release_build_refuses_drafts():
    ko = {"src:000000000000": {"ko": "가", "status": "draft"}}
    with pytest.raises(ValueError):
        build.build(TRACK.read_bytes(), ko, kfont.load_bdf(GALMURI), policy="release")


def test_normalize_maps_ascii_aliases_but_leaves_controls_alone():
    assert build.normalize("가(나)?{FC:02}") == "가（나）？{FC:02}"


def test_no_code_uses_f5_to_f7():
    cells = build.allocate(hangul={chr(0xAC00 + i) for i in range(300)}, one_byte={chr(0xAC00 + i) for i in range(100)},
                           kept={"・"})
    assert not any(build.code(k)[0] in (0xF5, 0xF6, 0xF7) for k in cells.values())


def test_text_for_copy_prefers_the_by_copy_variant():
    entry = {"ko": "기본", "by_copy": {"X_SUZU.BIN:011C8": "짧게"}}
    assert build.text_for(entry, "X_SUZU.BIN:011C8") == "짧게"
    assert build.text_for(entry, "KWAMENU.BIN:12004") == "기본"


@need_disc
@need_galmuri
def test_corpus_dev_build_installs_the_hangul_name_entry():
    import struct
    import nameentry as ne
    ko = {}
    for p in sorted((ROOT / "text" / "ko").glob("*.json")):
        ko.update(json.loads(p.read_text(encoding="utf-8")))
    out, report = build.build(TRACK.read_bytes(), ko, kfont.load_bdf(GALMURI), policy="dev")
    cells, files = report["cells"], report["files_out"]
    assert all(ch in cells for ch in ne.syllables())
    exe = files["SLPS_006.62"]
    o = ne.TABLE_START - ne.EXE_LOAD
    region = exe[o:ne.TABLE_END - ne.EXE_LOAD]
    for i, ch in enumerate(ne.layout(), 1):
        off = struct.unpack_from("<H", region, 2 * ne.number(i))[0]
        if ch == ne.SPACE:
            assert region[off] == 0xFD
        else:
            assert region[off:off + len(ne.code(cells[ch]))] == ne.code(cells[ch])
    kw = files["KWAMENU.BIN"]
    page0 = ne.encode_pages(cells, build.encode)[0]
    assert page0 in kw[ne.CAVE_START:ne.CAVE_END]
    assert not any(w["file"] == "KWAMENU.BIN" and ne.CAVE_START <= w["offset"] < ne.CAVE_END
                   for w in report["written"])


def test_beta_policy_takes_ai_reviewed_units_and_refuses_drafts():
    ko = {"src:a": {"ko": "가", "status": "ai_reviewed"}, "src:b": {"ko": "나", "status": "needs_context"},
          "src:c": {"ko": "다", "status": "reviewed"}, "src:d": {"ko": "", "status": "untranslated"}}
    assert set(build._select(ko, "beta")) == {"src:a", "src:b", "src:c"}
    with pytest.raises(ValueError):
        build._select({**ko, "src:e": {"ko": "라", "status": "draft"}}, "beta")
    with pytest.raises(ValueError):  # release stays human-reviewed only
        build._select(ko, "release")


def test_beta_is_distributed_but_marked_as_not_human_reviewed():
    assert build.CHANNELS["beta"]["distribution"] and not build.CHANNELS["beta"]["human_reviewed"]
    assert "AI-reviewed" in build.CHANNELS["beta"]["note"]
    assert build.CHANNELS["release"] == {"distribution": True, "human_reviewed": True, "note": ""}
    assert not build.CHANNELS["dev"]["distribution"]
