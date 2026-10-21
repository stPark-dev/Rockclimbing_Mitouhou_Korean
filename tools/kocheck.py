"""Mechanical checks for translations in text/ko (translation-workflow §5.1).

- tokens: F8/F9/FA/FB controls (name slots, string jumps, numbers, draw
  attributes) keep their count, order and arguments. FC, line breaks and the
  FD full-width space are layout and may move.
- glyph: every character is Hangul, a glyph the Korean font keeps (digits,
  Latin, symbols), or new punctuation adopted in D4. Kana and kanji cells are
  reused for Hangul, and 。、 are replaced by . , (D4).
- capacity: the in-place size (D3), counting the most frequent syllables as
  1-byte codes. The 1-byte plan is an estimate until the build assigns codes.

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
# 1-byte codes reach glyph cells 0-238 and 244-246 (F5-F7). Cells 0-59 stay fixed: FA prints
# digits from cells 0-9, and the symbols and Latin capitals keep their codes. The build places
# NEW_PUNCT, ｃｍｘ, ・ and ？ in 1-byte cells as well; every other non-Hangul glyph keeps a
# 2-byte cell.
FIXED_ONE_BYTE = 60
ONE_BYTE_OTHER = set("ｃｍｘ・？")
ONE_BYTE_SLOTS = (239 + 3) - FIXED_ONE_BYTE - len(NEW_PUNCT) - len(ONE_BYTE_OTHER)
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
    entries = []
    for k, v in ko.items():
        if v.get("ko"):
            toks = tokenize(v["ko"])
            cnt = collections.Counter(t[1] for t in toks if t[0] == "c" and "가" <= t[1] <= "힣")
            entries.append((toks, units_[k]["capacity"], cnt))
    freq = collections.Counter()
    for _, _, cnt in entries:
        freq.update(cnt)
    plan = one_byte_plan([v["ko"] for v in ko.values() if v.get("ko")], slots)
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


def ko_line_widths(toks, widths=None):
    lines = [0]
    for t in toks:
        if t == ("nl",):
            lines.append(0)
        elif t == ("sp",):
            lines[-1] += CELL_W
        elif t[0] == "ctl" and t[1] == 0xFC:
            lines[-1] += CELL_W * t[2][0]
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


def width_warnings(units_, ko, widths):
    """Lines wider than the widest source line of the same string. Observed source
    usage, not a confirmed window limit, so these are review candidates."""
    out = []
    for k, entry in ko.items():
        if not entry.get("ko"):
            continue
        src = max(source_line_widths(tc.decode(bytes.fromhex(units_[k]["source"])), widths))
        got = max(ko_line_widths(tokenize(entry["ko"]), widths))
        if got > src:
            out.append((k, "width", f"{got}px > source {src}px"))
    return out


def check(units_, ko, one_byte):
    probs = []
    for k, entry in ko.items():
        if not entry.get("ko"):
            continue
        toks = tokenize(entry["ko"])
        src = tokenize(units_[k]["text"])
        if protected(toks) != protected(src):
            probs.append((k, "tokens", f"{protected(toks)} != source {protected(src)}"))
        bad = sorted({t[1] for t in toks if t[0] == "c" and not encodable(t[1])})
        if bad:
            probs.append((k, "glyph", "".join(bad)))
        size = byte_length(toks, one_byte)
        if size > units_[k]["capacity"]:
            probs.append((k, "capacity", f"{size} > {units_[k]['capacity']}"))
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
        for k, kind, msg in check(us, ko, plan):
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
