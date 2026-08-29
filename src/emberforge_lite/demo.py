"""A deterministic, offline demo actor and the `demo` command.

The demo needs no credentials and no network: it synthesizes one actor with a
sprite, an animation, a linked sound, a links file, and a generation ledger,
using the same deterministic byte generators the fake providers use. It exists
so a first-time user can run `emberforge-lite demo` and see the review workbench
immediately.

Milestone 5 replaces this with a committed, rights-safe synthetic actor; the
programmatic version here keeps the command working in the meantime.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from emberforge_lite import build, generate, server
from emberforge_lite.config import Paths
from emberforge_lite.providers.fakes import FAKE_PREVIEW_GIF, _png, _wav

DEMO_SLUG = "ember-familiar"


def synthesize_demo_actor(actors_dir: Path, slug: str = DEMO_SLUG) -> Path:
    """Write a complete, valid, deterministic actor under `actors_dir`."""
    actor = actors_dir / slug
    for sub in ("sprites", "animations", "sounds", "sheets"):
        (actor / sub).mkdir(parents=True, exist_ok=True)

    sprite = f"{slug.replace('-', '_')}_source.png"
    (actor / "sprites" / sprite).write_bytes(_png(64, 64, b"demo-sprite"))

    anim = f"{slug.replace('-', '_')}_idle_preview.gif"
    (actor / "animations" / anim).write_bytes(FAKE_PREVIEW_GIF)

    sound = f"{slug.replace('-', '_')}_chime.wav"
    (actor / "sounds" / sound).write_bytes(_wav(800, b"demo-sound"))

    (actor / "links.json").write_text(json.dumps({anim: [sound]}, indent=2, sort_keys=True) + "\n")

    ledger = {
        "id": "demo000000000000000000000000demo",
        "ts": datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc).isoformat(timespec="seconds"),
        "event": "succeeded",
        "kind": "source",
        "provider": "fake",
        "live": False,
        "prompt": "a friendly ember familiar, pixel art",
        "settings": {"provider_choice": "spritelab_epic"},
        "estimate": {"unit": "spritelab_credits", "amount": "1"},
        "outputs": {"sprite": sprite},
        "reported_charge": "1",
        "charge_unit": "spritelab_credits",
    }
    (actor / generate.LEDGER_NAME).write_text(json.dumps(ledger, sort_keys=True) + "\n")
    return actor


def run_demo(port: int = 8000, *, keep: bool = False, data_dir: str | Path | None = None) -> None:
    """Serve a demo actor. Uses a temp data dir unless one is given."""
    ephemeral = data_dir is None
    base = Path(data_dir).expanduser().resolve() if data_dir else Path(tempfile.mkdtemp(prefix="emberforge-demo-"))
    paths = Paths(base).ensure()
    synthesize_demo_actor(paths.actors)

    build.configure_paths(paths)
    generate.configure_paths(paths)
    try:
        server.serve(paths, port=port, allow_spend=False)
    finally:
        if ephemeral and not keep:
            shutil.rmtree(base, ignore_errors=True)
            print(f"removed demo data directory {base}", flush=True)
        elif ephemeral and keep:
            print(f"demo data kept at {base}", flush=True)
