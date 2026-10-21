"""Translation units: one per distinct source byte string (text/src).

The same source sits in several modules (SUZU_0 and SUZU0-4, X_SUZU and
KWAMENU, ...); one translation serves every copy. A unit's capacity is the
smallest slot among its copies, since every copy is replaced in place (D3).
Translations live in text/ko/<group>.json keyed by `key(source)`.

usage: units.py <text/src dir> <text/ko dir>   (creates or extends the group files)
"""

import hashlib
import json
import sys
from pathlib import Path

GROUP_OF = {
    "KWAMENU.BIN": "menu",
    "SUZU_0.BIN": "stage", "X_SUZU.BIN": "stage",
    "SUZU0.BIN": "stage", "SUZU1.BIN": "stage", "SUZU2.BIN": "stage", "SUZU3.BIN": "stage", "SUZU4.BIN": "stage",
    "SUZU_1.BIN": "event", "MT0.BIN": "event", "MT1.BIN": "event",
    "KABE.BIN": "climb", "MESI.BIN": "camp", "STAFF.BIN": "staff",
}
GROUP_ORDER = ["menu", "stage", "event", "climb", "camp", "staff"]


def key(source_hex):
    return "src:" + hashlib.sha1(bytes.fromhex(source_hex)).hexdigest()[:12]


def build(entries):
    out = {}
    for e in sorted(entries, key=lambda e: e["id"]):
        u = out.setdefault(key(e["source"]), {"source": e["source"].lower(), "text": e["text"],
                                              "capacity": e["capacity"], "copies": [], "groups": set()})
        u["capacity"] = min(u["capacity"], e["capacity"])
        u["copies"].append(e["id"])
        u["groups"].add(GROUP_OF[e["file"]])
    for u in out.values():
        u["group"] = next(g for g in GROUP_ORDER if g in u["groups"])
        del u["groups"]
    return out


def merge(existing, units_, group):
    """Translations for one group file: keep authored fields, refresh protected ones."""
    vanished = set(existing) - set(units_)
    if vanished:
        raise ValueError(f"{group}: units no longer in the source: {sorted(vanished)[:5]}")
    out = {}
    for k, u in sorted(units_.items(), key=lambda kv: kv[1]["copies"][0]):
        if u["group"] != group:
            continue
        old = existing.get(k, {})
        out[k] = {"cap": u["capacity"], "copies": u["copies"],
                  "ko": old.get("ko", ""), "status": old.get("status", "untranslated")}
        if old.get("note"):
            out[k]["note"] = old["note"]
    return out


def main():
    src, ko = Path(sys.argv[1]), Path(sys.argv[2])
    es = [e for p in sorted(src.glob("*.json")) for e in json.loads(p.read_text(encoding="utf-8"))["entries"]]
    us = build(es)
    ko.mkdir(parents=True, exist_ok=True)
    for g in GROUP_ORDER:
        p = ko / f"{g}.json"
        existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        others = {k: v for k, v in us.items() if v["group"] == g}
        merged = merge(existing, others, g)
        p.write_text(json.dumps(merged, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(g, len(merged))


if __name__ == "__main__":
    main()
