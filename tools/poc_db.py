"""Representative PoC: one Korean line on the database screen.

Replaces the first line of the database page クライマーの操作法 → フリークライミング →
基本的な移動 (KWAMENU.BIN 0x1790D-0x17926, 「まず、移動しようと思う手や足を選びます。」)
with Korean of exactly the same byte length, drawing the syllables into
menu-font cells of MENU/KWAMENU.BIN. Lowercase-Latin cells give 1-byte codes,
cells 1250-1254 give 2-byte codes, so both code widths reach the screen.
The renderer advances by a per-glyph width table in the main executable, so
the used cells get Hangul widths there.

usage: poc_db.py --src <track 01 .bin> --cue <original .cue> --galmuri Galmuri11.bdf --out build/poc_db.bin
"""

import argparse
import hashlib
import os
import re
from pathlib import Path

import iso
import kfont
import textcodec as tc

LINE_START, LINE_END = 0x1790D, 0x17927
ORIGINAL_LINE = bytes.fromhex("759221f1e8f14e627c596af16d59f03d7af03e83f2999b756320")
SLOTS = [("먼", 60), ("저", 61), ("손", 62), ("발", 63), ("을", 64), (" ", 65),
         ("고", 1250), ("릅", 1251), ("니", 1252), ("다", 1253), (" ", 1254)]
PERIOD = 31  # 。 keeps its original cell
SOURCE_SHA256 = "86918cf6ae389bd0ef5ab264a0f172d8fcb9d70026a2f25cb7ec3fa9d4b9c6d8"  # survey §1
TEXT_FILE, FONT_FILE, EXE_FILE = "KWAMENU.BIN", "MENU/KWAMENU.BIN", "SLPS_006.62"
# Per-glyph advance table, 1348 bytes, RAM 0x80045680 in the main executable
# (t_addr 0x80010000, 0x800-byte header). Kanji advance 13 = 12px cell + 1px gap.
# The advance lookup (0x80017CCC) decodes 2-byte codes one higher than the
# bitmap lookup (0x80017604), so glyph k >= 239 advances by table[k + 1].
WIDTH_OFFSET = 0x35E80
WIDTH_ENTRIES = 1348
ORIGINAL_WIDTHS = {60: 8, 61: 8, 62: 9, 63: 8, 64: 9, 65: 7, 1251: 13, 1252: 13, 1253: 13, 1254: 13, 1255: 13}
HANGUL_WIDTH, SPACE_WIDTH = 12, 6  # 11px Galmuri box + 1px gap


def korean_line():
    one, two = dict(SLOTS[:6]), dict(SLOTS[6:])
    glyphs = [one[c] for c in "먼저 손발을 "] + [two[c] for c in "고릅니다"] + [PERIOD]
    line = tc.encode([("g", k) for k in glyphs])
    pad = (LINE_END - LINE_START) - len(line)
    if pad < 0 or pad % 2:
        raise ValueError(f"line is {len(line)} bytes; cannot pad to {LINE_END - LINE_START} with 2-byte blanks")
    return line + tc.encode([("g", two[" "])] * (pad // 2))


def patch_text(data):
    if data[LINE_START:LINE_END] != ORIGINAL_LINE:
        raise ValueError(f"{TEXT_FILE}: source bytes at {LINE_START:#x} are not the expected original line")
    return data[:LINE_START] + korean_line() + data[LINE_END:]


def patch_font(data, bdf):
    box = kfont.hangul_box(bdf)
    out = bytearray(data)
    for ch, k in SLOTS:
        glyph = bytes(kfont.GLYPH_BYTES) if ch == " " else kfont.render(bdf[ch], box)
        out[k * kfont.GLYPH_BYTES : (k + 1) * kfont.GLYPH_BYTES] = glyph
    return bytes(out)


def width_index(k):
    i = k if k <= 0xEE else k + 1
    if i >= WIDTH_ENTRIES:
        raise ValueError(f"glyph {k} advances by byte {i}, past the {WIDTH_ENTRIES}-entry width table")
    return i


def patch_widths(exe):
    out = bytearray(exe)
    for ch, k in SLOTS:
        i = width_index(k)
        if out[WIDTH_OFFSET + i] != ORIGINAL_WIDTHS[i]:
            raise ValueError(f"{EXE_FILE}: width byte {i} is {out[WIDTH_OFFSET + i]}, expected {ORIGINAL_WIDTHS[i]}")
        out[WIDTH_OFFSET + i] = SPACE_WIDTH if ch == " " else HANGUL_WIDTH
    return bytes(out)


def check_source(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("source is not the supported original track 1 (docs/survey.md §1)")


def check_paths(src, out):
    if Path(out).resolve() == Path(src).resolve():
        raise ValueError("--out must not be the source image")


def write_cue(src_cue, out_bin):
    """Copy the cue, pointing track 1 at out_bin and the audio tracks back at the originals."""
    src_dir, out_dir = Path(src_cue).resolve().parent, Path(out_bin).resolve().parent
    lines, track1 = [], 0
    for line in Path(src_cue).read_text().splitlines():
        m = re.match(r'FILE "(.+)" BINARY', line)
        if m:
            name = m.group(1)
            if "(Track 01)" in name:
                track1 += 1
                path = Path(out_bin).name
            else:
                path = os.path.relpath(src_dir / name, out_dir)
            line = f'FILE "{path}" BINARY'
        lines.append(line)
    if track1 != 1:
        raise ValueError(f"{src_cue}: expected exactly one (Track 01) FILE line, found {track1}")
    cue = Path(out_bin).with_suffix(".cue")
    cue.write_text("\n".join(lines) + "\n")
    return cue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--cue", required=True)
    ap.add_argument("--galmuri", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    check_paths(a.src, a.out)
    raw = Path(a.src).read_bytes()
    check_source(raw)
    disc = iso.load(raw)
    changes = {
        TEXT_FILE: patch_text(iso.read_file(raw, disc, TEXT_FILE)),
        FONT_FILE: patch_font(iso.read_file(raw, disc, FONT_FILE), kfont.load_bdf(a.galmuri)),
        EXE_FILE: patch_widths(iso.read_file(raw, disc, EXE_FILE)),
    }
    out = iso.apply(raw, iso.plan(raw, disc, changes))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(out)
    print(write_cue(a.cue, a.out))


if __name__ == "__main__":
    main()
