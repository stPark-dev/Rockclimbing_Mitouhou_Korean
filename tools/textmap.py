"""Text population of the modules (docs/survey.md §4).

A string is a run the renderer reads from a pointer to FF (textcodec.read_page).
Candidates start at the file start or after a 00/FF byte. They are adopted by
structure and reference, never by how the decoded text looks alone:

- code modules (overlays): a candidate is adopted when a 32-bit word or a
  lui/addiu pair in the module or the main executable points at its start
  ("ref"), or when it is chained to such a string ("chain": separated only by
  0-3 zero bytes of padding). Referenced candidates that read as MIPS bytes
  (`is_code_noise`) are dropped.
- text blobs (SUZU0-4, MT0/1, no code): every string of the chain at file
  start, up to the blob's text end ("blob").

Each string keeps its start offset; its slot (the bytes it may occupy after
translation) runs to the next string of its chain, or for the last one to
4-byte alignment over zero bytes.
"""

import json
import struct
import sys
from pathlib import Path

import charmap
import textcodec as tc

OVERLAY = 0x800AFF18
BLOB = 0x800CF984
MODULES = {
    "KWAMENU.BIN": ("code", OVERLAY),
    "KABE.BIN": ("code", OVERLAY),
    "MESI.BIN": ("code", OVERLAY),
    "MGAME.BIN": ("code", OVERLAY),
    "STAFF.BIN": ("code", OVERLAY),
    "SUZU_0.BIN": ("code", OVERLAY),
    "SUZU_1.BIN": ("code", OVERLAY),
    "X_SUZU.BIN": ("code", 0x800DF3F0),
    "SUZU0.BIN": ("blob", BLOB),
    "SUZU1.BIN": ("blob", BLOB),
    "SUZU2.BIN": ("blob", BLOB),
    "SUZU3.BIN": ("blob", BLOB),
    "SUZU4.BIN": ("blob", BLOB),
    "MT0.BIN": ("blob", BLOB),
    "MT1.BIN": ("blob", BLOB),
}
# MT0/MT1 carry digit tables after their messages (0x17E8 onward)
BLOB_TEXT_END = {"MT0.BIN": 0x17E8, "MT1.BIN": 0x17E8}
EXE_BASE, EXE_HEADER = 0x80010000, 0x800
# Adopted population (reviewed 2026-10-21, revised after the れ-index fix; docs/survey.md §4.3). MGAME.BIN has none:
# its referenced candidates all read as MIPS bytes.
EXPECTED_COUNTS = {
    "KWAMENU.BIN": 731, "KABE.BIN": 62, "MESI.BIN": 22, "STAFF.BIN": 1, "SUZU_0.BIN": 745,
    "SUZU_1.BIN": 268, "X_SUZU.BIN": 115, "SUZU0.BIN": 404, "SUZU1.BIN": 550, "SUZU2.BIN": 469,
    "SUZU3.BIN": 538, "SUZU4.BIN": 472, "MT0.BIN": 90, "MT1.BIN": 90,
}


def candidates(data):
    out, i = [], 0
    while i < len(data):
        if (i == 0 or data[i - 1] in (0, 0xFF)) and data[i]:
            try:
                toks, end = tc.read_page(data, i)
            except (ValueError, IndexError):
                i += 1
                continue
            out.append((i, end, toks))
            i = end
            continue
        i += 1
    return out


def chains(cands, data):
    out, cur = [], []
    for c in cands:
        if cur and c[0] - cur[-1][1] <= 3 and not any(data[cur[-1][1] : c[0]]):
            cur.append(c)
            continue
        if cur:
            out.append(cur)
        cur = [c]
    if cur:
        out.append(cur)
    return out


def slots(chain, data):
    ends = [c[0] for c in chain[1:]]
    last = chain[-1][1]
    pad = last
    while pad < len(data) and pad % 4 and not data[pad]:
        pad += 1
    return ends + [pad]


_LOADS = {0x08, 0x09, 0x0D, 0x20, 0x21, 0x23, 0x24, 0x25, 0x28, 0x29, 0x2B}


def refs(data, base):
    words = [struct.unpack_from("<I", data, i)[0] for i in range(0, len(data) - 3, 4)]
    out = {}
    for i, w in enumerate(words):
        out.setdefault(w, []).append(("word", base + 4 * i))
    for i, w in enumerate(words):
        if w >> 26 != 0x0F:
            continue
        rt, hi = (w >> 16) & 31, (w & 0xFFFF) << 16
        for w2 in words[i + 1 : i + 16]:
            op = w2 >> 26
            if (w2 >> 21) & 31 == rt and op in _LOADS:
                imm = w2 & 0xFFFF
                if op != 0x0D and imm & 0x8000:
                    imm -= 0x10000
                out.setdefault((hi + imm) & 0xFFFFFFFF, []).append(("pair", base + 4 * i))
            if (w2 >> 16) & 31 == rt and op in _LOADS | {0x0F}:
                break
    return out


_CODE_AFTER_RE = set(range(0, 18)) | set(range(20, 26))


def is_code_noise(toks):
    g = [t[1] for t in toks if t[0] == "g"]
    if len(g) < 2:
        return True
    if any(60 <= k <= 85 and k != 83 for k in g):  # Latin lowercase other than the ｘ placeholder
        return True
    # れ (127) followed by a digit, an ASCII-like symbol (＋－＝／ｘ；：＠”＃＄％＆) or Latin lowercase
    return any(a == 127 and (b in _CODE_AFTER_RE or 60 <= b <= 85) for a, b in zip(g, g[1:]))


def _entry(name, start, end, slot_end, data, evidence, sites):
    return {
        "id": f"{name}:{start:05X}",
        "file": name,
        "offset": start,
        "end": end,
        "slot_end": slot_end,
        "source": data[start:end].hex(),
        "evidence": evidence,
        "refs": [f"{k}@{a:08X}" for k, a in sites],
    }


def extract(files, exe):
    exe_refs = refs(exe[EXE_HEADER:], EXE_BASE)
    out = []
    for name, (kind, base) in MODULES.items():
        data = files[name]
        own = refs(data, base) if kind == "code" else {}
        if kind == "blob":
            limit = BLOB_TEXT_END.get(name, len(data))
            chain = [c for c in chains(candidates(data), data)[0] if c[1] <= limit]
            for c, slot_end in zip(chain, slots(chain, data)):
                if any(t[0] == "g" for t in c[2]):
                    out.append(_entry(name, c[0], c[1], min(slot_end, limit), data, "blob", []))
            continue
        for chain in chains(candidates(data), data):
            sites = [own.get(base + c[0], []) + exe_refs.get(base + c[0], []) for c in chain]
            referenced = [bool(s) and not is_code_noise(c[2]) for c, s in zip(chain, sites)]
            if not any(referenced):
                continue
            for c, s, r, slot_end in zip(chain, sites, referenced, slots(chain, data)):
                if is_code_noise(c[2]):
                    continue
                out.append(_entry(name, c[0], c[1], slot_end, data, "ref" if r else "chain", s))
    return out


def write_sources(entries, cm, outdir):
    """One JSON per module: protected source fields plus a display rendering."""
    by_file = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    for name, es in by_file.items():
        kind, base = MODULES.get(name, (None, None))
        doc = {
            "file": name,
            "base": None if base is None else f"{base:08X}",
            "entries": [
                dict(e, capacity=e["slot_end"] - e["offset"],
                     text=charmap.text(tc.decode(bytes.fromhex(e["source"])), cm))
                for e in sorted(es, key=lambda e: e["offset"])
            ],
        }
        (Path(outdir) / f"{name}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    files_dir, table, outdir = sys.argv[1:4]
    files = {n: (Path(files_dir) / n).read_bytes() for n in MODULES}
    entries = extract(files, (Path(files_dir) / "SLPS_006.62").read_bytes())
    counts = {}
    for e in entries:
        counts[e["file"]] = counts.get(e["file"], 0) + 1
    if counts != EXPECTED_COUNTS:
        raise SystemExit(f"population differs from the adopted counts: {counts}")
    write_sources(entries, charmap.load(table), outdir)
    print(f"{len(entries)} strings in {len(counts)} modules")


if __name__ == "__main__":
    main()
