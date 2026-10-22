"""Mechanical checks for translations in text/ko (translation-workflow §5.1).

- tokens: F8/F9/FA/FB controls (name slots, string jumps, numbers, draw
  attributes) keep their count, order and arguments. FC, line breaks and the
  FD full-width space are layout and may move.
- glyph: every character is Hangul, a glyph the Korean font keeps (digits,
  Latin, symbols), or new punctuation adopted in D4. Kana and kanji cells are
  reused for Hangul, and 。、 are replaced by . , (D4).
- capacity: the in-place size (D3), counting the most frequent syllables as
  1-byte codes. The 1-byte plan is an estimate until the build assigns codes.
- window: lines wider than a window limit measured on screen (WINDOW_LIMITS).
  Strings in windows not yet measured get a warning when a line is wider than
  the widest source line.

usage: kocheck.py <text/src dir> <text/ko dir> [-w]   (-w lists line-width warnings)
"""

import collections
import json
import re
import sys
from pathlib import Path

import charmap
import textcodec as tc
import units

TABLE = Path(__file__).resolve().parent.parent / "tables" / "charmap.tsv"
LAYOUT = {0xFC}
NEW_PUNCT = set(" .,“”")
ALIASES = {"(": "（", ")": "）", "!": "！", "?": "？", ":": "："}
# 1-byte codes reach glyph cells 0-238 (F5-F7 are not used: F6 for cell 245 drew blank on the
# peak info window, 2026-10-21). Cells 0-59 stay fixed: FA prints digits from cells 0-9, and the
# symbols and Latin capitals keep their codes. The build places NEW_PUNCT, ｃｍｘ, ・ and ？ in
# 1-byte cells as well; every other non-Hangul glyph keeps a 2-byte cell.
FIXED_ONE_BYTE = 60
ONE_BYTE_OTHER = set("ｃｍｘ・？")
ONE_BYTE_SLOTS = 239 - FIXED_ONE_BYTE - len(NEW_PUNCT) - len(ONE_BYTE_OTHER)
_CTL = re.compile(r"\{([0-9A-F]{2}):([0-9A-F]{2}(?:,[0-9A-F]{2})*)?\}")


def _kept():
    out = set()
    for k, (c, _) in charmap.load(TABLE).items():
        if c in "・ー":  # symbols that sit in the kana block
            out.add(c)
            continue
        if c in "。、" or "぀" <= c <= "ヿ" or "一" <= c <= "鿿" or c == "々":
            continue
        out.add(c)
    return out


KEPT = _kept()
_CELL = {}
for _k, (_c, _) in sorted(charmap.load(TABLE).items()):
    _CELL.setdefault(_c, _k)


def tokenize(text):
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == "{":
            m = _CTL.match(text, i)
            if not m:
                raise ValueError(f"malformed control at {i}: {text[i:i + 12]!r}")
            args = bytes(int(x, 16) for x in m.group(2).split(",")) if m.group(2) else b""
            out.append(("ctl", int(m.group(1), 16), args))
            i = m.end()
            continue
        out.append(("nl",) if ch == "\n" else ("sp",) if ch == "　" else ("c", ch))
        i += 1
    return out


def protected(toks):
    return [(t[1], t[2]) for t in toks if t[0] == "ctl" and t[1] not in LAYOUT]


def encodable(ch):
    return "가" <= ch <= "힣" or ch in NEW_PUNCT or ALIASES.get(ch, ch) in KEPT


def _one_byte_char(ch):
    ch = ALIASES.get(ch, ch)
    return ch in NEW_PUNCT or ch in ONE_BYTE_OTHER or _CELL.get(ch, 9999) < FIXED_ONE_BYTE


def byte_length(toks, one_byte):
    n = 1  # FF
    for t in toks:
        if t[0] == "ctl":
            n += 1 + len(t[2])
        elif t[0] == "c" and "가" <= t[1] <= "힣":
            n += 1 if t[1] in one_byte else 2
        elif t[0] == "c":
            n += 1 if _one_byte_char(t[1]) else 2
        else:
            n += 1
    return n


def one_byte_plan(texts, slots=ONE_BYTE_SLOTS):
    freq = collections.Counter(ch for t in texts for ch in t if "가" <= ch <= "힣")
    return {ch for ch, _ in freq.most_common(slots)}


def fit_plan(units_, ko, slots=ONE_BYTE_SLOTS, rounds=1000):
    """Frequency plan, then swap syllables of overflowing strings into 1-byte codes,
    each time evicting the least frequent 1-byte syllable whose eviction overflows nothing."""
    entries, texts = [], []
    for k, v in ko.items():
        if v.get("ko"):
            for _, text, cap in variants(units_[k], v):
                toks = tokenize(text)
                cnt = collections.Counter(t[1] for t in toks if t[0] == "c" and "가" <= t[1] <= "힣")
                entries.append((toks, cap, cnt))
                texts.append(text)
    freq = collections.Counter()
    for _, _, cnt in entries:
        freq.update(cnt)
    plan = one_byte_plan(texts, slots)
    for _ in range(rounds):
        slack = [cap - byte_length(toks, plan) for toks, cap, _ in entries]
        gain = collections.Counter()
        for (_, _, cnt), s in zip(entries, slack):
            if s < 0:
                gain.update({ch: c for ch, c in cnt.items() if ch not in plan})
        if not gain:
            break
        best = max(gain, key=lambda ch: (gain[ch], freq[ch], ch))
        out = None
        for ch in sorted(plan, key=lambda ch: (freq[ch], ch)):
            if all(s >= cnt[ch] for (_, _, cnt), s in zip(entries, slack) if ch in cnt and s >= 0) and not any(
                    ch in cnt for (_, _, cnt), s in zip(entries, slack) if s < 0):
                out = ch
                break
        if out is None:
            break
        plan = (plan - {out}) | {best}
    if any(cap < byte_length(toks, plan) for toks, cap, _ in entries):
        plan = cover_plan(entries, freq, slots) or plan
    return plan


def cover_plan(entries, freq, slots):
    """Smallest syllable set that fits every string (integer program), then the most frequent
    syllables in the remaining slots. Ties go to frequent syllables. None if scipy is missing
    or no such set fits in `slots`."""
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
    except ImportError:
        return None
    rows = [(cnt, byte_length(toks, set()) - cap) for toks, cap, cnt in entries]
    rows = [(cnt, need) for cnt, need in rows if need > 0]
    syl = sorted({ch for cnt, _ in rows for ch in cnt}, key=lambda ch: (-freq[ch], ch))
    if not syl:
        return None
    col = {ch: i for i, ch in enumerate(syl)}
    a = np.zeros((len(rows), len(syl)))
    for r, (cnt, _) in enumerate(rows):
        for ch, n in cnt.items():
            a[r, col[ch]] = n
    cost = 1 + np.arange(len(syl)) / (len(syl) * 10.0)
    res = milp(c=cost, constraints=[LinearConstraint(a, [need for _, need in rows], np.inf)],
               integrality=np.ones(len(syl)), bounds=Bounds(0, 1))
    if res.x is None:
        return None
    plan = {ch for ch, x in zip(syl, res.x) if x > 0.5}
    if len(plan) > slots:
        return None
    for ch, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
        if len(plan) >= slots:
            break
        plan.add(ch)
    return plan


WIDTH_OFFSET = 0x35E80  # advance table in SLPS_006.62 (docs/survey.md §3.3)
HANGUL_W, SPACE_W, PUNCT_W, CELL_W = 12, 6, 6, 13  # PoC advances; FD and FC step by 13


def _advance(k, widths):
    # the renderer reads 2-byte glyph k's advance from entry k + 1 (docs/survey.md §3.3)
    return widths.get(k if k <= 0xEE else k + 1, CELL_W)


def source_line_widths(toks, widths):
    lines = [0]
    for t in toks:
        if t == ("nl",):
            lines.append(0)
        elif t == ("sp",):
            lines[-1] += CELL_W
        elif t[0] == "g":
            lines[-1] += _advance(t[1], widths)
        elif t[0] == "ctl" and t[1] == 0xFC:
            lines[-1] += CELL_W * t[2][0]
    return lines


def ko_line_widths(toks, widths=None, name_w=0):
    lines = [0]
    for t in toks:
        if t == ("nl",):
            lines.append(0)
        elif t == ("sp",):
            lines[-1] += CELL_W
        elif t[0] == "ctl" and t[1] == 0xFC:
            lines[-1] += CELL_W * t[2][0]
        elif t[0] == "ctl" and t[1] == 0xF8 and t[2][0] == 0:
            lines[-1] += name_w
        elif t[0] == "c":
            ch = ALIASES.get(t[1], t[1])
            if "가" <= ch <= "힣":
                lines[-1] += HANGUL_W
            elif ch == " ":
                lines[-1] += SPACE_W
            elif ch in NEW_PUNCT:
                lines[-1] += PUNCT_W
            else:
                lines[-1] += _advance(_CELL[ch], widths or {})
    return lines


# Line widths measured on screen with the dev build: (module, first offset, end offset, px, evidence).
# The renderer does not clip at the window border, so a wider line draws over it.
WINDOW_LIMITS = [
    ("KWAMENU.BIN", 0x14060, 0x14460, 249,
     "database equipment descriptions: text x=47, inner right edge x~296 (docs/survey.md §9)"),
    ("KWAMENU.BIN", 0x128D0, 0x12C4C, 265,
     "peak introductions (climbing plan): text x=32, inner right edge x~297 (docs/survey.md §9)"),
    ("KWAMENU.BIN", 0x14460, 0x15EA8, 259,
     "stage descriptions (route plan, lower window): text x=36, inner right edge x~296 (docs/survey.md §9)"),
    ("KWAMENU.BIN", 0x15ED4, 0x1790C, 236,
     "database mountaineering terms: text x=44, inner right edge x~281 (docs/survey.md §9)"),
    ("KWAMENU.BIN", 0x1790C, 0x186A4, 268,
     "climber controls (database, under the picture): text x=28, inner right edge x~297 (docs/survey.md §9)"),
    ("KWAMENU.BIN", 0x138D8, 0x13EB8, 108,
     "training item summaries (right panel): text x=204, inner right edge x~313 (docs/survey.md §9)"),
    ("KWAMENU.BIN", 0x186BC, 0x196A4, 236,
     "training descriptions: same frame as the database terms window (docs/survey.md §9)"),
]


# Windows that draw every character, the half-width space included, in a 13px cell; FC:n is
# n cells and FD one. (module ranges, px from the text start to the inner right edge)
_SUZU = ["SUZU0.BIN", "SUZU1.BIN", "SUZU2.BIN", "SUZU3.BIN", "SUZU4.BIN"]
FIXED_WINDOWS = (
    [(m, 0x210, 0x7260, 238, "stage conditions: text x=44, inner right edge x~282 (docs/survey.md §9)") for m in _SUZU]
    + [(m, 0x8CEC, 0xBA54, 224, "stage overview: text x=57, inner right edge x~281 (docs/survey.md §9)") for m in _SUZU]
    + [("SUZU_0.BIN", lo, hi, px, why) for lo, hi, px, why in (
        (0x5A90, 0xCAE0, 238, "stage conditions"), (0x11694, 0x186E4, 238, "stage conditions"),
        (0xE56C, 0x112D4, 224, "stage overview"), (0x1A170, 0x1CED8, 224, "stage overview"))]
    + [(m, 0xBAB4, 0x10000, 236, "pitch overview and advice: text x=44, inner right edge x~280 (docs/survey.md §9)")
       for m in _SUZU]
)
WINDOW_LIMITS += [
    ("X_SUZU.BIN", 0x11C8, 0x12A8, 89,
     "mountain screen top-right peak and route labels: text x=213, inner right edge x~302 (docs/survey.md §9, 2026-10-22)"),
    ("X_SUZU.BIN", 0x12A8, 0x1680, 119,
     "mountain screen top-left stage name, centred: inner x~12-131 (docs/survey.md §9, 2026-10-22)"),
]
WINDOW_LIMITS += (
    [(m, 0x72EC, 0x8CC8, 234, "stage advice: text x=48, inner right edge x~282 (docs/survey.md §9)") for m in _SUZU]
    + [("SUZU_0.BIN", 0xCB6C, 0xE548, 234, "stage advice"), ("SUZU_0.BIN", 0x18770, 0x1A14C, 234, "stage advice")]
)
# Training results over the picture (success and failure share the frame): text x=48, inner right edge x~280
WINDOW_LIMITS += [("KWAMENU.BIN", 0x196A4, 0x19DD4, 232, "training results")]
# Memory card save dialog (questions and results seen on screen): text x=88, inner right edge x~241
WINDOW_LIMITS += [("KWAMENU.BIN", o, o + 1, 153, "memory card save dialog") for o in (0x10A98, 0x10B00, 0x10BB0, 0x10BFC)]
# Mountain screen progress status after a stage: text x=72, inner right edge x~252 (docs/survey.md §9, 2026-10-22)
WINDOW_LIMITS += [(m, 0x0, 0x19C, 180, "progress status (ahead of or behind plan)") for m in _SUZU]
# Climbing screen: frame x = 8*f384, inner right edge = 8*f384 + 16*(tiles-1) - 4 (docs/survey.md §9, 2026-10-22)
KABE_EVENTS = (0x2C014, 0x2C6F4)  # messages opened by the event handlers 0x800B3D2C-0x800B5604
WINDOW_LIMITS += [
    ("KABE.BIN", *KABE_EVENTS, 220,
     "climbing event messages (rockfall, avalanche, gust, hands, spindrift): text x=56, inner right edge x~276"),
    ("KABE.BIN", 0x2C880, 0x2C8A4, 124,
     "climbing notices (hunger, pitons found): text x=40, inner right edge x~164"),
    ("KABE.BIN", 0x2D74C, 0x2D750, 252,
     "altitude sickness near the summit: text x=40, 18 tiles from the code, edge by the formula"),
    ("KABE.BIN", 0x2C6F4, 0x2C880, 252,
     "level-up and new techniques: text x=40, 18 tiles from the code, edge by the formula"),
    ("KABE.BIN", 0x2C8A4, 0x2C8A5, 156,
     "terrace question: text x=80, inner right edge x~236"),
    ("KABE.BIN", 0x2D650, 0x2D6B0, 236,
     "give-up questions: text x=48, 17 tiles from the code, edge by the formula"),
    ("KABE.BIN", 0x2D6F8, 0x2D74C, 236, "give-up questions"),
]
# Camp screen between stages (MESI): boxes sized by the caller, not tiles (docs/survey.md §9, 2026-10-22)
WINDOW_LIMITS += [
    ("MESI.BIN", 0x1F9C, 0x1FFC, 245, "food ran out: text x=38, inner right edge x~283"),
    ("MESI.BIN", 0x1FFC, 0x2030, 203, "bivouac remark: text x=64, box x=60-268"),
    ("MESI.BIN", 0x2030, 0x2074, 191,
     "plan question: text x=68, inner right edge x~259; the F9 line is checked on screen"),
    ("MESI.BIN", 0x20AC, 0x211C, 187, "rest menu: text x=72, inner right edge x~259"),
    ("MESI.BIN", 0x211C, 0x21D0, 203, "rest and meal results: text x=64, box x=60-268"),
    ("MESI.BIN", 0x2210, 0x2224, 203, "bivouac: text x=64, box x=60-268"),
]
# Mountain screen between stages (MT0/MT1, same layout): docs/survey.md §9, 2026-10-22
WINDOW_LIMITS += [
    entry for m in ("MT0.BIN", "MT1.BIN") for entry in (
        (m, 0x58, 0x88, 132, "stage-to-stage note: text x=40, inner right edge x~172"),
        (m, 0x160, 0x200, 216, "stage move header: text x=64, inner right edge x~280"),
        (m, 0xC90, 0x14EC, 216, "route descriptions, drawn inside the stage move window"),
        (m, 0x14EC, 0x17E8, 178, "scenery remarks under the photo: text x=74, inner right edge x~252, 5 lines"),
    )
]
# Move hazards (storm, rockfall, spindrift, hidden cliff, crevasse): the text x of each message comes
# from the record table at SUZU_1 0xD3AC; warning frame inner right x~252, main x~280, outcome x~252
_HAZARD_WARNINGS = {0x20C: 179, 0x588: 178, 0x7C4: 178, 0xA88: 178, 0xB8C: 178}
_HAZARD_MAIN = {0x240: 220, 0x438: 220, 0x5BC: 210, 0x810: 210, 0xAC4: 210, 0xBD4: 205}
_HAZARD_OUTCOMES = (0x2DC, 0x340, 0x384, 0x3EC, 0x4D4, 0x53C, 0x648, 0x6A0, 0x6E0, 0x74C,
                    0x788, 0x89C, 0x8FC, 0x96C, 0x9C4, 0xA2C, 0xAF8, 0xB38, 0xBFC, 0xC54)
WINDOW_LIMITS += [
    (m, off, off + 1, px, "move hazard message")
    for m in ("MT0.BIN", "MT1.BIN")
    for off, px in [*_HAZARD_WARNINGS.items(), *_HAZARD_MAIN.items(), *((o, 178) for o in _HAZARD_OUTCOMES)]
]


# Windows where {F8:00} is the player name, drawn in a fixed 8-cell slot (docs/survey.md §9)
NAME_SLOT_W = 8 * CELL_W
NAME_SLOT_WINDOWS = [("KABE.BIN", *KABE_EVENTS, NAME_SLOT_W, "climbing event messages")]


def _limit(table, copies):
    found = []
    for cid in copies:
        mod, off = cid.split(":")
        found += [px for m, lo, hi, px, _ in table if m == mod and lo <= int(off, 16) < hi]
    return min(found) if found else None


def window_limit(copies):
    """Smallest measured limit among a unit's copies, or None if no copy sits in a measured window."""
    found = [x for x in (_limit(WINDOW_LIMITS, copies), _limit(FIXED_WINDOWS, copies)) if x is not None]
    return min(found) if found else None


def fixed_line_widths(toks):
    lines = [0]
    for t in toks:
        if t == ("nl",):
            lines.append(0)
        elif t[0] == "ctl" and t[1] == 0xFC:
            lines[-1] += CELL_W * t[2][0]
        elif t[0] == "ctl":
            continue
        else:
            lines[-1] += CELL_W
    return lines


def window_problems(units_, ko, widths=None):
    """Lines wider than a measured window limit."""
    out = []
    for k, entry in ko.items():
        if not entry.get("ko"):
            continue
        for copies, text, _ in variants(units_[k], entry):
            prop, fixed = _limit(WINDOW_LIMITS, copies), _limit(FIXED_WINDOWS, copies)
            if prop is None and fixed is None:
                continue
            # layout at the end of a line (FC tabs, FD spaces) draws nothing
            text = re.sub(r"(?:\{FC:[0-9A-F]{2}\}|　| )+(?=\n|$)", "", text)
            toks = tokenize(text)
            name_w = _limit(NAME_SLOT_WINDOWS, copies) or 0
            for limit, lines, tag in ((prop, ko_line_widths(toks, widths, name_w) if prop else [], ""),
                                      (fixed, fixed_line_widths(toks) if fixed else [], " (fixed 13px)")):
                over = [(i + 1, w) for i, w in enumerate(lines) if w > limit]
                if over:
                    out.append((k, "window", ", ".join(f"line {i} {w}px" for i, w in over) + f" > {limit}px{tag}"))
    return out


def width_warnings(units_, ko, widths):
    """Lines wider than the widest source line of the same string, for strings in windows
    not yet measured. Observed source usage, not a window limit, so these are review candidates."""
    out = []
    for k, entry in ko.items():
        if not entry.get("ko") or window_limit(units_[k].get("copies", [])) is not None:
            continue
        src = max(source_line_widths(tc.decode(bytes.fromhex(units_[k]["source"])), widths))
        got = max(ko_line_widths(tokenize(entry["ko"]), widths))
        if got > src:
            out.append((k, "width", f"{got}px > source {src}px"))
    return out


def variants(u, entry):
    """[(copy ids, text, capacity)]: the default wording on the copies without a by_copy text."""
    by = entry.get("by_copy", {})
    copies = u.get("copies") or ["*"]
    caps = u.get("caps") or {c: u["capacity"] for c in copies}
    rest = [c for c in copies if c not in by]
    out = [(rest, entry["ko"], min(caps[c] for c in rest))] if rest else []
    for c, text in by.items():
        out.append(([c], text, caps[c]))
    return out


def check(units_, ko, one_byte):
    probs = []
    for k, entry in ko.items():
        if not entry.get("ko"):
            continue
        src = tokenize(units_[k]["text"])
        for copies, text, cap in variants(units_[k], entry):
            where = "" if not entry.get("by_copy") or copies[0] not in entry["by_copy"] else f" [{copies[0]}]"
            toks = tokenize(text)
            if protected(toks) != protected(src):
                probs.append((k, "tokens", f"{protected(toks)} != source {protected(src)}{where}"))
            bad = sorted({t[1] for t in toks if t[0] == "c" and not encodable(t[1])})
            if bad:
                probs.append((k, "glyph", "".join(bad) + where))
            size = byte_length(toks, one_byte)
            if size > cap:
                probs.append((k, "capacity", f"{size} > {cap}{where}"))
    return probs


def main():
    src, kodir = Path(sys.argv[1]), Path(sys.argv[2])
    es = [e for p in sorted(src.glob("*.json")) for e in json.loads(p.read_text(encoding="utf-8"))["entries"]]
    us = units.build(es)
    files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(kodir.glob("*.json"))}
    merged = {k: v for f in files.values() for k, v in f.items()}
    plan = fit_plan(us, merged)
    total = 0
    for name, ko in files.items():
        for k, kind, msg in check(us, ko, plan) + window_problems(us, ko):
            total += 1
            print(f"{name} {k} {kind}: {msg}")
    exe = Path(__file__).resolve().parent.parent / "work" / "files" / "SLPS_006.62"
    warned = 0
    if exe.exists():
        table = exe.read_bytes()[WIDTH_OFFSET : WIDTH_OFFSET + 1348]
        widths = dict(enumerate(table))
        for name, ko in files.items():
            for k, kind, msg in width_warnings(us, ko, widths):
                warned += 1
                if "-w" in sys.argv:
                    print(f"{name} {k} {kind}: {msg}")
    done = sum(1 for f in files.values() for v in f.values() if v.get("ko"))
    print(f"{total} problems, {warned} width warnings (-w to list), "
          f"{done}/{sum(len(f) for f in files.values())} translated, 1-byte plan {len(plan)}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
