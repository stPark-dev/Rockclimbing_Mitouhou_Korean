"""ISO 9660 file replacement on the raw MODE2/2352 data track (track 1) of a
multi-track image.

The PVD volume runs past the data track into the CD-DA tracks, and the track
has no free sectors after its last file, so a replacement must fit the file's
original sector count and is always written in place; anything larger is
refused. Only the file's directory record size changes. Every change is a
whole-sector Write with the expected source sector; `apply` verifies them all
before producing output and audits the final diff. Files containing non-Form 1
sectors (XA/STR) or other subheaders are refused rather than normalized. New
data sectors use the subheaders observed on this disc (body 0x08, last sector
0x89).

Adapted from the Rurouni Kenshin project's iso.py (sibling repository).
"""

import struct
from dataclasses import dataclass

import numpy as np

import cdsector

RAW = cdsector.RAW
PVD_LBA = 16
SUB_DATA = bytes([0, 0, 0x08, 0] * 2)
SUB_END = bytes([0, 0, 0x89, 0] * 2)


@dataclass(frozen=True)
class FileRec:
    name: str
    lba: int
    size: int
    rec_lba: int
    rec_off: int


@dataclass(frozen=True)
class Disc:
    files: dict
    volume_sectors: int


@dataclass(frozen=True)
class Write:
    writer: str
    lba: int
    expected: bytes  # original raw sector
    new: bytes


def _user(raw, lba):
    o = lba * RAW + 24
    if o + 2048 > len(raw):
        raise ValueError(f"LBA {lba} beyond image end")
    return raw[o : o + 2048]


def _sectors(size):
    return max(1, -(-size // 2048))


def load(raw):
    pvd = _user(raw, PVD_LBA)
    if pvd[0:6] != b"\x01CD001":
        raise ValueError("no primary volume descriptor at LBA 16")
    files = {}

    def walk(lba, size, prefix, seen):
        if lba in seen:
            raise ValueError(f"directory loop at LBA {lba}")
        seen = seen | {lba}
        for s in range(_sectors(size)):
            data = _user(raw, lba + s)
            p = 0
            while p < 2048 and data[p]:
                ln = data[p]
                if ln < 34 or p + ln > 2048 or 33 + data[p + 32] > ln:
                    raise ValueError(f"bad directory record length {ln} at LBA {lba + s} +{p}")
                rec = data[p : p + ln]
                ext, sz, flags, nl = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0], rec[25], rec[32]
                name = rec[33 : 33 + nl]
                if flags & 0x80:
                    raise ValueError(f"multi-extent record {name!r} is not supported")
                if name not in (b"\0", b"\1"):
                    text = name.decode("ascii").split(";")[0]
                    if flags & 2:
                        walk(ext, sz, prefix + text + "/", seen)
                    else:
                        files[prefix + text] = FileRec(prefix + text, ext, sz, lba + s, p)
                p += ln

    root = pvd[156:190]
    walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "", frozenset())
    prev = None
    for f in sorted((f for f in files.values() if f.size), key=lambda f: f.lba):
        if prev and f.lba < prev.lba + _sectors(prev.size):
            raise ValueError(f"extents of {prev.name} and {f.name} overlap; a rewrite would change both")
        prev = f
    return Disc(files, struct.unpack_from("<I", pvd, 80)[0])


def _extent_sectors(raw, f):
    """Raw sectors of a file's extent; refuses anything that is not Form 1."""
    out = []
    for i in range(-(-f.size // 2048)):
        sec = raw[(f.lba + i) * RAW : (f.lba + i + 1) * RAW]
        if not cdsector.is_form1(sec):
            raise ValueError(f"{f.name}: LBA {f.lba + i} is not a Form 1 sector")
        out.append(sec)
    return out


def read_file(raw, disc, name):
    f = disc.files[name]
    return b"".join(s[24:0x818] for s in _extent_sectors(raw, f))[: f.size]


def _encode(lbas, subs, datas):
    arr = np.zeros((len(lbas), RAW), np.uint8)
    for i, (lba, sub, data) in enumerate(zip(lbas, subs, datas)):
        arr[i, :12] = np.frombuffer(cdsector.SYNC, np.uint8)
        arr[i, 12:16] = np.frombuffer(cdsector.header(lba), np.uint8)
        arr[i, 16:24] = np.frombuffer(sub, np.uint8)
        arr[i, 24:0x818] = np.frombuffer(data, np.uint8)
    return [r.tobytes() for r in cdsector.complete_form1(arr)] if lbas else []


def _both32(v):
    return struct.pack("<I", v) + struct.pack(">I", v)


def plan(raw, disc, changes):
    """Plan in-place Writes replacing each named file's content."""
    if len(raw) % RAW:
        raise ValueError("image is not a whole number of raw sectors")
    lbas, subs, datas, writers = [], [], [], []
    dir_edits = {}
    for f in sorted((disc.files[n] for n in changes), key=lambda f: f.lba):
        if not f.size:
            raise ValueError(f"{f.name}: empty file owns no sector to write into")
        odd = [s[16:24] for s in _extent_sectors(raw, f) if s[16:24] not in (SUB_DATA, SUB_END)]
        if odd:
            raise ValueError(f"{f.name}: unexpected subheader {odd[0].hex()}; refusing to rewrite")
        data = changes[f.name]
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"{f.name}: replacement must be bytes, not {type(data).__name__}")
        data = bytes(data)
        n = _sectors(len(data))
        if n > _sectors(f.size):
            raise ValueError(f"{f.name}: {len(data)} bytes need {n} sectors, only {_sectors(f.size)} allocated")
        padded = data + bytes(n * 2048 - len(data))
        for i in range(n):
            lbas.append(f.lba + i)
            subs.append(SUB_END if i == n - 1 else SUB_DATA)
            datas.append(padded[i * 2048 : (i + 1) * 2048])
            writers.append(f"file:{f.name}")
        sec = dir_edits.setdefault(f.rec_lba, bytearray(_user(raw, f.rec_lba)))
        sec[f.rec_off + 10 : f.rec_off + 18] = _both32(len(data))
    for lba, data in dir_edits.items():
        lbas.append(lba)
        subs.append(raw[lba * RAW + 16 : lba * RAW + 24])
        datas.append(bytes(data))
        writers.append("dir")
    sectors = _encode(lbas, subs, datas)
    return [Write(w, lba, raw[lba * RAW : (lba + 1) * RAW], s) for w, lba, s in zip(writers, lbas, sectors)]


def plan_sectors(raw, writer, users):
    """Writes replacing the user data of Form 1 sectors in place ({lba: 2048 bytes}),
    keeping their subheaders: movie video sectors, which sit between XA audio."""
    lbas = sorted(users)
    for lba in lbas:
        if not cdsector.is_form1(raw[lba * RAW:(lba + 1) * RAW]):
            raise ValueError(f"{writer}: LBA {lba} is not a Form 1 sector")
        if len(users[lba]) != 2048:
            raise ValueError(f"{writer}: LBA {lba} needs 2048 bytes")
    subs = [raw[lba * RAW + 16:lba * RAW + 24] for lba in lbas]
    sectors = _encode(lbas, subs, [users[lba] for lba in lbas])
    return [Write(writer, lba, raw[lba * RAW:(lba + 1) * RAW], sec) for lba, sec in zip(lbas, sectors)]


def apply(source, writes):
    """Verify all writes against the source, then return the patched image."""
    if len(source) % RAW:
        raise ValueError("source is not a whole number of raw sectors")
    total = len(source) // RAW
    lbas = [w.lba for w in writes]
    if len(set(lbas)) != len(lbas):
        raise ValueError("overlapping writes to the same sector")
    for w in writes:
        if not 0 <= w.lba < total:
            raise ValueError(f"{w.writer}: LBA {w.lba} is outside the data track")
        if len(w.new) != RAW:
            raise ValueError(f"{w.writer}: LBA {w.lba} is not a full raw sector")
        if w.expected is None or source[w.lba * RAW : (w.lba + 1) * RAW] != w.expected:
            raise ValueError(f"{w.writer}: LBA {w.lba} does not match expected source")
    out = bytearray(source)
    for w in writes:
        out[w.lba * RAW : (w.lba + 1) * RAW] = w.new
    _audit(source, bytes(out), set(lbas))
    return bytes(out)


def _audit(source, out, planned):
    if len(out) != len(source):
        raise ValueError("output size differs from the source")
    a = np.frombuffer(source, np.uint8).reshape(-1, RAW)
    b = np.frombuffer(out, np.uint8).reshape(-1, RAW)
    changed = set(np.nonzero((a != b).any(axis=1))[0].tolist())
    stray = changed - planned
    if stray:
        raise ValueError(f"unplanned changes at LBA {sorted(stray)[:5]}")
