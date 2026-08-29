"""Error mapping, live selection, and estimate branches (generate.py)."""

from __future__ import annotations

import pytest

from emberforge_lite import build, generate
from emberforge_lite.pngtools import fit_png
from emberforge_lite.providers.base import (
    AmbiguousOutcome,
    AuthenticationFailed,
    ProviderRejected,
    RateLimited,
)
from emberforge_lite.providers.fakes import FailureScript, _png


@pytest.fixture
def gen_env(tmp_path, monkeypatch):
    site = tmp_path / "site"
    actors = site / "actors"
    actors.mkdir(parents=True)
    monkeypatch.setattr(generate, "ACTORS_DIR", actors)
    monkeypatch.setattr(build, "ACTORS_DIR", actors)
    monkeypatch.setattr(build, "ROOT", site)
    monkeypatch.setattr(build, "OUTPUT", site / "gallery.html")
    generate.configure(allow_spend=False)
    generate._fit_cache.clear()
    return actors


def _actor(actors, slug="hero"):
    d = actors / slug
    (d / "sprites").mkdir(parents=True)
    (d / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
    return d


class TestErrorMapping:
    def test_auth_failed_maps_to_401(self):
        err = generate._from_provider_error(AuthenticationFailed("bad key"))
        assert err.status == 401

    def test_rate_limited_maps_to_429(self):
        err = generate._from_provider_error(RateLimited("slow down", retry_after_seconds=5))
        assert err.status == 429
        assert err.payload["retry_after"] == 5

    def test_ambiguous_maps_to_502(self):
        err = generate._from_provider_error(AmbiguousOutcome("unknown", job_id="j"))
        assert err.status == 502
        assert err.payload["ambiguous"] is True

    def test_rejected_maps_to_400(self):
        err = generate._from_provider_error(ProviderRejected("no"))
        assert err.status == 400


class TestSyncFailure:
    def test_failed_sound_records_and_raises(self, gen_env):
        _actor(gen_env)
        # Make the elevenlabs fake fail the job.
        generate.PROVIDERS["elevenlabs"].script = FailureScript(fail_job=True)
        params = {"prompt": "hum", "duration_ms": 800, "name": "hum"}
        est = generate.estimate("hero", "sound", params)
        with pytest.raises(generate.GenerateError):
            generate.run_sync("hero", "sound", params, est["amount"])
        events = [r["event"] for r in generate.read_ledger("hero")]
        assert "submitted" in events
        assert "failed" in events

    def test_rejected_source_maps(self, gen_env):
        _actor(gen_env)
        generate.PROVIDERS["spritelab_source_epic"].script = FailureScript(reject_reason="nope")
        params = {"prompt": "a knight", "provider": "spritelab_epic"}
        est = generate.estimate("hero", "source", params)
        with pytest.raises(generate.GenerateError):
            generate.run_sync("hero", "source", params, est["amount"])


class TestAnimationFailure:
    def test_failed_job_terminal(self, gen_env):
        _actor(gen_env)
        generate.PROVIDERS["spritelab_animate"].script = FailureScript(fail_job=True)
        params = {"prompt": "lunge", "sprite": "base.png", "action": "lunge", "frames": 8}
        est = generate.estimate("hero", "animation", params)
        job = generate.submit_animation("hero", params, est["amount"])
        last = None
        for _ in range(6):
            last = generate.advance_job("hero", job["job_id"])
            if last["state"] != "running":
                break
        assert last["state"] == "failed"

    def test_advance_unknown_job(self, gen_env):
        _actor(gen_env)
        with pytest.raises(generate.GenerateError):
            generate.advance_job("hero", "nosuchjob")


class TestLiveSelection:
    def test_live_adapters_selected_when_keys_present(self, monkeypatch):
        monkeypatch.setenv("SPRITELAB_API_KEY", "x")
        monkeypatch.setenv("OPENAI_API_KEY", "x")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
        providers = generate.select_providers(allow_spend=True)
        assert "spritelab_animate" in providers
        assert "openai" in providers
        assert "elevenlabs" in providers
        # Live provider status reports live=True.
        generate.configure(allow_spend=True)
        status = generate.provider_status()
        assert status["allow_spend"] is True
        assert status["providers"]["openai"]["live"] is True
        generate.configure(allow_spend=False)  # restore

    def test_no_keys_yields_no_live_adapters(self, monkeypatch):
        for k in ("SPRITELAB_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        assert generate.select_providers(allow_spend=True) == {}


class TestProviderUnavailable:
    def test_missing_provider_raises_403(self, gen_env, monkeypatch):
        _actor(gen_env)
        monkeypatch.setitem(generate.PROVIDERS, "openai", None)
        del generate.PROVIDERS["openai"]
        params = {"prompt": "a knight", "provider": "openai"}
        with pytest.raises(generate.GenerateError) as exc:
            generate.estimate("hero", "source", params)
        assert exc.value.status == 403
