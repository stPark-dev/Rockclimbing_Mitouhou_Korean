import struct
import sys
from pathlib import Path

import capstone
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import nameentry as ne  # noqa: E402

MD = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS32 + capstone.CS_MODE_LITTLE_ENDIAN)


def dis(word, addr=0x80000000):
    i = next(MD.disasm(struct.pack("<I", word), addr))
    return f"{i.mnemonic} {i.op_str}".strip()


def test_assembler_matches_capstone():
    assert dis(ne.sll("v0", "s1", 3)) == "sll $v0, $s1, 3"
    assert dis(ne.addu("v0", "v0", "s1")) == "addu $v0, $v0, $s1"
    assert dis(ne.lhu("a1", 0, "v0")) == "lhu $a1, ($v0)"
    assert dis(ne.addiu("a1", "a1", -6)) == "addiu $a1, $a1, -6"
    assert dis(ne.ori("s2", "zero", 0x11)) == "ori $s2, $zero, 0x11"
    assert dis(ne.lui("t0", 0x8013)) == "lui $t0, 0x8013"
    assert dis(ne.sw("v0", 0x10, "sp")) == "sw $v0, 0x10($sp)"
    assert dis(ne.jal(0x800C1234), 0x800BA90C) == "jal 0x800c1234"
    assert dis(ne.jr("ra")) == "jr $ra"
    assert dis(ne.beq("t0", "zero", 3), 0x80000000) == "beqz $t0, 0x80000010"
    assert dis(ne.andi("t0", "t0", 0xC)) == "andi $t0, $t0, 0xc"
    assert dis(ne.xori("t1", "t1", 1)) == "xori $t1, $t1, 1"
    assert dis(ne.NOP) == "nop"


def test_layout_has_every_syllable_once_and_a_space_key():
    cells = ne.layout()
    assert len(cells) == 252 <= ne.PAGES * ne.ROWS * ne.COLS
    assert (ne.PAGES, ne.ROWS, ne.COLS) == (3, 6, 18)
    syl = [c for c in cells if c != ne.SPACE]
    assert len(syl) == len(set(syl)) == len(ne.syllables()) == 251
    assert cells[-1] == ne.SPACE


def test_index_of_matches_the_patched_formula():
    assert ne.index_of(0, 0, 0) == 1
    assert ne.index_of(0, 5, 17) == 108
    assert ne.index_of(1, 0, 0) == 109
    assert ne.index_of(1, 1, 13) == 140
    assert ne.index_of(1, 1, 14) == 142  # 141 is the choice cursor
    assert ne.index_of(2, 1, 17) == 253 < 255  # 0xFF ends a name


def test_no_cell_takes_the_choice_cursor_number():
    # the climbing and camp choices put number 141 in an {F8} slot to draw ▶ (original table entry 141)
    numbers = [ne.number(k) for k in range(1, len(ne.layout()) + 1)]
    assert ne.CURSOR == 141 and ne.CURSOR not in numbers
    assert len(set(numbers)) == len(numbers) and max(numbers) < 0xFF


def fake_cells():
    # 1-byte cells for every other syllable, 2-byte cells for the rest
    out = {}
    for i, ch in enumerate(ne.syllables()):
        out[ch] = 60 + i if i % 2 else 0x200 + i
    return out


def read_glyph(table, base, idx):
    """What the patched draw functions read: halfword offset from base, then a 1- or 2-byte code."""
    off = struct.unpack_from("<H", table, idx * 2)[0]
    p = off  # table is laid out from base
    b = table[p]
    if b == 0xFD:
        return None
    if 0xF0 <= b < 0xF5:
        return 0xEF + ((b - 0xF0) << 8 | table[p + 1])
    return b - 1


def test_glyph_table_round_trips_every_index_and_fits():
    cells = fake_cells()
    table = ne.glyph_table(cells)
    assert len(table) <= ne.TABLE_END - ne.TABLE_START
    lay = ne.layout()
    assert read_glyph(table, ne.TABLE_START, 0) is None  # empty slot draws blank
    assert read_glyph(table, ne.TABLE_START, 0xFF) is None  # every byte value has an entry
    assert read_glyph(table, ne.TABLE_START, ne.CURSOR) == ne.CURSOR_GLYPH == 29  # ▶ of the original font
    for i, ch in enumerate(lay, 1):
        want = None if ch == ne.SPACE else cells[ch]
        assert read_glyph(table, ne.TABLE_START, ne.number(i)) == want
    for b, ch in zip(ne.default_name(), ne.DEFAULT_NAME):  # 클라이머 reads back through the shifted numbers
        assert read_glyph(table, ne.TABLE_START, b) == cells[ch]


def test_glyph_table_refuses_overflow():
    big = {ch: 0x300 for ch in ne.syllables()}
    with pytest.raises(ValueError):
        ne.glyph_table(big, limit=500)


def test_page_strings_are_six_lines_of_eighteen():
    pages = ne.page_texts()
    assert len(pages) == 3
    for p, text in enumerate(pages):
        lines = text.split("\n")
        assert len(lines) <= ne.ROWS and all(len(l) <= ne.COLS for l in lines)
    assert "".join(pages).replace("\n", "") == "".join(c for c in ne.layout() if c != ne.SPACE)


ROOT = Path(__file__).resolve().parent.parent
FILES = ROOT / "work" / "files"
needs_files = pytest.mark.skipif(not (FILES / "KWAMENU.BIN").exists(), reason="extracted disc files are not in the repository")


@needs_files
def test_patched_exe_reads_every_number_through_the_new_table():
    exe = bytearray((FILES / "SLPS_006.62").read_bytes())
    cells = fake_cells()
    ne.patch_exe(exe, cells)
    o = ne.TABLE_START - ne.EXE_LOAD
    region = bytes(exe[o:ne.TABLE_END - ne.EXE_LOAD])
    for i, ch in enumerate(ne.layout(), 1):
        assert read_glyph(region, ne.TABLE_START, ne.number(i)) == (None if ch == ne.SPACE else cells[ch])
    assert read_glyph(region, ne.TABLE_START, ne.CURSOR) == ne.CURSOR_GLYPH
    words = {a: struct.unpack_from("<I", exe, a - ne.EXE_LOAD)[0] for a in ne.EXE_PATCH}
    assert dis(words[0x80021140]) == "lhu $a1, ($v0)"
    assert dis(words[0x80021148]) == "addu $a1, $a1, $s4"
    with pytest.raises(ValueError):
        ne.patch_exe(exe, cells)  # second run: the originals are gone


@needs_files
def test_patched_name_screen_jumps_into_the_cave_and_branches_stay_inside():
    kw = bytearray((FILES / "KWAMENU.BIN").read_bytes())
    original = bytes(kw[ne.CAVE_START:ne.CAVE_END])
    strings = [b"\x01\xfe\x02\xff", b"\x03\xff", b"\x04\xff"]
    labels = ne.patch_kwamenu(kw, original, strings)
    lo, hi = ne.KW_BASE + ne.CAVE_START, ne.KW_BASE + ne.CAVE_END
    assert dis(struct.unpack_from("<I", kw, 0x800BAADC - ne.KW_BASE)[0], 0x800BAADC) == f"jal {labels['exit']:#x}"
    exit_code = bytes(kw[labels["exit"] - ne.KW_BASE:][:64])
    calls = [i.op_str for i in MD.disasm(exit_code, labels["exit"]) if i.mnemonic == "jal"]
    assert calls[:2] == [f"{ne.WIN_CLOSE:#x}", "0x80018d30"]  # close the keyboard, then the confirm sound
    # after 終了 the loop must not reopen the window: exit sets the closed flag (+36) that loop checks
    loop_code = bytes(kw[labels["loop"] - ne.KW_BASE:labels["number"] - ne.KW_BASE])
    flag = ne.hi_lo(labels["vars"])[1] + 36
    assert any(i.mnemonic == "lw" and i.op_str.endswith(f"{flag:#x}($t1)") for i in MD.disasm(loop_code, labels["loop"]))
    for name in ("init", "loop", "number", "show", "exit"):
        assert lo <= labels[name] < hi
    assert dis(struct.unpack_from("<I", kw, 0x800BA90C - ne.KW_BASE)[0], 0x800BA90C) == f"jal {labels['loop']:#x}"
    body = bytes(kw[ne.CAVE_START:ne.CAVE_END])
    code_from = labels["show"] - lo
    for ins in MD.disasm(body[code_from:labels["number"] - lo + 28], labels["show"]):
        if ins.mnemonic in ("beqz", "bnez", "beq", "bne"):
            target = int(ins.op_str.split(", ")[-1], 16)
            assert labels["show"] <= target < hi
    assert struct.unpack_from("<III", kw, labels["strptr"] - ne.KW_BASE) == (labels["page0"], labels["page1"], labels["page2"])
    assert bytes(kw[labels["page0"] - ne.KW_BASE:][:4]) == strings[0]
    assert bytes(kw[ne.NAME_TABLE - ne.KW_BASE:][:5]) == ne.default_name() + b"\x00"
    assert list(kw[ne.COL_TABLE - ne.KW_BASE:][:18]) == [12 * c for c in range(18)]
    assert list(kw[ne.ROW_TABLE - ne.KW_BASE:][:6]) == [14 * r for r in range(6)]
    assert dis(struct.unpack_from("<I", kw, 0x800BA970 - ne.KW_BASE)[0]) == "slti $v0, $s1, 6"
    assert dis(struct.unpack_from("<I", kw, 0x800BA980 - ne.KW_BASE)[0]) == "slti $v0, $s1, 6"  # second row check
    assert dis(struct.unpack_from("<I", kw, 0x800BA990 - ne.KW_BASE)[0]) == "ori $s1, $zero, 5"
    assert struct.unpack_from("<3I", kw, labels["offsets"] - ne.KW_BASE) == (0, 108, 216)


def run_number(code, base, labels, v0, page_offset):
    """Interpret the cave's number routine (the few instructions it uses, with delay slots)."""
    reg = {n: 0 for n in ne.REG}
    reg["v0"] = v0
    mem = {labels["vars"] + 8: page_offset}
    pc, target = labels["number"], None
    for _ in range(64):
        i = next(MD.disasm(code[pc - base:pc - base + 4], pc))
        ops = [o.strip().lstrip("$") for o in i.op_str.split(",")]
        imm = lambda o: int(o, 0)
        jump, m = target, i.mnemonic
        target = None
        if m == "lui":
            reg[ops[0]] = imm(ops[1]) << 16
        elif m == "lw":
            off, r = ops[1].rstrip(")").split("($")
            reg[ops[0]] = mem.get((reg[r] + imm(off or "0")) & 0xFFFFFFFF, 0)
        elif m in ("addiu", "ori", "xori", "slti"):
            a, b = reg[ops[1]], imm(ops[2])
            reg[ops[0]] = {"addiu": a + b, "ori": a | b, "xori": a ^ b, "slti": int(a < b)}[m]
        elif m == "addu":
            reg[ops[0]] = reg[ops[1]] + reg[ops[2]]
        elif m in ("bnez", "beqz"):
            target = imm(ops[1]) if (reg[ops[0]] != 0) == (m == "bnez") else pc + 8
        elif m == "jr":
            target = -1
        elif m != "nop":
            raise AssertionError(f"unexpected {m} {i.op_str}")
        reg["zero"] = 0
        if jump == -1:
            return reg["v0"]  # the delay slot of jr ra has run
        pc = jump if jump is not None else pc + 4
    raise AssertionError("number routine did not return")


@needs_files
def test_number_routine_skips_the_choice_cursor_and_maps_blank_cells_to_space():
    kw = bytearray((FILES / "KWAMENU.BIN").read_bytes())
    labels = ne.patch_kwamenu(kw, bytes(kw[ne.CAVE_START:ne.CAVE_END]), [b"\xff"] * 3)
    base = ne.KW_BASE
    space = ne.number(ne.layout().index(ne.SPACE) + 1)
    for page in range(ne.PAGES):
        for row in range(ne.ROWS):
            for col in range(ne.COLS):
                got = run_number(bytes(kw), base, labels, row * ne.COLS + col, page * ne.ROWS * ne.COLS)
                k = page * ne.ROWS * ne.COLS + row * ne.COLS + col + 1
                assert got == (ne.number(k) if k <= len(ne.layout()) else space), (page, row, col)
    assert ne.CURSOR not in ne.default_name()


@needs_files
def test_keyboard_picture_keeps_the_frame_and_clears_the_kana():
    import lz74
    menu = bytearray((FILES / "MENU" / "KWAMENU.BIN").read_bytes())
    before, _ = lz74.decode_stream(bytes(menu), ne.KEYBOARD)
    ne.blank_keyboard(menu)
    after, used = lz74.decode_stream(bytes(menu), ne.KEYBOARD)
    assert used <= ne.KEYBOARD_SLOT
    assert len(after) == len(before) and after[:0x40] == before[:0x40]  # TIM header and palette
    w, h, px = ne.keyboard_pixels(after)
    inner = {px[y][x] for y in range(ne.INNER[1], ne.INNER[3]) for x in range(ne.INNER[0], ne.INNER[2])}
    assert inner == {ne.KEYBOARD_BG}
    wb, hb, pb = ne.keyboard_pixels(before)
    assert all(px[y][x] == pb[y][x] for y in (0, 2, h - 1) for x in range(w))  # frame rows unchanged
