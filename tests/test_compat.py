import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import compat  # noqa: E402

FILES = Path(__file__).resolve().parent.parent / "work" / "files"
NAMES = ["SLPS_006.62", "START.BIN", "SUZU_0.BIN", "SUZU_1.BIN", "SYSTEM.CNF"]


@pytest.fixture
def files():
    if not all((FILES / n).exists() for n in NAMES):
        pytest.skip("extracted game files not available")
    return {n: bytearray((FILES / n).read_bytes()) for n in NAMES}


def test_compat_moves_start_bin_and_its_references_down_by_0x800(files):
    assert compat.apply(files) == sorted(NAMES)
    word = lambda n, off: struct.unpack_from("<I", files[n], off)[0]
    assert word("SLPS_006.62", 0x8001319C - 0x80010000 + 0x800) & 0xFFFF == 0xF704
    assert b"STACK = 801FF700" in files["SYSTEM.CNF"]
    # the 2048-byte sector read at the new address ends inside 2 MB of RAM
    assert 0x801FF704 + 2048 <= 0x80200000


def test_compat_refuses_files_it_does_not_recognise(files):
    files["START.BIN"][0x34] ^= 1
    with pytest.raises(ValueError):
        compat.apply(files)
