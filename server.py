#!/usr/bin/env python3
"""DEPRECATED root launcher. Use the installed CLI instead:

    emberforge-lite serve [--port 8000] [--data-dir PATH] [--allow-spend] [--env-file PATH]

This shim is retained through the v0.1.x series and will be removed in v0.2.0.
It forwards to `emberforge-lite serve`, defaulting the data directory to ./actors
in the current tree so the old `python3 server.py [port]` invocation keeps working.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))


def main() -> int:
    print("warning: `python3 server.py` is deprecated; use `emberforge-lite serve`.", file=sys.stderr)
    from emberforge_lite.cli import main as cli_main

    argv = ["serve", "--data-dir", str(Path(__file__).parent)]
    rest = sys.argv[1:]
    # Preserve the legacy positional port and --allow-spend.
    port = [a for a in rest if a.isdigit()]
    if port:
        argv += ["--port", port[0]]
    if "--allow-spend" in rest:
        argv += ["--allow-spend"]
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
