"""Product build: Korean text, glyphs and advances written in place (D3).

Steps, all on the fixed revision (docs/survey.md §1):
1. extract the adopted string population (textmap) and group it into units;
2. select translations by policy — dev: draft and reviewed (non-distribution),
   release: reviewed only, every translated unit must be reviewed;
3. allocate glyph cells: kept glyphs stay in their cells, new punctuation and
   the 1-byte Hangul plan (kocheck.fit_plan) take free 1-byte cells, the other
   Hangul take free 2-byte cells;
4. draw the glyphs into every copy of the font, write their advances into the
   executable's table, and write each translation over every copy of its unit;
5. apply the emulator compatibility fix (tools/compat.py: START.BIN below the end of RAM);
6. rebuild track 1 through iso.plan/apply.
Untranslated units keep their source bytes; under the dev policy their kana and
kanji show whatever now sits in those cells.

usage: build_ko.py --src <track 01 .bin> --cue <.cue> --galmuri Galmuri11.bdf --ko text/ko \\
                   --out build/mitouhou_ko.bin [--policy dev|release]
"""

import argparse
import hashlib
import json
from pathlib import Path

import charmap
import compat
import iso
import kfont
import kocheck
import poc_db
import textcodec as tc
import textmap
import units

TABLE = Path(__file__).resolve().parent.parent / "tables" / "charmap.tsv"
FONT_BYTES = kfont.GLYPHS * kfont.GLYPH_BYTES
FONT_FILE = "MENU/KWAMENU.BIN"
FONT_COPIES = 99  # MENU/KWAMENU, X/X0, X/X2, X_HUMAN/X_STAFF, SU_IG_0-81, SU_MG_0-12
WIDTH_OFFSET = kocheck.WIDTH_OFFSET
HANGUL_W, SPACE_W = kocheck.HANGUL_W, kocheck.SPACE_W
# 1-byte cells: 60-238. F5-F7 are not used: F6 (cell 245, ・) drew blank on the peak info window.
ONE_BYTE_CELLS = list(range(kocheck.FIXED_ONE_BYTE, 0xEF))
IN_PLACE = {"ｃ": 62, "ｍ": 72, "ｘ": 83}  # kept 1-byte glyphs that stay where they are
NEW_PUNCT_CELLS = sorted(kocheck.NEW_PUNCT) + ["？", "・"]  # ？ (242) and ・ (245) move to 1-byte cells
COPIED = {"・": 245}  # moved glyphs that keep their original bitmap and advance
# 2-byte cells: 239-1346; 1347 would read its advance past the table
TWO_BYTE_CELLS = list(range(0xEF, kfont.GLYPHS - 1))


def _cell_of():
    out = {}
    for k, (c, _) in sorted(charmap.load(TABLE).items()):
        out.setdefault(c, k)
    return out


CELL = _cell_of()


def width_index(k):
    return k if k <= 0xEE else k + 1


def allocate(hangul, one_byte, kept):
    cells = {}
    for ch in kept:
        if ch not in NEW_PUNCT_CELLS:
            cells[ch] = IN_PLACE.get(ch, CELL[ch])
    taken = set(cells.values()) | set(IN_PLACE.values())
    free1 = [k for k in ONE_BYTE_CELLS if k not in taken]
    first = NEW_PUNCT_CELLS + sorted(one_byte & hangul)
    if len(first) > len(free1):
        raise ValueError(f"{len(first)} 1-byte glyphs for {len(free1)} free 1-byte cells")
    cells.update(zip(first, free1))
    taken = set(cells.values())
    free2 = [k for k in TWO_BYTE_CELLS if k not in taken]
    rest = sorted(hangul - one_byte)
    if len(rest) > len(free2):
        raise ValueError(f"{len(rest)} 2-byte glyphs for {len(free2)} free 2-byte cells")
    cells.update(zip(rest, free2))
    idx = {}
    for ch, k in cells.items():
        other = idx.setdefault(width_index(k), ch)
        if other != ch:
            raise ValueError(f"{ch!r} and {other!r} share advance entry {width_index(k)}")
    return cells


def code(k):
    return tc.code(k)


def normalize(text):
    out = []
    for t in kocheck.tokenize(text):
        if t[0] == "c":
            out.append(kocheck.ALIASES.get(t[1], t[1]))
        elif t == ("nl",):
            out.append("\n")
        elif t == ("sp",):
            out.append("\u3000")
        else:
            out.append("{%02X:%s}" % (t[1], ",".join(f"{b:02X}" for b in t[2])))
    return "".join(out)


def encode(text, cells):
    out = bytearray()
    for t in kocheck.tokenize(text):
        if t[0] == "c":
            ch = kocheck.ALIASES.get(t[1], t[1])
            k = cells.get(ch)
            if k is None and CELL.get(ch, 9999) < kocheck.FIXED_ONE_BYTE:
                k = CELL[ch]
            if k is None:
                raise ValueError(f"no glyph cell for {ch!r}")
            out += code(k)
        else:
            out += tc.encode([t])
    return bytes(out) + b"\xff"


def decode_with(toks, cells):
    inv = {k: ch for ch, k in cells.items()}
    out = []
    for t in toks:
        if t[0] == "g":
            out.append(inv.get(t[1]) or charmap.load(TABLE)[t[1]][0])
        elif t == ("nl",):
            out.append("\n")
        elif t == ("sp",):
            out.append("　")
        elif t[0] == "ctl":
            out.append("{%02X:%s}" % (t[1], ",".join(f"{b:02X}" for b in t[2])))
    return "".join(out)


def write_string(data, offset, slot_end, raw):
    if offset + len(raw) > slot_end:
        raise ValueError(f"{len(raw)} bytes at {offset:#x} overrun the slot ending at {slot_end:#x}")
    data[offset:slot_end] = raw + bytes(slot_end - offset - len(raw))


def _bdf_char(ch, bdf):
    for c in (ch, {"？": "?", "“": "“", "”": "”"}.get(ch, ch)):
        if c in bdf:
            return bdf[c]
    raise ValueError(f"Galmuri has no glyph for {ch!r}")


def glyph(ch, bdf):
    if ch == " ":
        return bytes(kfont.GLYPH_BYTES)
    return kfont.render(_bdf_char(ch, bdf), kfont.hangul_box(bdf))


def advance(ch, bdf):
    if "가" <= ch <= "힣":
        return HANGUL_W
    if ch == " ":
        return SPACE_W
    w, _, xo, _ = _bdf_char(ch, bdf)["bbx"]
    return max(4, xo + w + 1)


def _units(entries, cm):
    us = {}
    for e in entries:
        u = us.setdefault(units.key(e["source"]), {
            "source": e["source"], "capacity": e["slot_end"] - e["offset"], "copies": [],
            "text": charmap.text(tc.decode(bytes.fromhex(e["source"])), cm)})
        u["capacity"] = min(u["capacity"], e["slot_end"] - e["offset"])
        u["copies"].append(e)
    return us


def _select(ko, policy):
    picked = {k: v for k, v in ko.items() if v.get("ko")}
    if policy == "release":
        bad = [k for k, v in picked.items() if v.get("status") != "reviewed"]
        if bad:
            raise ValueError(f"release build refuses {len(bad)} unreviewed translations, e.g. {bad[:3]}")
    elif policy != "dev":
        raise ValueError(f"unknown policy {policy}")
    return picked


def build(src, ko, bdf, policy="dev", compat_fix=True):
    if hashlib.sha256(src).hexdigest() != poc_db.SOURCE_SHA256:
        raise ValueError("source is not the supported original track 1")
    picked = _select(ko, policy)
    report = {"distribution": policy == "release", "strings_written": 0, "written": [], "cells": {},
              "files_out": {}}
    if not picked:
        return src, report
    disc = iso.load(src)
    names = sorted(n for n in disc.files if not n.startswith(("CDDA/", "MOVIE")))
    originals = {n: iso.read_file(src, disc, n) for n in names}
    files = {n: bytearray(d) for n, d in originals.items()}
    cm = charmap.load(TABLE)
    entries = textmap.extract({n: bytes(files[n]) for n in textmap.MODULES}, bytes(files["SLPS_006.62"]))
    us = _units(entries, cm)
    unknown = sorted(set(picked) - set(us))
    if unknown:
        raise ValueError(f"translations for units not in the source: {unknown[:5]}")

    plan = kocheck.fit_plan(us, picked, slots=len(ONE_BYTE_CELLS) - len(IN_PLACE) - len(NEW_PUNCT_CELLS))
    texts = [v["ko"] for v in picked.values()]
    hangul = {ch for t in texts for ch in t if "가" <= ch <= "힣"}
    kept = {kocheck.ALIASES.get(t[1], t[1]) for x in texts for t in kocheck.tokenize(x)
            if t[0] == "c" and not ("가" <= t[1] <= "힣")} - set(kocheck.NEW_PUNCT)
    for ch in kept:
        if ch not in NEW_PUNCT_CELLS and ch not in CELL:
            raise ValueError(f"no glyph for {ch!r}")
    cells = allocate(hangul, plan, kept)

    for k, v in picked.items():
        raw = encode(v["ko"], cells)
        for e in us[k]["copies"]:
            write_string(files[e["file"]], e["offset"], e["slot_end"], raw)
            report["written"].append({"file": e["file"], "offset": e["offset"], "ko": v["ko"]})
    report["strings_written"] = len(report["written"])

    drawn = {ch: k for ch, k in cells.items() if "가" <= ch <= "힣" or ch in NEW_PUNCT_CELLS}
    original_font = bytes(files[FONT_FILE][:FONT_BYTES])
    fonts = 0
    for n, data in files.items():
        at = bytes(data).find(original_font)
        if at < 0:
            continue
        for ch, k in drawn.items():
            if ch in COPIED:
                bitmap = original_font[COPIED[ch] * kfont.GLYPH_BYTES : (COPIED[ch] + 1) * kfont.GLYPH_BYTES]
            else:
                bitmap = glyph(ch, bdf)
            data[at + k * kfont.GLYPH_BYTES : at + (k + 1) * kfont.GLYPH_BYTES] = bitmap
        fonts += 1
    if fonts != FONT_COPIES:
        raise ValueError(f"found {fonts} font copies, expected {FONT_COPIES} (docs/survey.md §3.1)")
    exe = files["SLPS_006.62"]
    original_exe = originals["SLPS_006.62"]
    for ch, k in drawn.items():
        if ch in COPIED:
            exe[WIDTH_OFFSET + width_index(k)] = original_exe[WIDTH_OFFSET + width_index(COPIED[ch])]
        else:
            exe[WIDTH_OFFSET + width_index(k)] = advance(ch, bdf)

    if compat_fix:
        report["compat"] = compat.apply(files)
    changes = {n: bytes(d) for n, d in files.items() if bytes(d) != originals[n]}
    out = iso.apply(src, iso.plan(src, disc, changes))
    report.update(cells=cells, files_out={n: bytes(d) for n, d in files.items()}, fonts=fonts,
                  one_byte_hangul=len(plan & hangul), hangul=len(hangul), changed_files=sorted(changes))
    return out, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--cue", required=True)
    ap.add_argument("--galmuri", required=True)
    ap.add_argument("--ko", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--policy", default="dev")
    ap.add_argument("--no-compat", action="store_true", help="leave out the START.BIN emulator fix (tools/compat.py)")
    a = ap.parse_args()
    poc_db.check_paths(a.src, a.out)
    ko = {}
    for p in sorted(Path(a.ko).glob("*.json")):
        ko.update(json.loads(p.read_text(encoding="utf-8")))
    out, rep = build(Path(a.src).read_bytes(), ko, kfont.load_bdf(a.galmuri), a.policy,
                     compat_fix=not a.no_compat)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(out)
    cue = poc_db.write_cue(a.cue, a.out)
    manifest = {
        "policy": a.policy, "distribution": rep["distribution"],
        "note": "" if rep["distribution"] else "NON-DISTRIBUTION development build: contains unreviewed drafts",
        "sha256": hashlib.sha256(out).hexdigest(), "strings_written": rep["strings_written"],
        "hangul": rep.get("hangul"), "one_byte_hangul": rep.get("one_byte_hangul"),
        "changed_files": rep.get("changed_files"),
    }
    Path(a.out).with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    print(cue, manifest["sha256"], manifest["note"])


if __name__ == "__main__":
    main()
