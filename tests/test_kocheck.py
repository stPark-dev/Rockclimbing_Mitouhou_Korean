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
    # F5-F7 are not used: F6 (cell 245, ・) drew blank on the peak info window (2026-10-21),
    # so 1-byte cells are 0-238 only and ・ moves into one of them
    assert kocheck.ONE_BYTE_SLOTS == 239 - 60 - len(kocheck.NEW_PUNCT) - 3 - 2


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


def test_window_problem_when_a_line_exceeds_a_measured_limit():
    # database equipment descriptions: 249px (docs/survey.md §9)
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "57ff", "copies": ["KWAMENU.BIN:14354"]}}
    ko = {"src:a": {"ko": "가" * 20 + "\n" + "가" * 21, "status": "draft"}}  # 240px, 252px
    assert kocheck.window_problems(units_, ko) == [("src:a", "window", "line 2 252px > 249px")]
    ko = {"src:a": {"ko": "가" * 20, "status": "draft"}}
    assert kocheck.window_problems(units_, ko) == []


def test_measured_windows_replace_the_source_width_warning():
    widths = {86: 12}
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "57ff", "copies": ["KWAMENU.BIN:14354"]},
              "src:b": {"text": "", "capacity": 99, "source": "57ff", "copies": ["KWAMENU.BIN:11D4C"]}}  # summer/winter question, not measured
    ko = {"src:a": {"ko": "가나", "status": "draft"}, "src:b": {"ko": "가나", "status": "draft"}}
    assert [w[0] for w in kocheck.width_warnings(units_, ko, widths)] == ["src:b"]
    assert kocheck.window_problems(units_, ko) == []


def test_cover_plan_takes_the_smallest_fitting_set_then_frequent_syllables():
    # 가나, 가다 and 나라 each need one 1-byte syllable; {가, 나} covers all three with two slots,
    # and the third slot goes to the most frequent remaining syllable 라
    pytest.importorskip("scipy")
    import collections
    texts = [("가나", 4), ("가다", 4), ("나라", 4), ("다라라라", 99)]
    entries = [(kocheck.tokenize(t), cap, collections.Counter(t)) for t, cap in texts]
    freq = collections.Counter("".join(t for t, _ in texts))
    plan = kocheck.cover_plan(entries, freq, slots=3)
    assert plan == {"가", "나", "라"}
    assert kocheck.cover_plan(entries, freq, slots=1) is None


def test_window_problems_ignore_layout_at_the_end_of_a_line():
    # training item panel: 108px; a trailing FC tab draws nothing
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "57ff", "copies": ["KWAMENU.BIN:138D8"]}}
    ko = {"src:a": {"ko": "가" * 9 + "{FC:02}\n" + "가" * 9 + "　", "status": "draft"}}
    assert kocheck.window_problems(units_, ko) == []
    ko = {"src:a": {"ko": "{FC:01}" + "가" * 9, "status": "draft"}}
    assert kocheck.window_problems(units_, ko) == [("src:a", "window", "line 1 121px > 108px")]


def test_fixed_pitch_windows_count_every_character_as_a_13px_cell():
    # stage overview (SUZU0 0x8CEC-): 224px = 17 cells; the half-width space is a full cell
    toks = kocheck.tokenize("산{FC:05}：가나 다")
    assert kocheck.fixed_line_widths(toks) == [13 * (1 + 5 + 1 + 4)]
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "57ff", "copies": ["SUZU0.BIN:8CEC"]}}
    ko = {"src:a": {"ko": "가 " * 8 + "가", "status": "draft"}}  # 17 cells
    assert kocheck.window_problems(units_, ko) == []
    ko = {"src:a": {"ko": "가 " * 8 + "가가", "status": "draft"}}  # 18 cells
    assert kocheck.window_problems(units_, ko)[0][2].endswith("> 224px (fixed 13px)")


def test_variants_split_copies_between_by_copy_and_the_default():
    u = {"copies": ["A:1", "B:2", "C:3"], "caps": {"A:1": 20, "B:2": 8, "C:3": 20}}
    entry = {"ko": "기본", "by_copy": {"B:2": "짧게"}}
    assert kocheck.variants(u, entry) == [(["A:1", "C:3"], "기본", 20), (["B:2"], "짧게", 8)]


def test_check_reports_capacity_of_a_by_copy_variant_against_its_own_slot():
    units_ = {"src:a": {"text": "あ", "capacity": 3, "copies": ["A:1", "B:2"], "caps": {"A:1": 30, "B:2": 3}}}
    ko = {"src:a": {"ko": "가", "by_copy": {"A:1": "가나다라마바사"}, "status": "draft"}}
    assert kocheck.check(units_, ko, one_byte=set()) == []  # 7 Hangul x2 + FF = 15 <= 30; 가 = 3 <= 3
    ko["src:a"]["ko"] = "가나"
    assert [p[1] for p in kocheck.check(units_, ko, one_byte=set())] == ["capacity"]


def test_window_limit_applies_to_the_variant_on_that_copy(monkeypatch):
    monkeypatch.setattr(kocheck, "WINDOW_LIMITS", [("X.BIN", 0x10, 0x20, 30, "narrow")])
    monkeypatch.setattr(kocheck, "FIXED_WINDOWS", [])
    units_ = {"src:a": {"text": "あ", "capacity": 40, "copies": ["W.BIN:00010", "X.BIN:00010"],
                        "caps": {"W.BIN:00010": 40, "X.BIN:00010": 40}}}
    ko = {"src:a": {"ko": "가나다라", "by_copy": {"X.BIN:00010": "가나"}, "status": "draft"}}
    assert kocheck.window_problems(units_, ko) == []  # 가나 = 24px in the 30px window; 가나다라 is elsewhere
    ko["src:a"]["by_copy"] = {}
    assert [p[1] for p in kocheck.window_problems(units_, ko)] == ["window"]


def test_climbing_screen_windows_have_their_measured_limits():
    # KABE event messages 220px, small notices 124px, altitude sickness and level-up 252px (docs/survey.md §9)
    assert kocheck.window_limit(["KABE.BIN:2C014"]) == 220
    assert kocheck.window_limit(["KABE.BIN:2C67C"]) == 220
    assert kocheck.window_limit(["KABE.BIN:2C880"]) == 124
    assert kocheck.window_limit(["KABE.BIN:2C88C"]) == 124
    assert kocheck.window_limit(["KABE.BIN:2D74C"]) == 252
    assert kocheck.window_limit(["KABE.BIN:2C6F4"]) == 252  # level-up, frame formula
    assert kocheck.window_limit(["KABE.BIN:2C8A4"]) == 156  # terrace question
    assert kocheck.window_limit(["KABE.BIN:2D650"]) == 236  # give-up questions
    assert kocheck.window_limit(["KABE.BIN:2D720"]) == 236
    assert kocheck.window_limit(["KABE.BIN:2D6B0"]) is None  # return to the entrance: caller not found


def test_player_name_slot_counts_eight_cells_in_climbing_event_messages():
    # {F8:00} draws the player name in a fixed 8 x 13px slot there (docs/survey.md §9); elsewhere F8 is a cursor
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "57ff", "copies": ["KABE.BIN:2C080"]},
              "src:b": {"text": "", "capacity": 99, "source": "57ff", "copies": ["KWAMENU.BIN:14354"]}}
    ko = {"src:a": {"ko": "{F8:00}" + "가" * 9, "status": "draft"},  # 104 + 108 = 212px
          "src:b": {"ko": "{F8:00}" + "가" * 20, "status": "draft"}}  # 240px
    assert kocheck.window_problems(units_, ko) == []
    ko["src:a"]["ko"] = "{F8:00}" + "가" * 10  # 224px
    assert kocheck.window_problems(units_, ko) == [("src:a", "window", "line 1 224px > 220px")]


def test_camp_screen_windows_have_their_measured_limits():
    # MESI: food ran out 245px, results and bivouac 203px, plan question 191px, rest menu 187px (docs/survey.md §9)
    assert kocheck.window_limit(["MESI.BIN:01F9C"]) == 245
    assert kocheck.window_limit(["MESI.BIN:01FFC"]) == 203
    assert kocheck.window_limit(["MESI.BIN:02170"]) == 203
    assert kocheck.window_limit(["MESI.BIN:02210"]) == 203
    assert kocheck.window_limit(["MESI.BIN:02040"]) == 191
    assert kocheck.window_limit(["MESI.BIN:020AC"]) == 187
    assert kocheck.window_limit(["MESI.BIN:021D0"]) is None  # mood question: not measured


def test_mountain_screen_move_windows_have_their_measured_limits():
    # MT0/MT1: stage move header and route descriptions 216px, stage-to-stage note 132px (docs/survey.md §9)
    for mod in ("MT0.BIN", "MT1.BIN"):
        assert kocheck.window_limit([f"{mod}:00058"]) == 132
        assert kocheck.window_limit([f"{mod}:00160"]) == 216
        assert kocheck.window_limit([f"{mod}:00E64"]) == 216
        assert kocheck.window_limit([f"{mod}:014EC"]) == 178  # scenery remarks
        assert kocheck.window_limit([f"{mod}:017CC"]) == 178


def test_mountain_screen_hazard_windows_have_their_measured_limits():
    # MT0/MT1 move events: warning 179/178px, main 220/210/205px by text x, outcomes 178px (docs/survey.md §9)
    for mod in ("MT0.BIN", "MT1.BIN"):
        assert kocheck.window_limit([f"{mod}:0020C"]) == 179
        assert kocheck.window_limit([f"{mod}:00588"]) == 178
        assert kocheck.window_limit([f"{mod}:00240"]) == 220
        assert kocheck.window_limit([f"{mod}:005BC"]) == 210
        assert kocheck.window_limit([f"{mod}:00BD4"]) == 205
        assert kocheck.window_limit([f"{mod}:002DC"]) == 178
        assert kocheck.window_limit([f"{mod}:00C54"]) == 178
        assert kocheck.window_limit([f"{mod}:00200"]) is None  # bivouac notice: not measured


def test_mountain_screen_status_window_has_its_measured_limit():
    # SUZU0-4 progress status (ahead of or behind plan, food left): 180px (docs/survey.md §9)
    for mod in ("SUZU0.BIN", "SUZU1.BIN", "SUZU2.BIN", "SUZU3.BIN", "SUZU4.BIN"):
        assert kocheck.window_limit([f"{mod}:00000"]) == 180
        assert kocheck.window_limit([f"{mod}:00154"]) == 180
        assert kocheck.window_limit([f"{mod}:0019C"]) is None  # pitch list: another window


def test_pitch_overview_and_advice_are_fixed_pitch_windows():
    # SUZU1-4 0xBAB4-: pitch overview / advice, 13px cells, text x=44, inner right x~280: 18 cells (docs/survey.md §9)
    units_ = {"src:a": {"text": "", "capacity": 99, "source": "57ff", "copies": ["SUZU1.BIN:0BAB4"]}}
    ko = {"src:a": {"ko": "가" * 18, "status": "draft"}}
    assert kocheck.window_problems(units_, ko) == []
    ko = {"src:a": {"ko": "가" * 19, "status": "draft"}}
    assert kocheck.window_problems(units_, ko)[0][2].endswith("> 236px (fixed 13px)")
    assert kocheck.window_limit(["SUZU4.BIN:0CF94"]) == 236


def test_memory_card_dialog_has_its_measured_limit():
    # save flow dialog seen on screen: text x=88, inner right edge x~241 (docs/survey.md §9)
    for off in ("10A98", "10B00", "10BB0", "10BFC"):
        assert kocheck.window_limit([f"KWAMENU.BIN:{off}"]) == 153
    for off in ("10C5C", "10D8C", "10DC8"):  # error messages put into the same record (state intervention)
        assert kocheck.window_limit([f"KWAMENU.BIN:{off}"]) == 153


def test_training_result_window_has_its_measured_limit():
    # KWAMENU 0x196A4-: training results over the picture, text x=48, inner right edge x~280 (docs/survey.md §9)
    assert kocheck.window_limit(["KWAMENU.BIN:196A4"]) == 232
    assert kocheck.window_limit(["KWAMENU.BIN:19D70"]) == 232
    assert kocheck.window_limit(["KWAMENU.BIN:19DC0"]) == 232


def test_plan_advice_windows_have_their_measured_limits():
    # KWAMENU summer/winter advice 268px, partner/solo advice 172px (docs/survey.md §9)
    assert kocheck.window_limit(["KWAMENU.BIN:11D88"]) == 268
    assert kocheck.window_limit(["KWAMENU.BIN:11DC8"]) == 268
    assert kocheck.window_limit(["KWAMENU.BIN:11EB0"]) == 172
    assert kocheck.window_limit(["KWAMENU.BIN:11EFC"]) == 172


def test_save_slot_window_has_its_measured_limit():
    # KWAMENU 0x10E0C-0x112D8 save slot lines: text x=48, inner right edge x~281 (docs/survey.md §9)
    assert kocheck.window_limit(["KWAMENU.BIN:10E0C"]) == 233
    assert kocheck.window_limit(["KWAMENU.BIN:112C4"]) == 233


def test_windows_inferred_from_shared_call_sites():
    # KABE footing remarks open the 16-tile event frame; MESI advice opens the rest-menu box (docs/survey.md §9)
    assert kocheck.window_limit(["KABE.BIN:2BFE0"]) == 220
    assert kocheck.window_limit(["KABE.BIN:2BFF4"]) == 220
    assert kocheck.window_limit(["MESI.BIN:02224"]) == 187
    assert kocheck.window_limit(["MESI.BIN:02360"]) == 187


def test_history_and_food_out_windows():
    # route history (KWAMENU 0x12E0C-) 141px on screen; food ran out over a full-screen picture, x=72 (code) 248px
    assert kocheck.window_limit(["KWAMENU.BIN:12E0C"]) == 141
    assert kocheck.window_limit(["KWAMENU.BIN:12E4C"]) == 141
    assert kocheck.window_limit(["MT0.BIN:00000"]) == 248
