"""Reliable on-disk mutation: per-actor locks and atomic writes.

Every multi-file change to an actor (upload, link, trim, rename, delete,
generation reservation, page rebuild) runs under that actor's lock, and every
individual file is written to a sibling temporary file and swapped into place
with ``os.replace`` so a reader ever sees only the old complete file or the new
complete file, never a half-written one. A crash mid-write leaves a recognizable
``.efl-tmp-*`` file, which :func:`clean_stale_temp` sweeps at startup.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

from emberforge_lite.naming import unique_path

#: Prefix for our atomic-write temporary files, so startup cleanup can find them.
TMP_PREFIX = ".efl-tmp-"

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def actor_lock_for(slug: str) -> threading.RLock:
    """The re-entrant lock for one actor slug (created on first use)."""
    with _locks_guard:
        return _locks.setdefault(slug, threading.RLock())


@contextmanager
def actor_lock(slug: str):
    """Hold one actor's lock for the duration of a mutation."""
    lock = actor_lock_for(slug)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _atomic_replace(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = _mkstemp(target.parent, target.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        _quiet_unlink(Path(tmp_name))
        raise


def _mkstemp(directory: Path, suffix: str) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(dir=directory, prefix=TMP_PREFIX, suffix=suffix)


def _quiet_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def atomic_write_bytes(target: Path, data: bytes) -> None:
    """Write bytes to ``target`` atomically (temp file + replace + fsync)."""
    _atomic_replace(target, data)


def atomic_write_text(target: Path, text: str) -> None:
    """Write text to ``target`` atomically."""
    _atomic_replace(target, text.encode())


def reserve_and_write(directory: Path, filename: str, data: bytes, *, slug: str) -> Path:
    """Under the actor lock, choose a non-colliding name and write atomically.

    Reservation and creation are one locked step so two concurrent writes for
    the same name cannot both resolve to the same free path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with actor_lock(slug):
        target = unique_path(directory, filename)
        # Reserve the name immediately so a concurrent reserve sees it taken.
        target.touch()
        _atomic_replace(target, data)
        return target


def clean_stale_temp(root: Path) -> list[Path]:
    """Delete leftover atomic-write temp files under ``root``. Returns them."""
    removed: list[Path] = []
    if not root.exists():
        return removed
    for path in root.rglob(f"{TMP_PREFIX}*"):
        if path.is_file():
            _quiet_unlink(path)
            removed.append(path)
    return removed
