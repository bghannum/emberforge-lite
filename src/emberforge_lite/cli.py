"""The ``emberforge-lite`` console entry point.

emberforge-lite serve [--port 8000] [--data-dir PATH] [--allow-spend] [--env-file PATH]
emberforge-lite build [--data-dir PATH]
emberforge-lite link ACTOR ANIMATION SOUND [--data-dir PATH]
emberforge-lite migrate SOURCE [--data-dir DEST]
emberforge-lite demo [--port 8000] [--keep] [--data-dir PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from emberforge_lite import __version__, build, generate, media, server
from emberforge_lite.config import paths_for
from emberforge_lite.linking import add_link
from emberforge_lite.migrate import MigrationError, migrate


def _add_data_dir(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--data-dir",
        metavar="PATH",
        default=None,
        help="data directory (default: $EMBERFORGE_DATA_DIR or the platform default)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emberforge-lite", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"emberforge-lite {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="serve the review workbench on loopback")
    p_serve.add_argument("--port", type=int, default=8000)
    _add_data_dir(p_serve)
    p_serve.add_argument(
        "--allow-spend", action="store_true", help="use the live provider APIs (requires keys in the environment)"
    )
    p_serve.add_argument(
        "--env-file",
        metavar="PATH",
        default=None,
        help="explicit .env file to load credentials from (never auto-discovered)",
    )

    p_build = sub.add_parser("build", help="regenerate the static site from the actor tree")
    _add_data_dir(p_build)

    p_link = sub.add_parser("link", help="link a sound to an animation")
    p_link.add_argument("actor")
    p_link.add_argument("animation")
    p_link.add_argument("sound")
    _add_data_dir(p_link)

    p_migrate = sub.add_parser("migrate", help="copy an existing actor tree into a data directory")
    p_migrate.add_argument("source")
    _add_data_dir(p_migrate)

    p_demo = sub.add_parser("demo", help="serve a synthetic offline demo actor")
    p_demo.add_argument("--port", type=int, default=8000)
    p_demo.add_argument("--keep", action="store_true", help="keep the demo data directory on exit")
    _add_data_dir(p_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "serve":
        paths = paths_for(args.data_dir).ensure()
        env_file = Path(args.env_file) if args.env_file else None
        server.serve(paths, port=args.port, allow_spend=args.allow_spend, env_file=env_file)
        return 0

    if args.command == "build":
        paths = paths_for(args.data_dir).ensure()
        build.configure_paths(paths)
        generate.configure_paths(paths)
        count = build.build()
        print(f"Wrote {paths.site / 'gallery.html'} and {count} actor page(s)")
        return 0

    if args.command == "link":
        paths = paths_for(args.data_dir).ensure()
        try:
            add_link(paths.actors, args.actor, args.animation, args.sound)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        build.configure_paths(paths)
        generate.configure_paths(paths)
        build.build()
        print(f"linked {args.sound} -> {args.animation} for {args.actor}")
        return 0

    if args.command == "migrate":
        paths = paths_for(args.data_dir)
        try:
            summary = migrate(args.source, paths)
        except (MigrationError, media.Rejected) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"migrated {summary['copied']} file(s) across {summary['actors']} actor(s) "
            f"({summary['skipped']} excluded) into {paths.actors}"
        )
        return 0

    if args.command == "demo":
        from emberforge_lite.demo import run_demo

        run_demo(port=args.port, keep=args.keep, data_dir=args.data_dir)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
