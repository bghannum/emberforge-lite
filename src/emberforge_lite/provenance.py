"""Per-actor asset provenance (``provenance.json``, schema version 1).

Every asset an actor holds is either **generated** (through a provider) or
**uploaded** (dropped in by the user). For a generated asset this records the
provider, model, prompt, dates, rights context, attribution, transforms, and
reported charge that the provider returned but the ledger did not keep per file.
For an uploaded asset it records only that its rights are unknown, so the UI can
warn a reviewer who is about to treat borrowed art as their own.

The file is keyed by the asset's path relative to the actor directory, e.g.
``"sprites/hero_source.png"``. All writes go through the actor lock and are
atomic, so provenance survives a rename, delete, restart, rebuild, or export.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from emberforge_lite import storage

SCHEMA_VERSION = 1
FILENAME = "provenance.json"


def path_for(actor_dir: Path) -> Path:
    return actor_dir / FILENAME


def load(actor_dir: Path) -> dict[str, Any]:
    p = path_for(actor_dir)
    if not p.is_file():
        return {"schema_version": SCHEMA_VERSION, "assets": {}}
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"schema_version": SCHEMA_VERSION, "assets": {}}
    doc.setdefault("schema_version", SCHEMA_VERSION)
    doc.setdefault("assets", {})
    return doc


def _save(actor_dir: Path, doc: dict[str, Any]) -> None:
    storage.atomic_write_text(path_for(actor_dir), json.dumps(doc, indent=2, sort_keys=True) + "\n")


def _iso(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def record_generated(
    actor_dir: Path,
    rel_path: str,
    provenance: Any,
    *,
    reported_charge: str | None = None,
    charge_unit: str | None = None,
    extra_transforms: tuple[str, ...] = (),
) -> None:
    """Record a generated asset from a provider CandidateProvenance."""
    slug = actor_dir.name
    with storage.actor_lock(slug):
        doc = load(actor_dir)
        entry = {
            "source": "generated",
            "provider": provenance.provider,
            "model": provenance.model,
            "prompt": provenance.prompt,
            "generated_at": _iso(provenance.generated_at),
            "terms_reviewed_at": _iso(provenance.terms_reviewed_at),
            "account_rights": provenance.account_rights,
            "attribution_required": provenance.attribution_required,
            "attribution_text": provenance.attribution_text,
            "transforms": list(provenance.transforms) + list(extra_transforms),
            "reported_charge": (
                {"unit": charge_unit, "amount": reported_charge} if reported_charge is not None else None
            ),
            "vendor": dict(provenance.vendor),
        }
        doc["assets"][rel_path] = entry
        _save(actor_dir, doc)


def record_uploaded(actor_dir: Path, rel_path: str) -> None:
    """Record an uploaded asset: rights unknown, no generation metadata."""
    slug = actor_dir.name
    with storage.actor_lock(slug):
        doc = load(actor_dir)
        doc["assets"][rel_path] = {"source": "uploaded", "account_rights": None}
        _save(actor_dir, doc)


def rename_asset(actor_dir: Path, old_rel: str, new_rel: str) -> None:
    slug = actor_dir.name
    with storage.actor_lock(slug):
        doc = load(actor_dir)
        entry = doc["assets"].pop(old_rel, None)
        if entry is not None:
            doc["assets"][new_rel] = entry
            _save(actor_dir, doc)


def remove_asset(actor_dir: Path, rel_path: str) -> None:
    slug = actor_dir.name
    with storage.actor_lock(slug):
        doc = load(actor_dir)
        if doc["assets"].pop(rel_path, None) is not None:
            _save(actor_dir, doc)


def entry_for(actor_dir: Path, rel_path: str) -> dict[str, Any] | None:
    return load(actor_dir)["assets"].get(rel_path)
