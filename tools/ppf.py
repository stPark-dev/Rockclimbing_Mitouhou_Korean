"""PPF 3.0 patch for track 1 (the distributable patch: no game data, only the changed bytes).

Header (60 bytes): "PPF30", encoding 2, a 50-byte description, image type 0 (BIN),
block check 1, undo 0, a zero byte; then the 1024 bytes of the original at 0x9320 that
patchers compare before applying; then records of an 8-byte offset, a length (1-255) and the
new bytes.

usage: ppf.py <original track 01 .bin> <patched .bin> <out .ppf> [description]
"""

import struct
import sys
from pathlib import Path

CHECK_AT, CHECK_LEN, DESC_LEN, MAX_RUN, RECORD_HEAD = 0x9320, 1024, 50, 255, 9


def _runs(old, new):
    """(offset, new bytes) records; an unchanged gap shorter than a record header (9 bytes) is
    cheaper written inside one record than split, so it joins."""
    import numpy as np
    diff = np.flatnonzero(np.frombuffer(old, np.uint8) != np.frombuffer(new, np.uint8))
    if not len(diff):
        return
    start = last = int(diff[0])
    for p in diff[1:].tolist():
        if p - last <= RECORD_HEAD and p - start < MAX_RUN:
            last = p
            continue
        yield start, new[start:last + 1]
        start = last = p
    yield start, new[start:last + 1]


def make(old, new, description):
    if len(old) != len(new):
        raise ValueError("the patched image must keep the size of the original")
    desc = description.encode("ascii")
    if len(desc) > DESC_LEN:
        raise ValueError(f"description is longer than {DESC_LEN} bytes")
    out = bytearray(b"PPF30" + bytes([2]) + desc.ljust(DESC_LEN) + bytes([0, 1, 0, 0]))
    out += old[CHECK_AT:CHECK_AT + CHECK_LEN]
    for off, data in _runs(old, new):
        out += struct.pack("<QB", off, len(data)) + data
    return bytes(out)


def apply(old, patch):
    if patch[:6] != b"PPF30\x02" or patch[57] != 1:
        raise ValueError("not a PPF 3.0 patch with a block check")
    if old[CHECK_AT:CHECK_AT + CHECK_LEN] != patch[60:60 + CHECK_LEN]:
        raise ValueError("this patch is for another image")
    out, p = bytearray(old), 60 + CHECK_LEN
    while p < len(patch):
        off, n = struct.unpack_from("<QB", patch, p)
        out[off:off + n] = patch[p + 9:p + 9 + n]
        p += 9 + n
    return bytes(out)


def main():
    old, new = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]).read_bytes()
    patch = make(old, new, sys.argv[4] if len(sys.argv) > 4 else "Rock Climbing Mitouhou Korean")
    if apply(old, patch) != new:
        raise ValueError("patch does not reproduce the patched image")
    Path(sys.argv[3]).write_bytes(patch)
    print(sys.argv[3], len(patch))


if __name__ == "__main__":
    main()
