import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ppf  # noqa: E402


def image(n=0x9320 + 0x2000, seed=1):
    rnd = random.Random(seed)
    return bytes(rnd.randrange(256) for _ in range(n))


def test_patch_round_trips_scattered_and_long_changes():
    old = image()
    new = bytearray(old)
    new[0] ^= 1                                  # first byte
    new[100:100 + 600] = bytes(600)              # a run longer than one 255-byte record
    new[0x9320 + 5] ^= 0xFF                      # inside the block-check area
    new[-1] ^= 0x80                              # last byte
    patch = ppf.make(old, bytes(new), "Rock Climbing KO v1.0-beta")
    assert patch[:5] == b"PPF30" and patch[5] == 2
    assert ppf.apply(old, patch) == bytes(new)


def test_header_carries_description_and_the_block_check_of_the_original():
    old = image()
    patch = ppf.make(old, old[:1] + b"\x00" + old[2:], "desc")
    assert patch[6:56] == b"desc".ljust(50)
    assert patch[56:60] == bytes([0, 1, 0, 0])   # BIN image, block check on, no undo data
    assert patch[60:60 + 1024] == old[0x9320:0x9320 + 1024]


def test_apply_refuses_another_image_and_make_refuses_a_size_change():
    old = image()
    patch = ppf.make(old, bytes([old[0] ^ 1]) + old[1:], "x")
    with pytest.raises(ValueError):
        ppf.apply(image(seed=2), patch)
    with pytest.raises(ValueError):
        ppf.make(old, old + b"\x00", "x")
    with pytest.raises(ValueError):
        ppf.make(old, old, "d" * 51)


def records(patch):
    import struct
    p, out = 60 + 1024, []
    while p < len(patch):
        off, n = struct.unpack_from("<QB", patch, p)
        out.append((off, n))
        p += 9 + n
    return out


def test_short_unchanged_gaps_join_one_record_and_long_ones_split():
    old = image()
    new = bytearray(old)
    for i in (1000, 1002, 1010):          # gaps of 1 and 7 bytes: cheaper inside one record
        new[i] ^= 1
    new[1030] ^= 1                        # gap of 19 bytes: its own record
    patch = ppf.make(old, bytes(new), "x")
    assert records(patch) == [(1000, 11), (1030, 1)]
    assert ppf.apply(old, patch) == bytes(new)
