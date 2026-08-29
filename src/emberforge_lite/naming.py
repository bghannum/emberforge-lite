"""Slug and filename hygiene, shared by the server and the generator."""

from __future__ import annotations

import re
from pathlib import Path

SLUG_RE = re.compile(r"[^a-z0-9_-]+")
FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def sanitize_slug(raw: str) -> str:
    return SLUG_RE.sub("-", raw.strip().lower()).strip("-")


def sanitize_filename(raw: str) -> str:
    name = Path(raw).name  # strips any directory components / traversal
    return FILENAME_RE.sub("-", name).strip("-.")


def asset_stem(raw: str) -> str:
    """A short name for a generated asset: lowercase, underscores, no extension."""
    stem = SLUG_RE.sub("_", Path(raw).stem.strip().lower()).strip("_-")
    return stem.replace("-", "_")


def unique_path(dir_path: Path, filename: str) -> Path:
    candidate = dir_path / filename
    if not candidate.exists():
        return candidate
    stem, ext = Path(filename).stem, Path(filename).suffix
    n = 2
    while True:
        candidate = dir_path / f"{stem}-{n}{ext}"
        if not candidate.exists():
            return candidate
        n += 1
