"""redux_shot.py <name.raw>...: convert PCSX-Redux takeScreenShot dumps (name.txt = w h bpp) to PNG."""
import sys
from pathlib import Path

from PIL import Image

for p in map(Path, sys.argv[1:]):
    w, h, bpp = map(int, p.with_suffix(".txt").read_text().split())
    raw = p.read_bytes()
    if bpp == 24:
        im = Image.frombytes("RGB", (w, h), raw[: w * h * 3])
    else:
        px = [int.from_bytes(raw[i:i + 2], "little") for i in range(0, w * h * 2, 2)]
        im = Image.new("RGB", (w, h))
        im.putdata([((v & 31) << 3, ((v >> 5) & 31) << 3, ((v >> 10) & 31) << 3) for v in px])
    im.save(p.with_suffix(".png"))
    print(p.with_suffix(".png"), w, h, bpp)
