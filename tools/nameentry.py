"""Hangul name entry (D2, D10: paged syllable table), docs/survey.md §10.2.

A name is 8 bytes of input-table numbers at 0x80070EA4. The executable draws a number by
looking it up in the table at 0x80046548 (0x800210B0, 0x80021218); the name screen
(KWAMENU 0x800BA830) stores row*20 + col + 1 from a 20 x 7 kana picture.

This module turns that into three pages of 18 x 6 Hangul syllables (252 cells, numbers 1-253):
- executable: the table area 0x800462F4-0x80046780 is rewritten as halfword offsets from its start
  followed by 1- or 2-byte glyph codes (both draw functions only read the first code), and the
  two lookups use lhu + base instead of lw;
- KWAMENU: the number becomes row*18 + col + page offset, the page is switched with L1/R1, and the
  syllables of the current page are drawn by a text window over the emptied keyboard frame;
- number 141 stays the choice cursor ▶: the climbing and camp choices put it in an {F8} slot
  (original table entry 141, past the 140 kana cells), so the cells after it are numbered one higher.
"""

import struct
from pathlib import Path

SYLLABLES = Path(__file__).resolve().parent.parent / "tables" / "name_syllables.txt"
SPACE = " "
PAGES, ROWS, COLS = 3, 6, 18  # 6 rows: the text window line pitch is 14 px
TABLE_START, TABLE_END = 0x800462F4, 0x80046780  # old entries + old pointer table, only used here
CURSOR, CURSOR_GLYPH = 141, 29  # choice cursor number and its glyph ▶ (code 0x1E) in the original font

REG = {n: i for i, n in enumerate(
    "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra".split())}


def _r(op, rs, rt, rd, sh, fn):
    return op << 26 | REG[rs] << 21 | REG[rt] << 16 | REG[rd] << 11 | sh << 6 | fn


def _i(op, rs, rt, imm):
    return op << 26 | REG[rs] << 21 | REG[rt] << 16 | (imm & 0xFFFF)


NOP = 0


def sll(rd, rt, sh): return _r(0, "zero", rt, rd, sh, 0)
def addu(rd, rs, rt): return _r(0, rs, rt, rd, 0, 0x21)
def jr(rs): return _r(0, rs, "zero", "zero", 0, 8)
def addiu(rt, rs, imm): return _i(9, rs, rt, imm)
def andi(rt, rs, imm): return _i(0xC, rs, rt, imm)
def ori(rt, rs, imm): return _i(0xD, rs, rt, imm)
def xori(rt, rs, imm): return _i(0xE, rs, rt, imm)
def lui(rt, imm): return _i(0xF, "zero", rt, imm)
def lw(rt, off, rs): return _i(0x23, rs, rt, off)
def lhu(rt, off, rs): return _i(0x25, rs, rt, off)
def lbu(rt, off, rs): return _i(0x24, rs, rt, off)
def sw(rt, off, rs): return _i(0x2B, rs, rt, off)
def sh_(rt, off, rs): return _i(0x29, rs, rt, off)
def beq(rs, rt, words): return _i(4, rs, rt, words)
def bne(rs, rt, words): return _i(5, rs, rt, words)
def jal(addr): return 3 << 26 | (addr >> 2) & 0x3FFFFFF


def hi_lo(addr):
    """lui/addiu halves of an address (addiu sign-extends)."""
    lo = addr & 0xFFFF
    return (addr >> 16) + (1 if lo & 0x8000 else 0) & 0xFFFF, lo - 0x10000 if lo & 0x8000 else lo


def syllables():
    return SYLLABLES.read_text(encoding="utf-8").strip()


def layout():
    """Characters of every cell, page by page and row by row; the last cell is the space key."""
    cells = list(syllables()) + [SPACE]
    if len(cells) > min(PAGES * ROWS * COLS, 253):  # numbers skip CURSOR and stop below 0xFF
        raise ValueError(f"{len(cells)} cells for {PAGES * ROWS * COLS} keyboard positions")
    if len(set(cells)) != len(cells):
        raise ValueError("a syllable appears twice in tables/name_syllables.txt")
    return cells


def number(k):
    """Name byte of the k-th cell (1-based): CURSOR is skipped."""
    return k if k < CURSOR else k + 1


def index_of(page, row, col):
    return number(page * ROWS * COLS + row * COLS + col + 1)


def code(k):
    return bytes([k + 1]) if k < 0xEF else bytes([0xF0 + ((k - 0xEF) >> 8), (k - 0xEF) & 0xFF])


def glyph_table(cells, limit=TABLE_END - TABLE_START):
    """Halfword offsets for every byte value (relative to the table start), then the codes.
    0, 0xFF and unused numbers point to the blank code FD, CURSOR to ▶."""
    lay = layout()
    n = 256
    head = 2 * n
    body = bytearray([0xFD])
    offs = [head] * n
    offs[CURSOR] = head + len(body)
    body += code(CURSOR_GLYPH)
    for i, ch in enumerate(lay, 1):
        if ch == SPACE:
            continue
        offs[number(i)] = head + len(body)
        body += code(cells[ch])
    out = struct.pack(f"<{n}H", *offs) + bytes(body)
    if len(out) > limit:
        raise ValueError(f"name glyph table needs {len(out)} bytes, {limit} available")
    return out


def page_texts():
    lay = layout()
    pages = []
    for p in range(PAGES):
        cells = lay[p * ROWS * COLS:(p + 1) * ROWS * COLS]
        rows = ["".join(cells[r * COLS:(r + 1) * COLS]).rstrip(SPACE) for r in range(ROWS)]
        pages.append("\n".join(r for r in rows if r))
    return pages


# ---- executable: lookups in the two draw functions -------------------------------------------
EXE_LOAD = 0x80010000 - 0x800  # file offset = address - EXE_LOAD
EXE_PATCH = {  # address: (original word, new word)
    0x80021114: (0x3C148004, None),  # lui s4, 0x8004       -> table base (set in exe_patches)
    0x80021118: (0x26946548, None),  # addiu s4, s4, 0x6548
    0x80021138: (0x00031080, sll("v0", "v1", 1)),
    0x80021140: (0x8C450000, lhu("a1", 0, "v0")),
    0x80021148: (0x10A00023, addu("a1", "a1", "s4")),  # was beqz a1: every number now has an entry
    0x80021310: (0x3C148004, None),
    0x80021314: (0x26946548, None),
    0x80021358: (0x00041080, sll("v0", "a0", 1)),
    0x80021360: (0x8C420000, lhu("v0", 0, "v0")),
    0x80021368: (0x10400007, addu("v0", "v0", "s4")),  # was beqz v0: number 0 points to FD
}


def exe_patches():
    hi, lo = hi_lo(TABLE_START)
    out = dict(EXE_PATCH)
    for a in (0x80021114, 0x80021310):
        out[a] = (out[a][0], lui("s4", hi))
    for a in (0x80021118, 0x80021314):
        out[a] = (out[a][0], addiu("s4", "s4", lo))
    return out


def patch_exe(exe, cells):
    for addr, (old, new) in exe_patches().items():
        o = addr - EXE_LOAD
        if struct.unpack_from("<I", exe, o)[0] != old:
            raise ValueError(f"unexpected instruction at {addr:#x}: not the supported revision")
        struct.pack_into("<I", exe, o, new)
    table = glyph_table(cells)
    o = TABLE_START - EXE_LOAD
    exe[o:TABLE_END - EXE_LOAD] = table + bytes(TABLE_END - TABLE_START - len(table))
    return len(table)


# ---- KWAMENU: name screen ----------------------------------------------------------------------
KW_BASE = 0x800AFF18
CAVE_START, CAVE_END = 0x12FB8, 0x133E8  # unreferenced development dummies "ｘｘ…" (docs/survey.md §10.2)
WIN_OPEN, WIN_CLOSE = 0x80014CAC, 0x8001858C  # text window (string, x, y, mode) -> handle; close(handle)
PAD_EDGE = 0x800D12CC  # buttons pressed this frame
L1R1 = 0x000C
WIN_X, WIN_Y, ROW_PITCH = 44, 64, 14  # first cell on screen; text line pitch (measured on screen)
CUR_X_OFF, CUR_Y_OFF = 54, 68  # cursor ring = table value + offset (ring is drawn ~11 px left of it)
DEFAULT_NAME = "클라이머"

KW_HOOKS = {  # address: original word
    0x800BA8F0: ori("s0", "zero", 5),    # name length after the default name -> jal init
    0x800BA90C: lw("v0", 0, "s6"),       # loop top -> jal loop
    0x800BA958: ori("s2", "zero", 0x13),  # left wrap to the last column
    0x800BA970: 0x2A220007,              # slti v0, s1, 7: last keyboard row
    0x800BA978: 0x2A420014,              # slti v0, s2, 20: right wrap
    0x800BA980: 0x2A220007,              # slti v0, s1, 7: the same row check after a right press
    0x800BA990: ori("s1", "zero", 6),
    0x800BA9D4: sll("v0", "s1", 2),      # number = row*20 + col + 1
    0x800BA9D8: addu("v0", "v0", "s1"),
    0x800BA9DC: sll("v0", "v0", 2),
    0x800BA9E0: addu("v0", "v0", "s2"),
    0x800BA9E4: addiu("v0", "v0", 1),
    0x800BAADC: jal(0x80018D30),           # confirm sound when 終了 is chosen -> jal exit
    0x800BAA30: addiu("a1", "a1", 0x3D),  # cursor x offset
    0x800BAA38: addiu("a2", "a2", 0x47),  # cursor y offset
}
COL_TABLE, ROW_TABLE, NAME_TABLE = 0x800CD058, 0x800CD06C, 0x800CD074
KANA_COLS = bytes([0, 9, 18, 27, 36, 54, 63, 72, 81, 90, 109, 119, 127, 136, 145, 163, 172, 181, 190, 199])
KANA_ROWS = bytes([0, 9, 18, 27, 36, 55, 64])
KANA_NAME = bytes([0x21, 0x4C, 0x0C, 0x24, 0x76])  # クライマー


def slti(rt, rs, imm): return _i(0xA, rs, rt, imm)


class Asm:
    """Tiny two-pass assembler: items are words, ('label', name) or callables(addr, labels) -> word."""

    def __init__(self, base):
        self.base, self.items = base, []

    def __call__(self, *items):
        self.items.extend(items)

    def label(self, name):
        self.items.append(("label", name))

    def b(self, op, rs, rt, name):
        self.items.append(lambda a, L: _i(op, rs, rt, (L[name] - a - 4) >> 2))

    def jal(self, name):
        self.items.append(lambda a, L: jal(L[name]))

    def build(self):
        labels, a = {}, self.base
        for it in self.items:
            if isinstance(it, tuple) and it[0] == "label":
                labels[it[1]] = a
            elif isinstance(it, (bytes, bytearray)):
                a += len(it)
            else:
                a += 4
        out, a = bytearray(), self.base
        for it in self.items:
            if isinstance(it, tuple):
                continue
            if isinstance(it, (bytes, bytearray)):
                out += it
                a += len(it)
                continue
            word = it(a, labels) if callable(it) else it
            out += struct.pack("<I", word)
            a += 4
        return bytes(out), labels


def cave(strings):
    """Variables, the two page strings and the hook routines, from KWAMENU CAVE_START."""
    base = KW_BASE + CAVE_START
    A = Asm(base)
    A.label("vars")
    A(bytes(12))                    # +0 window handle, +4 page, +8 number offset of the page
    A.label("strptr")               # +12 page strings
    A(*[(lambda n: lambda a, L: L[n])(f"page{p}") for p in range(PAGES)])
    A.label("offsets")              # +24 number offset of each page
    A(*[p * ROWS * COLS for p in range(PAGES)])
    A(0)                            # +36 closed: set when 終了 is chosen, so L1/R1 cannot reopen the window
    for p in range(PAGES):
        A.label(f"page{p}"); A(strings[p])
    A(bytes(-sum(len(x) for x in strings) % 4))
    vhi, vlo = hi_lo(base)

    # show: close the old window, set the number offset and open the window of the current page
    A.label("show")
    A(addiu("sp", "sp", -24), sw("ra", 16, "sp"), sw("s0", 20, "sp"),
      lui("s0", vhi), addiu("s0", "s0", vlo),
      lw("a0", 0, "s0"), NOP)
    A.b(4, "a0", "zero", "show_open"); A(NOP)
    A(jal(WIN_CLOSE), NOP)
    A.label("show_open")
    A(lw("t0", 4, "s0"), NOP, sll("t2", "t0", 2), addu("t2", "t2", "s0"),
      lw("t1", 12 + 4 * PAGES, "t2"), NOP, sw("t1", 8, "s0"),
      lw("a0", 12, "t2"), ori("a1", "zero", WIN_X), ori("a2", "zero", WIN_Y),
      jal(WIN_OPEN), ori("a3", "zero", 3),
      sw("v0", 0, "s0"),
      lw("ra", 16, "sp"), lw("s0", 20, "sp"), addiu("sp", "sp", 24), jr("ra"), NOP)

    # init (replaces "ori s0, zero, 5" at the start of the name screen)
    A.label("init")
    A(addiu("sp", "sp", -24), sw("ra", 16, "sp"),
      lui("t0", vhi), sw("zero", vlo, "t0"), sw("zero", vlo + 4, "t0"), sw("zero", vlo + 36, "t0"))
    A.jal("show"); A(NOP)
    A(lw("ra", 16, "sp"), ori("s0", "zero", len(DEFAULT_NAME)), addiu("sp", "sp", 24), jr("ra"), NOP)

    # loop (replaces "lw v0, 0(s6)" at the loop top): L1/R1 switch the page
    A.label("loop")
    A(addiu("sp", "sp", -24), sw("ra", 16, "sp"),
      lui("t0", PAD_EDGE >> 16 & 0xFFFF), lw("t0", PAD_EDGE & 0xFFFF, "t0"), NOP,
      andi("t0", "t0", L1R1))
    A.b(4, "t0", "zero", "loop_done"); A(NOP)
    # R1 (8): next page, L1 (4): previous page, wrapping around
    A(lui("t1", vhi), lw("t3", vlo + 36, "t1"), NOP)
    A.b(5, "t3", "zero", "loop_done"); A(NOP)
    A(lw("t2", vlo + 4, "t1"), andi("t3", "t0", 8))
    A.b(4, "t3", "zero", "loop_l1"); A(andi("t3", "t0", 4))
    A(addiu("t2", "t2", 1))
    A.label("loop_l1")
    A.b(4, "t3", "zero", "loop_wrap"); A(NOP)
    A(addiu("t2", "t2", PAGES - 1))
    A.label("loop_wrap")
    A(slti("t3", "t2", PAGES))
    A.b(5, "t3", "zero", "loop_store"); A(NOP)
    A(addiu("t2", "t2", -PAGES))
    A.label("loop_store")
    A(sw("t2", vlo + 4, "t1"))
    A.jal("show"); A(NOP)
    A.label("loop_done")
    A(lw("ra", 16, "sp"), lw("v0", 0, "s6"), addiu("sp", "sp", 24), jr("ra"), NOP)

    # exit (replaces the confirm sound when 終了 is chosen): the menu framework closes only its own
    # title window, so close the keyboard window here, then play the sound as before
    A.label("exit")
    A(addiu("sp", "sp", -24), sw("ra", 16, "sp"),
      lui("t0", vhi), lw("a0", vlo, "t0"), NOP)
    A.b(4, "a0", "zero", "exit_sound"); A(NOP)
    A(jal(WIN_CLOSE), NOP, lui("t0", vhi), sw("zero", vlo, "t0"))
    A.label("exit_sound")
    A(lui("t0", vhi), ori("t1", "zero", 1), sw("t1", vlo + 36, "t0"))
    A(jal(0x80018D30), ori("a0", "zero", 2),
      lw("ra", 16, "sp"), NOP, addiu("sp", "sp", 24), jr("ra"), NOP)

    # number: v0 = row*18 + col, then + 1 + page offset, then past CURSOR (replaces "addiu v0, v0, 1")
    A.label("number")
    # cells past the last syllable (third page) enter a space
    A(lui("t0", vhi), lw("t0", vlo + 8, "t0"), NOP, addiu("v0", "v0", 1), addu("v0", "v0", "t0"),
      slti("t0", "v0", len(layout()) + 1))
    A.b(5, "t0", "zero", "number_done"); A(NOP)
    A(ori("v0", "zero", layout().index(SPACE) + 1))
    A.label("number_done")
    A(slti("t0", "v0", CURSOR), xori("t0", "t0", 1), jr("ra"), addu("v0", "v0", "t0"))
    code_bytes, labels = A.build()
    if len(code_bytes) > CAVE_END - CAVE_START:
        raise ValueError(f"name screen code needs {len(code_bytes)} bytes, {CAVE_END - CAVE_START} available")
    return code_bytes, labels


def kw_patches(labels):
    return {
        0x800BA8F0: jal(labels["init"]),
        0x800BA90C: jal(labels["loop"]),
        0x800BA958: ori("s2", "zero", COLS - 1),
        0x800BA970: slti("v0", "s1", ROWS),
        0x800BA978: slti("v0", "s2", COLS),
        0x800BA980: slti("v0", "s1", ROWS),
        0x800BA990: ori("s1", "zero", ROWS - 1),
        0x800BA9D4: sll("v0", "s1", 3),
        0x800BA9D8: addu("v0", "v0", "s1"),
        0x800BA9DC: sll("v0", "v0", 1),
        0x800BA9E0: addu("v0", "v0", "s2"),
        0x800BA9E4: jal(labels["number"]),  # delay slot "addiu s0, s0, 1" runs first
        0x800BAADC: jal(labels["exit"]),    # delay slot "ori a0, zero, 2" runs first
        0x800BAA30: addiu("a1", "a1", CUR_X_OFF),
        0x800BAA38: addiu("a2", "a2", CUR_Y_OFF),
    }


def default_name():
    lay = layout()
    return bytes(number(lay.index(ch) + 1) for ch in DEFAULT_NAME)


def patch_kwamenu(kw, original_cave, strings):
    """strings: the page texts already encoded (FE newlines, FF end)."""
    if bytes(kw[CAVE_START:CAVE_END]) != original_cave:
        raise ValueError("KWAMENU cave range was changed by something else")
    for addr, old in KW_HOOKS.items():
        if struct.unpack_from("<I", kw, addr - KW_BASE)[0] != old:
            raise ValueError(f"unexpected instruction at {addr:#x}: not the supported revision")
    for addr, want in ((COL_TABLE, KANA_COLS), (ROW_TABLE, KANA_ROWS), (NAME_TABLE, KANA_NAME)):
        if bytes(kw[addr - KW_BASE:addr - KW_BASE + len(want)]) != want:
            raise ValueError(f"unexpected data at {addr:#x}: not the supported revision")
    body, labels = cave(strings)
    kw[CAVE_START:CAVE_END] = body + bytes(CAVE_END - CAVE_START - len(body))
    for addr, word in kw_patches(labels).items():
        struct.pack_into("<I", kw, addr - KW_BASE, word)
    o = COL_TABLE - KW_BASE
    kw[o:o + 20] = bytes(12 * c for c in range(COLS)) + bytes(20 - COLS)
    o = ROW_TABLE - KW_BASE
    kw[o:o + ROWS] = bytes(ROW_PITCH * r for r in range(ROWS))
    o = NAME_TABLE - KW_BASE
    kw[o:o + 5] = default_name() + bytes(5 - len(DEFAULT_NAME))
    return labels


# ---- MENU/KWAMENU: keyboard picture (0x74 TIM, 240x120 4bpp) -------------------------------------
KEYBOARD, KEYBOARD_SLOT = 0x47E78, 0xBF0
INNER = (12, 8, 229, 107)  # x0, y0, x1, y1 of the frame's inside (picture pixels)
KEYBOARD_BG = 2


def _image(tim):
    p = 8 + struct.unpack_from("<I", tim, 8)[0]  # skip the CLUT block
    _, _, _, w, h = struct.unpack_from("<IHHHH", tim, p)
    return p + 12, w * 4, h


def keyboard_pixels(tim):
    at, w, h = _image(tim)
    return w, h, [[tim[at + (y * w + x) // 2] >> 4 * (x & 1) & 15 for x in range(w)] for y in range(h)]


def blank_keyboard(menu):
    import lz74
    tim, used = lz74.decode_stream(bytes(menu), KEYBOARD)
    if used != KEYBOARD_SLOT:
        raise ValueError("keyboard picture is not the supported one")
    tim = bytearray(tim)
    at, w, _ = _image(tim)
    for y in range(INNER[1], INNER[3]):
        for x in range(INNER[0], INNER[2]):
            i = at + (y * w + x) // 2
            s = 4 * (x & 1)
            tim[i] = tim[i] & ~(15 << s) & 0xFF | KEYBOARD_BG << s
    packed = lz74.encode_stream(bytes(tim))
    if len(packed) > KEYBOARD_SLOT:
        raise ValueError(f"keyboard picture needs {len(packed)} bytes, slot is {KEYBOARD_SLOT}")
    menu[KEYBOARD:KEYBOARD + KEYBOARD_SLOT] = packed + bytes(KEYBOARD_SLOT - len(packed))
    return len(packed)


def encode_pages(cells, encode):
    return [encode(t, cells) for t in page_texts()]


def reserved(file, offset):
    """String slots the name screen code takes over; the build does not write translations there."""
    return file == "KWAMENU.BIN" and CAVE_START <= offset < CAVE_END


def install(files, originals, cells, encode):
    """Apply every name entry change to the build's files; returns a short report."""
    table = patch_exe(files["SLPS_006.62"], cells)
    labels = patch_kwamenu(files["KWAMENU.BIN"], bytes(originals["KWAMENU.BIN"][CAVE_START:CAVE_END]),
                           encode_pages(cells, encode))
    kbd = blank_keyboard(files["MENU/KWAMENU.BIN"])
    return {"glyph_table_bytes": table, "keyboard_bytes": kbd, "cave": {k: hex(v) for k, v in labels.items()}}
