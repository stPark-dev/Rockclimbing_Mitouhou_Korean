"""Emulator compatibility fix: move START.BIN below the end of RAM (docs/survey.md §9.1).

The game loads START.BIN (164 bytes, the mountain module loader) to 0x801FFF04, right
above the initial stack. CD reads move whole 2048-byte sectors, so 0x704 bytes land past
the 2 MB end of RAM. The game set 2 MB mode (SetMem(2)) and the overflow is lost, but
emulators either wrap it to address 0 (Mednafen, PCSX-Redux: the kernel call stubs are
wiped right after boot) or drop the whole transfer (DuckStation: START.BIN is missing and
the game crashes after the travel movie, on the way to the mountain).

The fix moves the stack top and START.BIN down by 0x800, so the sector fits in RAM, and
moves every reference with them. Each patch checks the original instruction first.
"""
import struct

SHIFT = 0x800
EXE = "SLPS_006.62"
EXE_BASE, EXE_HEADER = 0x80010000, 0x800

# (file, address or file offset, original word, patched word)
_PATCHES = [
    # crt0: ori $sp, $sp, 0xff00 -> 0xf700 (stack top 0x801FFF00)
    (EXE, 0x80011C94, 0x37BDFF00, 0x37BDF700),
    # START.BIN load address: ori $a1, $a1, 0xff04 (0x801FFF04)
    (EXE, 0x8001319C, 0x34A5FF04, 0x34A5F704),
    # START.BIN entry points 0x801FFF28 / 0x801FFF68: addiu $a0, $a0, -0xd8 / -0x98
    (EXE, 0x80013854, 0x2484FF28, 0x2484F728),
    (EXE, 0x80013864, 0x2484FF68, 0x2484F768),
    (EXE, 0x80020610, 0x2484FF28, 0x2484F728),
    (EXE, 0x80020EE8, 0x2484FF68, 0x2484F768),
    # START.BIN's own file name strings 0x801FFF08 / 0x801FFF18
    ("START.BIN", 0x34, 0x2484FF08, 0x2484F708),
    ("START.BIN", 0x74, 0x2484FF18, 0x2484F718),
    # SUZU_0 / SUZU_1 read START.BIN's first word: lw $a1, -0xfc($a1)
    ("SUZU_0.BIN", 0x3AC, 0x8CA5FF04, 0x8CA5F704),
    ("SUZU_1.BIN", 0xA70, 0x8CA5FF04, 0x8CA5F704),
]
_CNF = (b"STACK = 801FFF00", b"STACK = 801FF700")


def _offset(name, at):
    return at - EXE_BASE + EXE_HEADER if name == EXE else at


def apply(files):
    """Patch the bytearrays in `files` (name -> bytearray) in place. Returns the patched names."""
    for name, at, old, new in _PATCHES:
        off = _offset(name, at)
        got = struct.unpack_from("<I", files[name], off)[0]
        if got != old:
            raise ValueError(f"{name} {at:#x}: expected {old:08x}, found {got:08x}")
    cnf = files["SYSTEM.CNF"]
    if bytes(cnf).count(_CNF[0]) != 1:
        raise ValueError("SYSTEM.CNF: STACK line not found")
    for name, at, old, new in _PATCHES:
        struct.pack_into("<I", files[name], _offset(name, at), new)
    at = bytes(cnf).find(_CNF[0])
    cnf[at:at + len(_CNF[1])] = _CNF[1]
    return sorted({p[0] for p in _PATCHES} | {"SYSTEM.CNF"})
