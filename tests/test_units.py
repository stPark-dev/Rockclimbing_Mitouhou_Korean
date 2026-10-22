import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import units  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "text" / "src"


def _entry(eid, file, source, text, cap):
    off = int(eid.split(":")[1], 16)
    return {"id": eid, "file": file, "offset": off, "end": off + len(source) // 2,
            "slot_end": off + cap, "capacity": cap, "source": source, "text": text}


def test_units_group_identical_sources_and_keep_smallest_capacity():
    es = [
        _entry("SUZU_0.BIN:00010", "SUZU_0.BIN", "5758ff", "あい", 4),
        _entry("SUZU0.BIN:00020", "SUZU0.BIN", "5758ff", "あい", 3),
        _entry("MT0.BIN:00000", "MT0.BIN", "59ff", "う", 4),
    ]
    us = units.build(es)
    assert len(us) == 2
    u = us[units.key("5758ff")]
    assert u["capacity"] == 3 and u["copies"] == ["SUZU0.BIN:00020", "SUZU_0.BIN:00010"]
    assert u["group"] == "stage"  # the first group in GROUP_ORDER that holds a copy


def test_key_is_stable_and_prefixed():
    assert units.key("5758ff") == units.key("5758FF") and units.key("5758ff").startswith("src:")


@pytest.mark.parametrize("file,group", [("KWAMENU.BIN", "menu"), ("SUZU3.BIN", "stage"), ("MT1.BIN", "event"),
                                        ("KABE.BIN", "climb"), ("MESI.BIN", "camp"), ("STAFF.BIN", "staff"),
                                        ("X_SUZU.BIN", "stage"), ("SUZU_1.BIN", "event")])
def test_groups(file, group):
    assert units.GROUP_OF[file] == group


def test_merge_keeps_existing_translations_and_adds_new_units(tmp_path):
    us = units.build([_entry("MT0.BIN:00000", "MT0.BIN", "59ff", "う", 4),
                      _entry("MT0.BIN:00004", "MT0.BIN", "5aff", "え", 4)])
    old = {units.key("59ff"): {"ko": "우", "status": "draft"}}
    merged = units.merge(old, us, "event")
    assert merged[units.key("59ff")]["ko"] == "우" and merged[units.key("59ff")]["status"] == "draft"
    assert merged[units.key("5aff")]["ko"] == "" and merged[units.key("5aff")]["status"] == "untranslated"
    assert "ja" not in merged[units.key("5aff")] and merged[units.key("5aff")]["cap"] == 4  # Japanese stays in text/src


def test_merge_refuses_units_that_vanished_from_the_source():
    with pytest.raises(ValueError):
        units.merge({"src:deadbeef0000": {"ko": "x", "status": "draft"}}, {}, "event")


@pytest.mark.skipif(not SRC.exists(), reason="text/src not generated")
def test_corpus_unit_count_matches_unique_sources():
    es = [e for p in SRC.glob("*.json") for e in json.loads(p.read_text(encoding="utf-8"))["entries"]]
    us = units.build(es)
    assert len(us) == len({e["source"] for e in es}) == 1474  # after the pointer-tail starts (2026-10-22)
    assert sum(len(u["copies"]) for u in us.values()) == 4556
