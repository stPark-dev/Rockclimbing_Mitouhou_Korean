import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract  # noqa: E402
from test_iso import A, B, DISC, FORM2_AUDIO, _set_subheader, make_disc  # noqa: E402


def test_extract_writes_every_form1_file(tmp_path):
    raw = make_disc([("A.BIN", 20, A), ("B.BIN", 22, B)])
    skipped = extract.extract(raw, tmp_path)
    assert skipped == []
    assert (tmp_path / "A.BIN").read_bytes() == A
    assert (tmp_path / "B.BIN").read_bytes() == B


def test_extract_skips_and_reports_non_form1_files(tmp_path):
    raw = _set_subheader(DISC, 20, FORM2_AUDIO)
    assert extract.extract(raw, tmp_path) == ["A.BIN"]
    assert not (tmp_path / "A.BIN").exists()
    assert (tmp_path / "B.BIN").read_bytes() == B


def test_extract_skips_entries_outside_the_data_track(tmp_path):
    raw = make_disc([("A.BIN", 20, A), ("B.BIN", 22, B)])
    # point B.BIN at an LBA past the image, like the CDDA/*.DA records on the real disc
    root = 18 * 2352 + 24
    data = bytearray(raw)
    off = bytes(data[root : root + 2048]).index(b"B.BIN;1") - 33
    import struct

    data[root + off + 2 : root + off + 10] = struct.pack("<I", 9999) + struct.pack(">I", 9999)
    assert extract.extract(bytes(data), tmp_path) == ["B.BIN"]
