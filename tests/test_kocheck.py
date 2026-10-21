import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import kocheck  # noqa: E402


def test_tokenize_controls_lines_spaces_and_chars():
    assert kocheck.tokenize("가{F8:00}\n　나 .") == [
        ("c", "가"), ("ctl", 0xF8, b"\x00"), ("nl",), ("sp",), ("c", "나"), ("c", " "), ("c", ".")]


def test_tokenize_rejects_malformed_control():
    with pytest.raises(ValueError):
        kocheck.tokenize("{F8:0}")


def test_protected_sequence_ignores_layout_controls():
    src = kocheck.tokenize("{FC:02}あ{F8:00}{F9:01}")
    assert kocheck.protected(src) == [(0xF8, b"\x00"), (0xF9, b"\x01")]


def test_byte_length_counts_one_and_two_byte_codes():
    toks = kocheck.tokenize("가나{FC:02}\n다")
    # 가 one byte, 나/다 two bytes, FC+arg two, newline one, FF end one
    assert kocheck.byte_length(toks, one_byte={"가"}) == 1 + 2 + 2 + 1 + 2 + 1


def test_one_byte_plan_takes_the_most_frequent_syllables():
    plan = kocheck.one_byte_plan(["가가가나나다", "가나"], slots=2)
    assert plan == {"가", "나"}


@pytest.mark.parametrize("ch,ok", [("가", True), ("힣", True), ("０", True), ("。", False), (".", True),
                                   (" ", True), ("“", True), ("(", True), ("a", False), ("あ", False), ("漢", False),
                                   ("、", False), ("ｃ", True), ("℃", True), ("△", True), ("・", True), ("ー", True)])
def test_encodable(ch, ok):
    assert kocheck.encodable(ch) is ok


def test_check_reports_each_kind_of_problem():
    units_ = {
        "src:a": {"text": "あ{F8:00}", "capacity": 8},
        "src:b": {"text": "あ", "capacity": 2},
        "src:c": {"text": "あ", "capacity": 8},
    }
    ko = {"src:a": {"ko": "가", "status": "draft"},  # F8 dropped
          "src:b": {"ko": "가나다라", "status": "draft"},  # too long
          "src:c": {"ko": "가a", "status": "draft"}}  # 'a' has no glyph
    probs = {(k, kind) for k, kind, _ in kocheck.check(units_, ko, one_byte=set())}
    assert probs == {("src:a", "tokens"), ("src:b", "capacity"), ("src:c", "glyph")}


def test_check_skips_untranslated_units():
    units_ = {"src:a": {"text": "あ{F8:00}", "capacity": 1}}
    assert kocheck.check(units_, {"src:a": {"ko": "", "status": "untranslated"}}, one_byte=set()) == []


def test_fit_plan_moves_syllables_of_tight_strings_into_one_byte_codes():
    # "가" is most frequent but only in a roomy string; "다" sits in a string with no slack.
    units_ = {"src:a": {"text": "", "capacity": 50}, "src:b": {"text": "", "capacity": 2}}  # a has room for 가 as 2 bytes
    ko = {"src:a": {"ko": "가" * 20 + "나", "status": "draft"}, "src:b": {"ko": "다", "status": "draft"}}
    assert kocheck.one_byte_plan(["가" * 20 + "나", "다"], slots=1) == {"가"}
    plan = kocheck.fit_plan(units_, ko, slots=1)
    assert plan == {"다"}
    assert kocheck.check(units_, ko, plan) == []


def test_fit_plan_keeps_frequency_plan_when_everything_fits():
    units_ = {"src:a": {"text": "", "capacity": 40}}
    ko = {"src:a": {"ko": "가가나", "status": "draft"}}
    assert kocheck.fit_plan(units_, ko, slots=1) == {"가"}


@pytest.mark.parametrize("text,size", [
    ("Ａ", 2), ("０", 2), ("？", 2), ("・", 2), (".", 2), ("ｃ", 2),  # 1-byte cells + FF
    ("Ⅰ", 3), ("℃", 3), ("△", 3),  # glyphs in 2-byte cells
])
def test_non_hangul_sizes_follow_their_cells(text, size):
    assert kocheck.byte_length(kocheck.tokenize(text), one_byte=set()) == size


def test_one_byte_slots_leave_room_for_fixed_and_reserved_cells():
    # cells 0-238 and 244-246 are 1-byte; 0-59 stay fixed (digits for FA, symbols, Latin capitals);
    # new punctuation, ｃｍｘ, ・ and ？ take 1-byte cells too
    assert kocheck.ONE_BYTE_SLOTS == (239 + 3) - 60 - len(kocheck.NEW_PUNCT) - 3 - 2


def test_line_widths_use_the_advance_table_and_layout_controls():
    widths = {86: 12, 87: 9}  # あ い
    src = [("g", 86), ("g", 87), ("nl",), ("ctl", 0xFC, b"\x02"), ("g", 86), ("sp",)]
    assert kocheck.source_line_widths(src, widths) == [21, 26 + 12 + 13]
    ko = kocheck.tokenize("가 나\n{FC:01}다")
    assert kocheck.ko_line_widths(ko) == [12 + 6 + 12, 13 + 12]


def test_width_warning_when_a_line_is_wider_than_the_widest_source_line():
    widths = {86: 12}
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "5757ff"}}  # ああ = 24px
    ko = {"src:a": {"ko": "가나다", "status": "draft"}}  # 36px
    assert [w[1] for w in kocheck.width_warnings(units_, ko, widths)] == ["width"]
    ko = {"src:a": {"ko": "가나", "status": "draft"}}  # 24px
    assert kocheck.width_warnings(units_, ko, widths) == []
