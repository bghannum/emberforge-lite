"""Provider credentials: a `.env` shim and a names-only status report.

Keys are local operator credentials. This module sets them into the process
environment for the adapters to read and reports *whether* each is present.
It never returns, logs, or serialises a value.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent

KEYS = {
    "spritelab": "SPRITELAB_API_KEY",
    "openai": "OPENAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


def load_env_file(path: Path = ROOT / ".env") -> list[str]:
    """Set `NAME=value` lines from `path` into the environment, if not already set.

    Returns the names it filled. Same shape as emberforge's shim: no quoting
    rules beyond stripping one pair of matching quotes, no export keyword, no
    interpolation. A missing file is not an error.
    """
    filled: list[str] = []
    if not path.is_file():
        return filled
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name and not os.environ.get(name):
            os.environ[name] = value
            filled.append(name)
    return filled


def configured() -> dict[str, bool]:
    """Which providers have a key in the environment. Names only."""
    return {name: bool(os.environ.get(var, "").strip()) for name, var in KEYS.items()}
