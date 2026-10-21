import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import textcodec as tc  # noqa: E402
import textmap  # noqa: E402

FILES = Path(__file__).resolve().parent.parent / "work" / "files"
need_files = pytest.mark.skipif(not (FILES / "KWAMENU.BIN").exists(), reason="extracted files not available")

A = tc.encode([("g", 86), ("g", 87), ("end",)])  # あい
B = tc.encode([("sp",), ("g", 300), ("end",)])  # 　手


def test_candidates_start_after_boundaries_and_read_tokens():
    blob = A + b"\0" + B
    assert [(s, e) for s, e, _ in textmap.candidates(blob)] == [(0, 3), (4, 8)]


def test_chain_links_strings_separated_by_up_to_three_zero_bytes():
    blob = A + b"\0\0\0" + B + b"\0\0\0\0" + A
    chains = textmap.chains(textmap.candidates(blob), blob)
    assert [[s for s, _, _ in c] for c in chains] == [[0, 6], [14]]


def test_slot_runs_to_next_string_or_alignment():
    blob = A + b"\0" + B + b"\0\0\0\0\0"
    c = textmap.candidates(blob)
    ch = textmap.chains(c, blob)[0]
    # first string owns its padding up to the next start; last string only up to 4-byte alignment
    assert textmap.slots(ch, blob) == [4, 8]


def test_refs_find_words_and_lui_addiu_pairs():
    base = 0x800AFF18
    code = struct.pack("<I", 0x800B0010)  # data word
    code += struct.pack("<II", 0x3C04800B, 0x24840020)  # lui a0,0x800b ; addiu a0,a0,0x20
    code += struct.pack("<II", 0x3C05800B, 0x24A5FFF0)  # lui a1,0x800b ; addiu a1,a1,-0x10
    r = textmap.refs(code, base)
    assert ("word", base) in r[0x800B0010]
    assert ("pair", base + 4) in r[0x800B0020]
    assert ("pair", base + 12) in r[0x800AFFF0]


@pytest.mark.parametrize("toks,noise", [
    ([("g", 86), ("g", 87)], False),  # あい
    ([("g", 4), ("g", 127), ("g", 1), ("g", 59)], True),  # ５れ２Ｚ: MIPS bytes read as text (れ = 127)
    ([("g", 4), ("g", 126), ("g", 1)], False),  # ５る２: る (126) is not part of the rule
    ([("g", 98), ("g", 127), ("g", 32), ("g", 220)], False),  # されれ、: punctuation after れ is prose
    ([("g", 127), ("g", 31)], False),  # れ。
    ([("g", 234)], True),  # one glyph
    ([("g", 83), ("g", 83), ("g", 110)], False),  # ｘｘの: developer placeholder text
])
def test_code_noise(toks, noise):
    assert textmap.is_code_noise(toks) is noise


@need_files
def test_corpus_entries_decode_do_not_overlap_and_fit_their_files():
    files = {n: (FILES / n).read_bytes() for n in textmap.MODULES}
    entries = textmap.extract(files, (FILES / "SLPS_006.62").read_bytes())
    by_file = {}
    for e in entries:
        data = files[e["file"]]
        assert data[e["offset"] : e["end"]] == bytes.fromhex(e["source"])
        toks, end = tc.read_page(data, e["offset"])
        assert end == e["end"] and e["end"] <= e["slot_end"] <= len(data)
        assert not any(data[e["end"] : e["slot_end"]])
        by_file.setdefault(e["file"], []).append(e)
    for es in by_file.values():
        es.sort(key=lambda e: e["offset"])
        assert all(a["slot_end"] <= b["offset"] for a, b in zip(es, es[1:]))
    assert len({e["id"] for e in entries}) == len(entries)


@need_files
def test_corpus_counts_are_the_adopted_population():
    files = {n: (FILES / n).read_bytes() for n in textmap.MODULES}
    entries = textmap.extract(files, (FILES / "SLPS_006.62").read_bytes())
    counts = {}
    for e in entries:
        counts[e["file"]] = counts.get(e["file"], 0) + 1
    assert counts == textmap.EXPECTED_COUNTS


@need_files
def test_corpus_known_lines_are_present():
    files = {n: (FILES / n).read_bytes() for n in textmap.MODULES}
    ids = {e["id"] for e in textmap.extract(files, (FILES / "SLPS_006.62").read_bytes())}
    assert "KWAMENU.BIN:1790C" in ids  # database: まず、移動しようと思う手や足を選びます。
    assert "MT0.BIN:00000" in ids  # 日程が大幅に遅れたため


def test_write_sources_emits_one_json_per_module(tmp_path):
    import json

    entries = [
        {"id": "A.BIN:00000", "file": "A.BIN", "offset": 0, "end": 3, "slot_end": 4,
         "source": A.hex(), "evidence": "blob", "refs": []},
    ]
    cm = {86: ("あ", "visual"), 87: ("い", "visual")}
    textmap.write_sources(entries, cm, tmp_path)
    doc = json.loads((tmp_path / "A.BIN.json").read_text(encoding="utf-8"))
    assert doc["entries"][0]["text"] == "あい" and doc["entries"][0]["capacity"] == 4
    assert doc["file"] == "A.BIN" and doc["base"] is None
