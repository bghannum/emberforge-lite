"""Copy an existing actor tree into a data directory, validating as it goes.

`migrate SOURCE [--data-dir DEST]` performs a one-way, non-destructive copy:

* the source is never modified;
* the destination's ``actors`` directory must be empty (or absent);
* credentials (``.env``) and generated HTML (``gallery.html``,
  ``actor-<slug>.html``) are excluded -- they are re-derived, not migrated;
* every PNG/GIF/WAV/MP3 is validated before it is written, so a corrupt or
  oversized asset stops the migration instead of landing in the new store.

The source may be a data directory (containing ``actors/``) or an ``actors``
directory itself.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from emberforge_lite import media
from emberforge_lite.config import Paths

EXCLUDED_NAMES = {".env"}
_VALIDATED_EXTS = {".png", ".gif", ".wav", ".mp3"}


class MigrationError(Exception):
    """The migration cannot proceed; the destination is left untouched."""


def _source_actors_dir(source: Path) -> Path:
    if (source / "actors").is_dir():
        return source / "actors"
    if source.is_dir():
        return source
    raise MigrationError(f"no actor directory found at {source}")


def _is_excluded(rel: Path) -> bool:
    if rel.name in EXCLUDED_NAMES:
        return True
    # Generated pages: gallery.html and actor-<slug>.html, at the top level.
    if rel.suffix == ".html" and (rel.name == "gallery.html" or rel.name.startswith("actor-")):
        return True
    return False


def _validate(path: Path) -> None:
    ext = path.suffix.lower()
    if ext not in _VALIDATED_EXTS:
        return
    data = path.read_bytes()
    if ext in (".wav", ".mp3"):
        media.inspect_audio(data)
    else:
        media.validate(path)


def migrate(source: str | Path, dest: Paths) -> dict[str, int]:
    """Copy validated actor content from `source` into `dest`. Returns a summary."""
    src_actors = _source_actors_dir(Path(source).expanduser().resolve())
    dest.ensure()
    if dest.actors.exists() and any(dest.actors.iterdir()):
        raise MigrationError(f"destination actors directory is not empty: {dest.actors}")

    copied = 0
    skipped = 0
    actors: set[str] = set()
    for path in sorted(src_actors.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_actors)
        if _is_excluded(rel):
            skipped += 1
            continue
        _validate(path)  # raises media.Rejected on bad content
        target = dest.actors / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
        actors.add(rel.parts[0])

    return {"copied": copied, "skipped": skipped, "actors": len(actors)}
