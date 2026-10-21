import glob
import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import cdsector  # noqa: E402
import iso  # noqa: E402

RAW = 2352
SUB_DATA = bytes([0, 0, 0x08, 0] * 2)
SUB_END = bytes([0, 0, 0x89, 0] * 2)
AUDIO_SECTORS = 40  # volume space past the data track, as CDDA entries make it on the real disc


def both16(v):
    return struct.pack("<H", v) + struct.pack(">H", v)


def both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def dir_record(name, lba, size, flags=0):
    n = name.encode()
    rec = bytes([0, 0]) + both32(lba) + both32(size) + bytes(7) + bytes([flags, 0, 0]) + both16(1)
    rec += bytes([len(n)]) + n
    if len(rec) % 2:
        rec += b"\0"
    return bytes([len(rec)]) + rec[1:]


def make_disc(files):
    """files: list of (name, lba, data). Root dir at LBA 18; the PVD volume runs past the image."""
    end = max(lba + max(1, -(-len(d) // 2048)) for _, lba, d in files)
    sectors = [bytes(2048)] * end
    subs = [SUB_DATA] * end
    root = dir_record("\0", 18, 2048, 2) + dir_record("\1", 18, 2048, 2)
    for name, lba, data in files:
        root += dir_record(name + ";1", lba, len(data))
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    pvd[80:88] = both32(end + AUDIO_SECTORS)
    pvd[156:190] = dir_record("\0", 18, 2048, 2)
    sectors[16] = bytes(pvd)
    subs[16] = bytes([0, 0, 0x09, 0] * 2)
    sectors[17] = b"\xffCD001" + bytes(2042)
    subs[17] = SUB_END
    sectors[18] = root + bytes(2048 - len(root))
    subs[18] = SUB_END
    for name, lba, data in files:
        n = max(1, -(-len(data) // 2048))
        padded = data + bytes(n * 2048 - len(data))
        for i in range(n):
            sectors[lba + i] = padded[i * 2048 : (i + 1) * 2048]
            subs[lba + i] = SUB_END if i == n - 1 else SUB_DATA
    return b"".join(cdsector.build_form1(i, subs[i], sectors[i]) for i in range(end))


A = b"A" * 3000
B = b"B" * 100
DISC = make_disc([("A.BIN", 20, A), ("B.BIN", 22, B)])


def test_load_lists_files():
    d = iso.load(DISC)
    assert {f.name: (f.lba, f.size) for f in d.files.values()} == {"A.BIN": (20, 3000), "B.BIN": (22, 100)}
    assert d.volume_sectors == 23 + AUDIO_SECTORS


def test_read_file():
    d = iso.load(DISC)
    assert iso.read_file(DISC, d, "A.BIN") == A


def test_empty_plan_is_identity():
    assert iso.apply(DISC, []) == DISC


def test_same_content_replace_is_identity():
    d = iso.load(DISC)
    assert iso.apply(DISC, iso.plan(DISC, d, {"A.BIN": A, "B.BIN": B})) == DISC


def test_in_place_replace_updates_size_only():
    d = iso.load(DISC)
    out = iso.apply(DISC, iso.plan(DISC, d, {"A.BIN": b"x" * 2100}))
    d2 = iso.load(out)
    assert (d2.files["A.BIN"].lba, d2.files["A.BIN"].size) == (20, 2100)
    assert iso.read_file(out, d2, "A.BIN") == b"x" * 2100
    assert iso.read_file(out, d2, "B.BIN") == B
    assert d2.volume_sectors == d.volume_sectors
    assert len(out) == len(DISC)


def test_shrinking_to_fewer_sectors_moves_end_subheader():
    d = iso.load(DISC)
    out = iso.apply(DISC, iso.plan(DISC, d, {"A.BIN": b"s" * 10}))
    assert out[20 * RAW + 16 : 20 * RAW + 24] == SUB_END
    assert iso.read_file(out, iso.load(out), "A.BIN") == b"s" * 10


def test_growth_past_allocated_sectors_is_refused():
    # No room to append: the data track is followed by audio tracks.
    d = iso.load(DISC)
    with pytest.raises(ValueError):
        iso.plan(DISC, d, {"A.BIN": b"g" * 4097})


def test_growth_within_last_sector_is_allowed():
    d = iso.load(DISC)
    out = iso.apply(DISC, iso.plan(DISC, d, {"A.BIN": b"g" * 4096}))
    assert iso.read_file(out, iso.load(out), "A.BIN") == b"g" * 4096


def test_written_sectors_have_valid_subheaders_and_ecc():
    d = iso.load(DISC)
    out = iso.apply(DISC, iso.plan(DISC, d, {"A.BIN": b"z" * 4000, "B.BIN": b"q" * 10}))
    arr = np.frombuffer(out, np.uint8).reshape(-1, RAW)
    assert (cdsector.complete_form1(arr) == arr).all()
    assert out[20 * RAW + 16 : 20 * RAW + 24] == SUB_DATA
    assert out[21 * RAW + 16 : 21 * RAW + 24] == SUB_END


def test_unknown_file_raises():
    with pytest.raises(KeyError):
        iso.plan(DISC, iso.load(DISC), {"NOPE.BIN": b""})


def test_expected_source_mismatch_raises():
    writes = iso.plan(DISC, iso.load(DISC), {"B.BIN": b"new"})
    tampered = bytearray(DISC)
    tampered[22 * RAW + 100] ^= 1
    with pytest.raises(ValueError):
        iso.apply(bytes(tampered), writes)


def test_duplicate_writes_raise():
    writes = iso.plan(DISC, iso.load(DISC), {"B.BIN": b"new"})
    with pytest.raises(ValueError):
        iso.apply(DISC, writes + writes[:1])


def test_write_past_image_end_raises():
    w = iso.Write("x", len(DISC) // RAW, None, bytes(RAW))
    with pytest.raises(ValueError):
        iso.apply(DISC, [w])


def test_multi_extent_file_rejected():
    raw = bytearray(DISC)
    root = 18 * RAW + 24
    data = bytes(raw[root : root + 2048])
    off = data.index(b"A.BIN;1") - 33
    raw[root + off + 25] |= 0x80
    with pytest.raises(ValueError):
        iso.load(bytes(raw))


def _set_subheader(raw, lba, sub):
    out = bytearray(raw)
    out[lba * RAW + 16 : lba * RAW + 24] = sub
    return bytes(out)


FORM2_AUDIO = bytes([1, 1, 0x64, 1] * 2)


def test_non_form1_file_is_refused_not_normalized():
    raw = _set_subheader(DISC, 20, FORM2_AUDIO)
    d = iso.load(raw)
    with pytest.raises(ValueError):
        iso.plan(raw, d, {"A.BIN": A})
    with pytest.raises(ValueError):
        iso.read_file(raw, d, "A.BIN")


def test_unexpected_form1_subheader_is_refused():
    raw = _set_subheader(DISC, 22, bytes([0, 0, 0x09, 0] * 2))
    with pytest.raises(ValueError):
        iso.plan(raw, iso.load(raw), {"B.BIN": b"x"})


def test_empty_file_cannot_be_filled():
    raw = make_disc([("A.BIN", 20, A), ("B.BIN", 22, B), ("E.BIN", 0, b"")])
    with pytest.raises(ValueError):
        iso.plan(raw, iso.load(raw), {"E.BIN": b"e" * 100})


@pytest.mark.parametrize("field,value", [(0, 0x10), (32, 200)], ids=["shorter_than_header", "name_past_record"])
def test_bad_directory_record_length_raises(field, value):
    raw = bytearray(DISC)
    root = 18 * RAW + 24
    off = bytes(raw[root : root + 2048]).index(b"B.BIN;1") - 33
    raw[root + off + field] = value
    with pytest.raises(ValueError):
        iso.load(bytes(raw))


BIN = os.environ.get("MITOUHOU_BIN") or next(
    iter(sorted(glob.glob(str(Path(__file__).resolve().parent.parent / "original" / "*(Track 01).bin")))), None
)


@pytest.mark.skipif(not BIN, reason="original disc image not available")
def test_corpus_rewrite_every_data_file_with_itself_is_identity():
    src = Path(BIN).read_bytes()
    d = iso.load(src)
    assert len(d.files) == 618 and d.volume_sectors == 250142 and len(src) // RAW == 64092
    data_files = {n: iso.read_file(src, d, n) for n in d.files if not n.startswith(("CDDA/", "MOVIE"))}
    assert len(data_files) == 539  # 618 records - 21 CDDA - 58 STR movies
    assert iso.apply(src, iso.plan(src, d, data_files)) == src


def test_plan_refuses_non_bytes_content():
    with pytest.raises(TypeError):
        iso.plan(DISC, iso.load(DISC), {"B.BIN": 100})


def test_overlapping_extents_are_rejected():
    raw = make_disc([("A.BIN", 20, A), ("B.BIN", 21, B)])  # A spans 20-21
    with pytest.raises(ValueError):
        iso.load(raw)
