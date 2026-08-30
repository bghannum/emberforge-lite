"""Compose a frame package into a single spritesheet PNG (a "sprite table").

Frames are laid out row-major on a near-square grid with a transparent fill,
so an engine can address frame ``i`` as ``(i % cols, i // cols)``. Nearest
neighbour throughout: pixels are copied, never resampled. Stdlib only, via
:mod:`pngtools`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from emberforge_lite import animmeta, media, pngtools, storage


def grid_shape(count: int, cell_width: int = 1, max_width: int = media.MAX_DIMENSION) -> tuple[int, int]:
    """(cols, rows) for `count` cells: near-square, shrunk to fit `max_width`."""
    if count < 1:
        raise ValueError("a sheet needs at least one frame")
    cols = math.ceil(math.sqrt(count))
    while cols > 1 and cols * cell_width > max_width:
        cols -= 1
    rows = math.ceil(count / cols)
    return cols, rows


def compose_sheet(frames: list[bytes]) -> tuple[bytes, dict[str, Any]]:
    """Blit equally sized RGBA frames onto one grid PNG. Returns (png, layout)."""
    if not frames:
        raise ValueError("a sheet needs at least one frame")
    decoded = [pngtools.decode_rgba(f) for f in frames]
    w, h, _ = decoded[0]
    for i, (fw, fh, _) in enumerate(decoded):
        if (fw, fh) != (w, h):
            raise media.Rejected(f"frame {i} is {fw}x{fh}; expected {w}x{h}")
    cols, rows = grid_shape(len(frames), w)
    sheet_w, sheet_h = cols * w, rows * h
    if sheet_w > media.MAX_DIMENSION or sheet_h > media.MAX_DIMENSION:
        raise media.Rejected(f"sheet would be {sheet_w}x{sheet_h}, over the {media.MAX_DIMENSION}px limit")
    out = bytearray(sheet_w * sheet_h * 4)
    stride = sheet_w * 4
    row_bytes = w * 4
    for i, (_, _, rgba) in enumerate(decoded):
        cx, cy = (i % cols) * w, (i // cols) * h
        for y in range(h):
            dst = (cy + y) * stride + cx * 4
            out[dst : dst + row_bytes] = rgba[y * row_bytes : (y + 1) * row_bytes]
    layout = {"cols": cols, "rows": rows, "cell": [w, h], "frames": len(frames), "size": [sheet_w, sheet_h]}
    return pngtools.encode_rgba(sheet_w, sheet_h, out), layout


def sheet_path(sheets_dir: Path, name: str) -> Path:
    return sheets_dir / f"{name}_sheet.png"


def write_sheet(anim_dir: Path, sheets_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Compose the package under `anim_dir` and write ``<name>_sheet.png``."""
    manifest = animmeta.load_manifest(anim_dir)
    frames = [(anim_dir / animmeta.FRAMES_DIR / f.file).read_bytes() for f in manifest.frames]
    png, layout = compose_sheet(frames)
    target = sheet_path(sheets_dir, anim_dir.name)
    storage.atomic_write_bytes(target, png)
    return target, layout
