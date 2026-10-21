"""Glyph-index -> character table (tables/charmap.tsv).

Columns: glyph, character, read status. Status `visual` = read from the
bitmap, `context` = settled by the source text it appears in, `unverified` =
read from the bitmap but not found in root-module text.
"""

GLYPHS = 1348


def load(path, size=GLYPHS):
    table = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        k, c, status = line.rstrip("\n").split("\t")
        if int(k) in table:
            raise ValueError(f"glyph {k} listed twice")
        table[int(k)] = (c, status)
    missing = set(range(size)) - set(table)
    if missing:
        raise ValueError(f"glyphs missing from the table: {sorted(missing)[:10]}")
    return table


def text(toks, table):
    out = []
    for t in toks:
        if t[0] == "g":
            out.append(table[t[1]][0])
        elif t == ("nl",):
            out.append("\n")
        elif t == ("sp",):
            out.append("　")
        elif t[0] == "ctl":
            out.append("{%02X:%s}" % (t[1], ",".join(f"{b:02X}" for b in t[2])))
    return "".join(out)
