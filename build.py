#!/usr/bin/env python3
"""DEPRECATED root launcher. Use the installed CLI instead:

    emberforge-lite build [--data-dir PATH]

Retained through v0.1.x, removed in v0.2.0. Rebuilds the static site for the
actor tree in the current directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))


def main() -> int:
    print("warning: `python3 build.py` is deprecated; use `emberforge-lite build`.", file=sys.stderr)
    from emberforge_lite.cli import main as cli_main

    return cli_main(["build", "--data-dir", str(Path(__file__).parent)])


if __name__ == "__main__":
    raise SystemExit(main())
