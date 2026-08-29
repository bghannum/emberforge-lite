"""Milestone 3 reliability: resume, no double-submit, provenance, export."""

from __future__ import annotations

import http.client
import io
import threading
import zipfile
from contextlib import contextmanager

import pytest

from emberforge_lite import build, generate, provenance, server
from emberforge_lite.config import Paths
from emberforge_lite.pngtools import fit_png
from emberforge_lite.providers.fakes import _png


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


def _actor_with_sprite(actors, slug="hero"):
    d = actors / slug
    (d / "sprites").mkdir(parents=True)
    (d / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
    return d


class TestResumeAfterRestart:
    def test_open_animation_resumes(self, gen_env):
        _actor_with_sprite(gen_env)
        params = {"prompt": "lunge", "sprite": "base.png", "action": "lunge_attack", "frames": 8}
        est = generate.estimate("hero", "animation", params)
        submitted = generate.submit_animation("hero", params, est["amount"])
        job_id = submitted["job_id"]

        # Simulate a server restart: brand-new fake providers with no job memory.
        generate.configure(allow_spend=False)
        generate._job_locks.clear()

        last = None
        for _ in range(6):
            last = generate.advance_job("hero", job_id)
            if last["state"] != "running":
                break
        assert last["state"] == "succeeded"
        assert "gif" in last["outputs"]


class TestNoDoubleSubmit:
    def test_concurrent_confirmations_submit_once(self, gen_env):
        _actor_with_sprite(gen_env)
        params = {"prompt": "lunge", "sprite": "base.png", "action": "lunge_attack", "frames": 8}
        est = generate.estimate("hero", "animation", params)

        outcomes = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            try:
                outcomes.append(("ok", generate.submit_animation("hero", params, est["amount"])))
            except generate.GenerateError as e:
                outcomes.append(("err", e.status))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        submitted = [
            r for r in generate.read_ledger("hero") if r.get("event") == "submitted" and r.get("kind") == "animation"
        ]
        assert len(submitted) == 1, outcomes
        assert sum(1 for kind, _ in outcomes if kind == "err") == 1


class TestProvenanceRecorded:
    def test_sound_generation_records_provenance(self, gen_env):
        d = _actor_with_sprite(gen_env)
        params = {"prompt": "hum", "duration_ms": 800, "name": "hum"}
        est = generate.estimate("hero", "sound", params)
        result = generate.run_sync("hero", "sound", params, est["amount"])
        entry = provenance.entry_for(d, f"sounds/{result['filename']}")
        assert entry is not None
        assert entry["source"] == "generated"
        assert entry["provider"] == "elevenlabs"

    def test_animation_records_provenance(self, gen_env):
        d = _actor_with_sprite(gen_env)
        params = {"prompt": "lunge", "sprite": "base.png", "action": "lunge_attack", "frames": 8}
        est = generate.estimate("hero", "animation", params)
        job = generate.submit_animation("hero", params, est["amount"])
        last = None
        for _ in range(6):
            last = generate.advance_job("hero", job["job_id"])
            if last["state"] != "running":
                break
        gif = last["outputs"]["gif"]
        assert provenance.entry_for(d, f"animations/{gif}")["source"] == "generated"


class TestBadges:
    def test_generated_and_unknown_badges(self, gen_env, monkeypatch):
        d = _actor_with_sprite(gen_env)  # base.png has no provenance -> unknown
        params = {"prompt": "a hero", "provider": "openai"}
        est = generate.estimate("hero", "source", params)
        generate.run_sync("hero", "source", params, est["amount"])
        page = build.render_actor(d)
        assert "prov-generated" in page  # the generated source sprite
        assert "prov-unknown" in page  # base.png, no provenance


@contextmanager
def serving(paths: Paths):
    server.configure_paths(paths)
    build.configure_paths(paths)
    generate.configure_paths(paths)
    generate.configure(allow_spend=False)
    build.build()
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    server.configure_security(port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


class TestExportContents:
    def test_export_includes_provenance_and_ledger(self, tmp_path):
        paths = Paths(tmp_path / "data").ensure()
        actor = paths.actors / "hero"
        (actor / "sprites").mkdir(parents=True)
        (actor / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
        generate.configure_paths(paths)
        generate.configure(allow_spend=False)
        generate._fit_cache.clear()
        params = {"prompt": "a hero", "provider": "openai"}
        est = generate.estimate("hero", "source", params)
        generate.run_sync("hero", "source", params, est["amount"])
        assert provenance.path_for(actor).is_file()

        with serving(paths) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/export/hero")
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert "hero/provenance.json" in names
        assert "hero/generations.jsonl" in names
