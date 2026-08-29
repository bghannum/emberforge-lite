"""Characterize estimates, the ledger, and offline generation (generate.py).

All runs use the deterministic fake providers (allow_spend=False), so no
network or credentials are touched.
"""

from __future__ import annotations

import pytest

import build
import generate
from pngtools import fit_png
from providers.fakes import _png


@pytest.fixture
def gen_env(tmp_path, monkeypatch):
    """Point generate + build at a throwaway data dir and load the fakes."""
    # build.render_actor computes media URLs relative to ROOT, so actors must
    # live under ROOT exactly as they do in the real layout (ROOT/actors).
    site = tmp_path / "site"
    site.mkdir()
    actors = site / "actors"
    actors.mkdir()
    monkeypatch.setattr(generate, "ACTORS_DIR", actors)
    monkeypatch.setattr(build, "ACTORS_DIR", actors)
    monkeypatch.setattr(build, "ROOT", site)
    monkeypatch.setattr(build, "OUTPUT", site / "gallery.html")
    generate.configure(allow_spend=False)
    # Reset generate's per-process caches between tests.
    generate._fit_cache.clear()
    return actors


def _make_actor(actors, slug="hero"):
    d = actors / slug
    (d / "sprites").mkdir(parents=True)
    return d


def _add_sprite(actor_dir, name="base.png"):
    # A fitted 256px still that estimate/prepare will accept.
    fitted, _ = fit_png(_png(64, 64, b"sprite"))
    (actor_dir / "sprites" / name).write_bytes(fitted)
    return name


class TestEstimateSound:
    def test_shape(self, gen_env):
        _make_actor(gen_env)
        est = generate.estimate("hero", "sound", {"prompt": "whoosh", "duration_ms": 800})
        assert est["kind"] == "sound"
        assert est["provider"] == "elevenlabs"
        assert est["unit"] == "elevenlabs_credits"
        assert est["output_name"].endswith(".mp3")
        assert est["live"] is False
        # amount is a normalized decimal string
        float(est["amount"])

    def test_missing_prompt_rejected(self, gen_env):
        _make_actor(gen_env)
        with pytest.raises(generate.GenerateError):
            generate.estimate("hero", "sound", {"prompt": ""})


class TestEstimateSource:
    def test_openai_usd(self, gen_env):
        _make_actor(gen_env)
        est = generate.estimate("hero", "source", {"prompt": "a knight", "provider": "openai"})
        assert est["unit"] == "usd"
        assert est["display"].startswith("$")


class TestEstimateAnimation:
    def test_requires_existing_sprite(self, gen_env):
        _make_actor(gen_env)
        with pytest.raises(generate.GenerateError):
            generate.estimate("hero", "animation", {"prompt": "lunge", "sprite": "missing.png", "action": "lunge"})

    def test_includes_plan(self, gen_env):
        actor = _make_actor(gen_env)
        sprite = _add_sprite(actor)
        est = generate.estimate("hero", "animation", {"prompt": "lunge", "sprite": sprite, "action": "lunge_attack"})
        assert est["unit"] == "spritelab_credits"
        assert est["submitted_size"] == [256, 256]
        assert est["output_name"] == "hero_lunge_attack_preview.gif"


class TestConfirmation:
    def test_mismatch_raises_409(self, gen_env):
        _make_actor(gen_env)
        est = generate.estimate("hero", "sound", {"prompt": "hum", "duration_ms": 800})
        with pytest.raises(generate.GenerateError) as exc:
            generate.check_confirmation(est, "999999")
        assert exc.value.status == 409

    def test_match_passes(self, gen_env):
        _make_actor(gen_env)
        est = generate.estimate("hero", "sound", {"prompt": "hum", "duration_ms": 800})
        generate.check_confirmation(est, est["amount"])  # no raise


class TestRunSyncSound:
    def test_writes_file_and_ledger(self, gen_env):
        _make_actor(gen_env)
        params = {"prompt": "hum", "duration_ms": 800, "name": "hum"}
        est = generate.estimate("hero", "sound", params)
        result = generate.run_sync("hero", "sound", params, est["amount"])
        assert result["filename"].endswith(".mp3") or result["filename"].endswith(".wav")
        # sound file landed on disk
        sounds = list((gen_env / "hero" / "sounds").iterdir())
        assert len(sounds) == 1
        # ledger has submitted + succeeded
        events = [r["event"] for r in generate.read_ledger("hero")]
        assert "submitted" in events
        assert "succeeded" in events


class TestLedger:
    def test_empty_when_absent(self, gen_env):
        _make_actor(gen_env)
        assert generate.read_ledger("hero") == []

    def test_append_and_read_roundtrip(self, gen_env):
        _make_actor(gen_env)
        generate._append("hero", {"event": "submitted", "job_id": "j1", "kind": "animation"})
        records = generate.read_ledger("hero")
        assert records[-1]["job_id"] == "j1"

    def test_malformed_line_skipped(self, gen_env):
        actor = _make_actor(gen_env)
        ledger = actor / generate.LEDGER_NAME
        ledger.write_text('{"event": "submitted", "job_id": "ok"}\n{ broken json\n')
        records = generate.read_ledger("hero")
        assert len(records) == 1
        assert records[0]["job_id"] == "ok"

    def test_open_jobs_excludes_terminal(self, gen_env):
        _make_actor(gen_env)
        generate._append("hero", {"id": "a", "event": "submitted", "kind": "animation", "job_id": "j1",
                                  "ts": "2026-08-29T00:00:00+00:00", "settings": {"action": "lunge"}})
        assert len(generate.open_jobs("hero")) == 1
        generate._append("hero", {"id": "a", "event": "succeeded", "kind": "animation", "job_id": "j1",
                                  "ts": "2026-08-29T00:00:01+00:00", "settings": {"action": "lunge"}})
        assert generate.open_jobs("hero") == []


class TestAnimationJob:
    def test_submit_then_advance_to_success(self, gen_env):
        actor = _make_actor(gen_env)
        sprite = _add_sprite(actor)
        params = {"prompt": "lunge", "sprite": sprite, "action": "lunge_attack", "frames": 8}
        est = generate.estimate("hero", "animation", params)
        submitted = generate.submit_animation("hero", params, est["amount"])
        assert submitted["state"] == "queued"
        job_id = submitted["job_id"]
        # Poll until terminal.
        last = None
        for _ in range(6):
            last = generate.advance_job("hero", job_id)
            if last["state"] != "running":
                break
        assert last["state"] == "succeeded"
        assert "gif" in last["outputs"]
        assert (actor / "animations").exists()


class TestProviderStatus:
    def test_offline_status(self, gen_env):
        status = generate.provider_status()
        assert status["allow_spend"] is False
        assert set(status["providers"]) == {"spritelab", "openai", "elevenlabs"}
