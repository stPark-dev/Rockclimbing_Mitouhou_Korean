"""Extract every Form 1 file of the data track to a directory (analysis input).

Files that are not readable as Form 1 from track 1 — the STR movies with Form 2
sectors and the CDDA/*.DA records that point into the audio tracks — are
skipped and listed.

usage: extract.py <track 01 .bin> <outdir>
"""

import sys
from pathlib import Path

import iso


def extract(raw, outdir):
    disc = iso.load(raw)
    skipped = []
    for name in sorted(disc.files):
        try:
            data = iso.read_file(raw, disc, name)
        except ValueError:
            skipped.append(name)
            continue
        p = Path(outdir) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return skipped


def main():
    skipped = extract(Path(sys.argv[1]).read_bytes(), sys.argv[2])
    print(f"skipped {len(skipped)} non-Form 1 or out-of-track files")


if __name__ == "__main__":
    main()
