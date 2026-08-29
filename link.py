#!/usr/bin/env python3
"""Link a sound to an animation for one actor, then re-run build.py.

    python3 link.py <actor-slug> <animation-filename> <sound-filename>

Both filenames must already exist in actors/<slug>/animations/ and
actors/<slug>/sounds/. Writes/updates actors/<slug>/links.json.
"""

import sys
from pathlib import Path

from linking import add_link

ROOT = Path(__file__).parent


def main() -> None:
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(1)

    slug, anim_name, sound_name = sys.argv[1:4]
    try:
        add_link(ROOT / "actors", slug, anim_name, sound_name)
    except FileNotFoundError as e:
        raise SystemExit(str(e))

    print(f"Linked {sound_name} -> {anim_name} for {slug}. Run build.py to see it.")


if __name__ == "__main__":
    main()
