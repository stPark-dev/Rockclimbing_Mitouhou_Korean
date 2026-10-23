"""Picture replacement for compressed TIMs (D1, D11), docs/graphics_text.md.

TIMs here are 4bpp or 8bpp with one CLUT block. A replacement keeps the header, the CLUT and the
VRAM position, changes only the pixel indices, and is recompressed (tools/lz74.py) into the
original slot of the stream, which is checked against the original bytes first.
"""

import hashlib
import struct

import lz74

# title logo on MENU/KWAMENU.BIN: three 8bpp pieces drawn side by side at (15, 31), sharing the
# background's 256-colour CLUT (0, 480). (stream offset, x in the 288 x 88 logo, width)
LOGO_PIECES = ((0x56D24, 0, 128), (0x59A54, 128, 128), (0x59128, 256, 32))
LOGO_SIZE = (288, 88)
LOGO_SHA1 = {0x56D24: "955d5b18351cd2c1", 0x59A54: "916dad0d6ad711d5", 0x59128: "d9157241122744a1"}


def _blocks(tim):
    flag = struct.unpack_from("<I", tim, 4)[0]
    p = 8
    clut = None
    if flag & 8:
        clut = p
        p += struct.unpack_from("<I", tim, p)[0]
    return flag & 3, clut, p


def image(tim):
    """(width in pixels, height, pixel bytes as stored)."""
    bpp, _, p = _blocks(tim)
    blen, _, _, w, h = struct.unpack_from("<IHHHH", tim, p)
    return w * (4, 2, 1)[bpp], h, bytes(tim[p + 12:p + blen])


def palette(tim):
    _, c, _ = _blocks(tim)
    blen = struct.unpack_from("<I", tim, c)[0]
    vals = struct.unpack_from(f"<{(blen - 12) // 2}H", tim, c + 12)
    return [((v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3) for v in vals]


def with_image(tim, pixels):
    _, _, p = _blocks(tim)
    blen = struct.unpack_from("<I", tim, p)[0]
    if len(pixels) != blen - 12:
        raise ValueError(f"{len(pixels)} pixel bytes for an image of {blen - 12}")
    return bytes(tim[:p + 12]) + bytes(pixels) + bytes(tim[p + blen:])


def slot(data, off):
    """Bytes the stream at off may take: its length plus the zero padding before the next data."""
    _, used = lz74.decode_stream(data, off)
    end = off + used
    while end < len(data) and data[end] == 0:
        end += 1
    return end - off


def quantize(art, pal, size=None):
    """RGB picture -> palette indices (Floyd-Steinberg), as a list of rows."""
    from PIL import Image
    if size:
        art = art.convert("RGB").resize(size, Image.LANCZOS)
    p = Image.new("P", (1, 1))
    p.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 3 * len(pal)))
    q = art.convert("RGB").quantize(palette=p, dither=Image.FLOYDSTEINBERG)
    w, h = q.size
    flat = list(q.getdata())
    return [flat[y * w:(y + 1) * w] for y in range(h)]


def _undithered(art, pal):
    from PIL import Image
    p = Image.new("P", (1, 1))
    p.putpalette([c for rgb in pal for c in rgb] + [0] * (768 - 3 * len(pal)))
    q = art.convert("RGB").quantize(palette=p, dither=Image.NONE)
    w, h = q.size
    flat = list(q.getdata())
    return [flat[y * w:(y + 1) * w] for y in range(h)]


def original_logo(menu):
    """The current 288 x 88 logo as an RGB picture."""
    from PIL import Image
    out = Image.new("RGB", LOGO_SIZE)
    for off, x0, w in LOGO_PIECES:
        tim, _ = lz74.decode_stream(bytes(menu), off)
        pw, ph, px = image(tim)
        pal = palette(tim)
        piece = Image.new("RGB", (pw, ph))
        piece.putdata([pal[v] for v in px])
        out.paste(piece, (x0, 0))
    return out


def feathered(art, base, feather):
    """art over base, fading linearly to base within `feather` pixels of the edges."""
    from PIL import Image
    w, h = art.size
    mask = Image.new("L", (w, h))
    mask.putdata([min(255, 255 * min(x, y, w - 1 - x, h - 1 - y) // feather)
                  for y in range(h) for x in range(w)])
    return Image.composite(art, base, mask)


def replace_title_logo(menu, art, resize=True, feather=0):
    """Write a 288 x 88 RGB picture over the title logo in MENU/KWAMENU.BIN (bytearray).
    feather > 0 blends the outer pixels into the original logo, so the box does not show on the
    background it sits on."""
    from PIL import Image
    for off, _, _ in LOGO_PIECES:
        _, used = lz74.decode_stream(bytes(menu), off)
        if hashlib.sha1(bytes(menu[off:off + used])).hexdigest()[:16] != LOGO_SHA1[off]:
            raise ValueError(f"title logo piece at {off:#x} is not the supported original")
    if art.size != LOGO_SIZE:
        if not resize:
            raise ValueError(f"title logo must be {LOGO_SIZE}, got {art.size}")
        art = art.convert("RGB").resize(LOGO_SIZE, Image.LANCZOS)
    first, _ = lz74.decode_stream(bytes(menu), LOGO_PIECES[0][0])
    pal = palette(first)
    if feather:
        art = feathered(art.convert("RGB"), original_logo(menu), feather)
    rows = quantize(art, pal)
    flat_rows = None
    written = 0
    for off, x0, w in LOGO_PIECES:
        room = slot(bytes(menu), off)
        tim, _ = lz74.decode_stream(bytes(menu), off)
        for source in ("dithered", "flat"):
            src = rows
            if source == "flat":  # dithering compresses badly; fall back to plain nearest colours
                flat_rows = flat_rows or _undithered(art, pal)
                src = flat_rows
            px = bytes(v for r in src for v in r[x0:x0 + w])
            packed = lz74.encode_stream(with_image(tim, px))
            if len(packed) <= room:
                break
        else:
            raise ValueError(f"title logo piece at {off:#x} needs {len(packed)} bytes, slot is {room}")
        menu[off:off + room] = packed + bytes(room - len(packed))
        written += 1
    return {"pieces": written}
