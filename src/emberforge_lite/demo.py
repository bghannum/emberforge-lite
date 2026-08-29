"""The offline demo actor and the `demo` command.

The demo needs no credentials and no network. A committed sample actor -- the
"evil-treant", generated on the owner's own paid SpriteLab, OpenAI, and
ElevenLabs subscriptions -- ships under ``demo_assets/`` with its ledger and
provenance (see its README for the rights context). ``run_demo`` copies it into a
data directory and serves it.

``synthesize_demo_actor`` builds a *procedural* stand-in actor from the
deterministic fake-provider byte generators; it is a fallback for a package that
somehow lacks the committed assets, and a lightweight fixture for the tests.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from emberforge_lite import build, generate, provenance, server
from emberforge_lite.config import Paths
from emberforge_lite.providers.fakes import FAKE_NOW, FAKE_PREVIEW_GIF, _png, _wav

DEMO_SLUG = "evil-treant"
DEMO_ASSETS = Path(__file__).parent / "demo_assets"


class _DemoProv:
    """CandidateProvenance-shaped record for the synthetic demo assets."""

    provider = "fake"
    model = None
    prompt = "a friendly ember familiar, pixel art"
    generated_at = FAKE_NOW
    terms_reviewed_at = FAKE_NOW.date()
    account_rights = "synthetic_demo_mit_licensed"
    attribution_required = False
    attribution_text = None
    transforms = ()
    vendor = {"note": "deterministic fake-provider output"}


def synthesize_demo_actor(actors_dir: Path, slug: str = DEMO_SLUG) -> Path:
    """Write a complete, valid, deterministic actor under `actors_dir`."""
    actor = actors_dir / slug
    for sub in ("sprites", "animations", "sounds"):
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
        "prompt": _DemoProv.prompt,
        "settings": {"provider_choice": "spritelab_epic"},
        "estimate": {"unit": "spritelab_credits", "amount": "1"},
        "outputs": {"sprite": sprite},
        "reported_charge": "1",
        "charge_unit": "spritelab_credits",
    }
    (actor / generate.LEDGER_NAME).write_text(json.dumps(ledger, sort_keys=True) + "\n")

    # Record provenance so the demo showcases the generated/uploaded badges.
    for rel, charge in ((f"sprites/{sprite}", "1"), (f"animations/{anim}", "20"), (f"sounds/{sound}", "32")):
        provenance.record_generated(actor, rel, _DemoProv(), reported_charge=charge, charge_unit="spritelab_credits")
    return actor


def _install_demo_actor(actors_dir: Path) -> None:
    """Copy the packaged demo actor, or synthesize it if the package lacks it."""
    packaged = DEMO_ASSETS / DEMO_SLUG
    if packaged.is_dir():
        shutil.copytree(packaged, actors_dir / DEMO_SLUG, dirs_exist_ok=True)
        # Ensure provenance exists even if the packaged copy predates it.
        if not (actors_dir / DEMO_SLUG / provenance.FILENAME).is_file():
            synthesize_demo_actor(actors_dir)
    else:
        synthesize_demo_actor(actors_dir)


def run_demo(port: int = 8000, *, keep: bool = False, data_dir: str | Path | None = None) -> None:
    """Serve the demo actor. Uses a temp data dir unless one is given."""
    ephemeral = data_dir is None
    base = Path(data_dir).expanduser().resolve() if data_dir else Path(tempfile.mkdtemp(prefix="emberforge-demo-"))
    paths = Paths(base).ensure()
    _install_demo_actor(paths.actors)

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
