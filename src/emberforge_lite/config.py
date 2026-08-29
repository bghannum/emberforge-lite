"""Where Emberforge Lite keeps its runtime data, and how that location is chosen.

Runtime content lives entirely outside the source tree, under a single data
directory resolved in this order:

1. an explicit ``--data-dir`` (the ``data_dir`` argument here);
2. the ``EMBERFORGE_DATA_DIR`` environment variable;
3. a per-user platform default.

Under the data directory:

    <data-dir>/actors   one folder per actor (art, sounds, links, ledger)
    <data-dir>/site     generated gallery.html and actor-<slug>.html pages
    <data-dir>/tmp      scratch space for atomic writes and exports

Keeping ``actors`` and ``site`` as siblings under the data directory is why the
served pages address media with root-relative ``/actors/...`` URLs rather than
paths relative to the page file.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "emberforge-lite"


def platform_default_data_dir() -> Path:
    """The per-user data directory for this OS.

    * macOS: ``~/Library/Application Support/emberforge-lite``
    * Linux/other: ``$XDG_DATA_HOME/emberforge-lite`` or
      ``~/.local/share/emberforge-lite``
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME


def resolve_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the data directory using the documented precedence."""
    if data_dir:
        return Path(data_dir).expanduser().resolve()
    env = os.environ.get("EMBERFORGE_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return platform_default_data_dir()


@dataclass(frozen=True)
class Paths:
    """The resolved directory layout under one data directory."""

    data_dir: Path

    @property
    def actors(self) -> Path:
        return self.data_dir / "actors"

    @property
    def site(self) -> Path:
        return self.data_dir / "site"

    @property
    def tmp(self) -> Path:
        return self.data_dir / "tmp"

    def ensure(self) -> Paths:
        """Create the layout if it does not exist. Returns self."""
        for d in (self.data_dir, self.actors, self.site, self.tmp):
            d.mkdir(parents=True, exist_ok=True)
        return self


def paths_for(data_dir: str | os.PathLike[str] | None = None) -> Paths:
    """Resolve and return the :class:`Paths` for the chosen data directory."""
    return Paths(resolve_data_dir(data_dir))
