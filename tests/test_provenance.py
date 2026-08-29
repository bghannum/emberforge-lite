"""Provenance schema v1: record, rename, remove, survive (provenance.py)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from emberforge_lite import provenance


class _Prov:
    """A minimal stand-in for CandidateProvenance."""

    provider = "openai"
    model = "gpt-image-2"
    prompt = "a knight"
    generated_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    terms_reviewed_at = date(2026, 8, 21)
    account_rights = "openai_exclusive"
    attribution_required = False
    attribution_text = None
    transforms = ("nearest_fit",)
    vendor = {"request_id": "req_1"}


@pytest.fixture
def actor(tmp_path):
    d = tmp_path / "hero"
    d.mkdir()
    return d


class TestRecord:
    def test_generated_entry(self, actor):
        provenance.record_generated(actor, "sprites/a.png", _Prov(), reported_charge="0.006", charge_unit="usd")
        entry = provenance.entry_for(actor, "sprites/a.png")
        assert entry["source"] == "generated"
        assert entry["provider"] == "openai"
        assert entry["model"] == "gpt-image-2"
        assert entry["reported_charge"] == {"unit": "usd", "amount": "0.006"}
        assert entry["transforms"] == ["nearest_fit"]

    def test_uploaded_entry(self, actor):
        provenance.record_uploaded(actor, "sprites/u.png")
        entry = provenance.entry_for(actor, "sprites/u.png")
        assert entry == {"source": "uploaded", "account_rights": None}

    def test_schema_version_written(self, actor):
        provenance.record_uploaded(actor, "sprites/u.png")
        assert provenance.load(actor)["schema_version"] == provenance.SCHEMA_VERSION


class TestLifecycle:
    def test_rename_moves_entry(self, actor):
        provenance.record_uploaded(actor, "sprites/old.png")
        provenance.rename_asset(actor, "sprites/old.png", "sprites/new.png")
        assert provenance.entry_for(actor, "sprites/old.png") is None
        assert provenance.entry_for(actor, "sprites/new.png")["source"] == "uploaded"

    def test_remove_drops_entry(self, actor):
        provenance.record_uploaded(actor, "sprites/u.png")
        provenance.remove_asset(actor, "sprites/u.png")
        assert provenance.entry_for(actor, "sprites/u.png") is None

    def test_survives_reload(self, actor):
        provenance.record_generated(actor, "sprites/a.png", _Prov())
        # Simulate a restart: a fresh load reads the same file back.
        assert provenance.entry_for(actor, "sprites/a.png")["provider"] == "openai"

    def test_corrupt_file_tolerated(self, actor):
        provenance.path_for(actor).write_text("{ broken")
        # A corrupt provenance file reads as empty rather than raising.
        assert provenance.load(actor)["assets"] == {}
