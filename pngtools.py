"""Stdlib PNG decode, nearest-neighbour fit onto a padded canvas, and encode.

Exists for one provider fact: SpriteLab `/animate` refuses inputs over 256 px per
axis and returns exactly the canvas it is given. So a source has to be scaled
*and* padded before submission -- the margin is the room the animation moves
into; without it a raised arm leaves the canvas and comes back clipped.

The geometry mirrors emberforge's `transforms.plan_submission` exactly (content
bounding box, longest edge to `canvas - 2 * margin`, horizontally centred,
bottom-aligned above the floor margin, nearest-neighbour only). Nearest is not a
taste: pixel art has no anti-aliasing, and any smoothing filter invents colours.

Only 8-bit RGB/RGBA non-interlaced PNGs are decoded. That is what every sprite
the user has uploaded is, and what every provider here returns.
"""

from __future__ import annotations

import struct
import zlib
from fractions import Fraction
from typing import Any

from media import PNG_SIGNATURE, inspect_png

DEFAULT_CANVAS = 256
DEFAULT_MARGIN = 16


class PngUnsupported(ValueError):
    """The PNG is valid but not a shape this decoder handles."""


def decode_rgba(data: bytes) -> tuple[int, int, bytearray]:
    """Decode to a flat RGBA buffer (4 bytes per pixel, row-major)."""
    width, height, frames = inspect_png(data)  # bounds size and dimensions first
    if frames != 1:
        raise PngUnsupported("animated PNGs are not supported; a source must be a still")

    pos = len(PNG_SIGNATURE)
    ihdr = None
    idat = bytearray()
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat += payload
        elif kind == b"IEND":
            break
    if ihdr is None:
        raise PngUnsupported("no IHDR chunk")

    _, _, depth, colour, _, _, interlace = ihdr
    if depth != 8 or colour not in (2, 6) or interlace != 0:
        raise PngUnsupported(
            "only 8-bit RGB or RGBA, non-interlaced PNGs are supported; "
            "re-export the sprite in that form"
        )
    bpp = 4 if colour == 6 else 3
    stride = width * bpp

    raw = zlib.decompress(bytes(idat))
    if len(raw) != (stride + 1) * height:
        raise PngUnsupported("PNG image data has the wrong length")

    out = bytearray(width * height * 4)
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filt = raw[start]
        line = bytearray(raw[start + 1 : start + 1 + stride])
        _unfilter(filt, line, prev, bpp)
        if bpp == 4:
            out[y * stride : (y + 1) * stride] = line
        else:
            row = y * width * 4
            for x in range(width):
                s = x * 3
                d = row + x * 4
                out[d] = line[s]
                out[d + 1] = line[s + 1]
                out[d + 2] = line[s + 2]
                out[d + 3] = 255
        prev = line
    return width, height, out


def _unfilter(filt: int, line: bytearray, prev: bytearray, bpp: int) -> None:
    n = len(line)
    if filt == 0:
        return
    if filt == 1:
        for i in range(bpp, n):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif filt == 2:
        for i in range(n):
            line[i] = (line[i] + prev[i]) & 0xFF
    elif filt == 3:
        for i in range(n):
            a = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
    elif filt == 4:
        for i in range(n):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa = abs(p - a)
            pb = abs(p - b)
            pc = abs(p - c)
            if pa <= pb and pa <= pc:
                pred = a
            elif pb <= pc:
                pred = b
            else:
                pred = c
            line[i] = (line[i] + pred) & 0xFF
    else:
        raise PngUnsupported(f"unknown PNG filter type {filt}")


def content_box(width: int, height: int, rgba: bytearray) -> tuple[int, int, int, int]:
    """Bounding box (left, top, right, bottom) of pixels with alpha > 0."""
    left, top, right, bottom = width, height, 0, 0
    alpha = rgba[3::4]
    for y in range(height):
        row = alpha[y * width : (y + 1) * width]
        if not any(row):
            continue
        first = next(i for i, a in enumerate(row) if a)
        last = width - next(i for i, a in enumerate(reversed(row)) if a)
        left = min(left, first)
        right = max(right, last)
        top = min(top, y)
        bottom = y + 1
    if right <= left:
        raise PngUnsupported("image is fully transparent; there is no content to frame")
    return left, top, right, bottom


def fit_to_canvas(
    width: int,
    height: int,
    rgba: bytearray,
    *,
    canvas: int = DEFAULT_CANVAS,
    margin: int = DEFAULT_MARGIN,
) -> tuple[bytes, dict[str, Any]]:
    """Scale the content onto a `canvas` square with `margin` all round.

    Returns the encoded PNG and a JSON-safe plan recording exactly what was done.
    """
    left, top, right, bottom = content_box(width, height, rgba)
    cw, ch = right - left, bottom - top
    available = canvas - 2 * margin
    if available <= 0:
        raise PngUnsupported(f"a {margin}px margin leaves no room on a {canvas}px canvas")

    scale = Fraction(available, max(cw, ch))
    sw = max(1, round(cw * scale))
    sh = max(1, round(ch * scale))
    px = (canvas - sw) // 2
    py = canvas - margin - sh

    out = bytearray(canvas * canvas * 4)
    for y in range(sh):
        sy = top + (y * ch) // sh
        src_row = sy * width * 4
        dst_row = (py + y) * canvas * 4
        for x in range(sw):
            sx = left + (x * cw) // sw
            s = src_row + sx * 4
            d = dst_row + (px + x) * 4
            out[d : d + 4] = rgba[s : s + 4]

    plan = {
        "source_size": [width, height],
        "content_box": [left, top, right, bottom],
        "scale": f"{scale.numerator}/{scale.denominator}",
        "scaled_size": [sw, sh],
        "canvas": [canvas, canvas],
        "placement": [px, py],
        "resampling": "nearest",
    }
    return encode_rgba(canvas, canvas, out), plan


def encode_rgba(width: int, height: int, rgba: bytearray) -> bytes:
    """Encode a flat RGBA buffer as a PNG (filter 0 on every row)."""
    stride = width * 4
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows += rgba[y * stride : (y + 1) * stride]

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def fit_png(data: bytes, *, canvas: int = DEFAULT_CANVAS, margin: int = DEFAULT_MARGIN) -> tuple[bytes, dict[str, Any]]:
    """Decode, fit, encode in one call."""
    width, height, rgba = decode_rgba(data)
    return fit_to_canvas(width, height, rgba, canvas=canvas, margin=margin)
