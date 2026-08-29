"""HTTP-level characterization of the app endpoints (server.py).

Complements test_server_security.py: these exercise the happy-path mutations
end to end through the handler, with a valid Origin + CSRF token, so the
packaging and web-layer refactors have a behavioral safety net.
"""

from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager

import pytest

from emberforge_lite import build, generate, provenance, server
from emberforge_lite.providers.fakes import _png, _wav


@contextmanager
def running_server(root):
    server.ROOT = root
    server.ACTORS_DIR = root / "actors"
    build.ROOT = root
    build.ACTORS_DIR = root / "actors"
    build.OUTPUT = root / "gallery.html"
    generate.ACTORS_DIR = root / "actors"
    generate.configure(allow_spend=False)
    generate._fit_cache.clear()

    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    port = httpd.server_address[1]
    server.configure_security(port)
    build.build()
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "root"
    hero = root / "actors" / "hero"
    for sub in ("sprites", "animations", "sounds"):
        (hero / sub).mkdir(parents=True)
    from emberforge_lite.pngtools import fit_png

    (hero / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
    (hero / "animations" / "idle.gif").write_bytes(server.slow_gif(_gif(), 1))
    (hero / "sounds" / "hum.wav").write_bytes(_wav(800, b"h"))
    return root


def _gif() -> bytes:
    from emberforge_lite.providers.fakes import FAKE_PREVIEW_GIF

    return FAKE_PREVIEW_GIF


def call(port, method, path, payload=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": server.CSRF_TOKEN}
    body = raw
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    parsed = json.loads(data) if data and resp.getheader("Content-Type", "").startswith("application/json") else data
    return resp.status, parsed


class TestLinkUnlink:
    def test_link_then_unlink(self, data_root):
        with running_server(data_root) as port:
            status, body = call(port, "POST", "/link", {"slug": "hero", "animation": "idle.gif", "sound": "hum.wav"})
            assert status == 200
            links = json.loads((data_root / "actors" / "hero" / "links.json").read_text())
            assert links == {"idle.gif": ["hum.wav"]}

            status, body = call(port, "POST", "/unlink", {"slug": "hero", "animation": "idle.gif", "sound": "hum.wav"})
            assert status == 200
            assert body["unlinked"] == "hum.wav"


class TestTrim:
    def test_trim_writes_new_sound(self, data_root):
        with running_server(data_root) as port:
            status, body = call(
                port, "POST", "/trim", {"slug": "hero", "sound": "hum.wav", "start_ms": 0, "end_ms": 400}
            )
            assert status == 200
            assert body["filename"].startswith("hum_0-400")
            assert (data_root / "actors" / "hero" / "sounds" / body["filename"]).is_file()


class TestRename:
    def test_rename_sound(self, data_root):
        with running_server(data_root) as port:
            status, body = call(
                port, "POST", "/rename", {"slug": "hero", "filename": "hum.wav", "new_name": "drone.wav"}
            )
            assert status == 200
            assert (data_root / "actors" / "hero" / "sounds" / "drone.wav").is_file()
            assert not (data_root / "actors" / "hero" / "sounds" / "hum.wav").exists()

    def test_rename_must_keep_type(self, data_root):
        with running_server(data_root) as port:
            status, _ = call(port, "POST", "/rename", {"slug": "hero", "filename": "hum.wav", "new_name": "drone.png"})
            assert status == 400


class TestDelete:
    def test_delete_sound(self, data_root):
        with running_server(data_root) as port:
            status, body = call(port, "DELETE", "/asset/hero/hum.wav")
            assert status == 200
            assert body["deleted"] == "hum.wav"
            assert not (data_root / "actors" / "hero" / "sounds" / "hum.wav").exists()


class TestEstimateAndGenerate:
    def test_estimate_sound(self, data_root):
        with running_server(data_root) as port:
            status, body = call(
                port, "POST", "/estimate", {"slug": "hero", "kind": "sound", "prompt": "hum", "duration_ms": 800}
            )
            assert status == 200
            assert body["unit"] == "elevenlabs_credits"

    def test_generate_sound_requires_confirm(self, data_root):
        with running_server(data_root) as port:
            status, _ = call(port, "POST", "/generate/sound", {"slug": "hero", "prompt": "hum", "duration_ms": 800})
            assert status == 400

    def test_generate_sound_end_to_end(self, data_root):
        with running_server(data_root) as port:
            _, est = call(
                port,
                "POST",
                "/estimate",
                {"slug": "hero", "kind": "sound", "prompt": "hum", "duration_ms": 800, "name": "hum"},
            )
            status, body = call(
                port,
                "POST",
                "/generate/sound",
                {"slug": "hero", "prompt": "hum", "duration_ms": 800, "name": "hum", "confirm_amount": est["amount"]},
            )
            assert status == 200
            assert body["filename"]

    def test_animation_job_flow(self, data_root):
        with running_server(data_root) as port:
            _, est = call(
                port,
                "POST",
                "/estimate",
                {
                    "slug": "hero",
                    "kind": "animation",
                    "prompt": "lunge",
                    "sprite": "base.png",
                    "action": "lunge_attack",
                },
            )
            status, submitted = call(
                port,
                "POST",
                "/generate/animation",
                {
                    "slug": "hero",
                    "prompt": "lunge",
                    "sprite": "base.png",
                    "action": "lunge_attack",
                    "confirm_amount": est["amount"],
                },
            )
            assert status == 202
            job_id = submitted["job_id"]
            last = None
            for _ in range(6):
                _, last = call(port, "GET", f"/job/hero/{job_id}")
                if last["state"] != "running":
                    break
            assert last["state"] == "succeeded"


class TestSpeedAndProviders:
    def test_speed_returns_gif(self, data_root):
        with running_server(data_root) as port:
            status, body = call(port, "GET", "/speed/hero/idle.gif?factor=0.5")
            assert status == 200
            assert body[:6] in (b"GIF87a", b"GIF89a")

    def test_providers_status(self, data_root):
        with running_server(data_root) as port:
            status, body = call(port, "GET", "/providers")
            assert status == 200
            assert body["allow_spend"] is False


class TestProvenanceThroughServer:
    def test_upload_records_uploaded_provenance(self, data_root):
        with running_server(data_root) as port:
            status, _ = call(port, "PUT", "/upload/hero/new.png", raw=_png(32, 32, b"u"))
            assert status == 200
            entry = provenance.entry_for(data_root / "actors" / "hero", "sprites/new.png")
            assert entry == {"source": "uploaded", "account_rights": None}

    def test_delete_removes_provenance(self, data_root):
        with running_server(data_root) as port:
            call(port, "PUT", "/upload/hero/gone.png", raw=_png(32, 32, b"u"))
            actor = data_root / "actors" / "hero"
            assert provenance.entry_for(actor, "sprites/gone.png") is not None
            status, _ = call(port, "DELETE", "/asset/hero/gone.png")
            assert status == 200
            assert provenance.entry_for(actor, "sprites/gone.png") is None

    def test_rename_moves_provenance(self, data_root):
        with running_server(data_root) as port:
            call(port, "PUT", "/upload/hero/orig.png", raw=_png(32, 32, b"u"))
            actor = data_root / "actors" / "hero"
            status, _ = call(
                port, "POST", "/rename", {"slug": "hero", "filename": "orig.png", "new_name": "renamed.png"}
            )
            assert status == 200
            assert provenance.entry_for(actor, "sprites/orig.png") is None
            assert provenance.entry_for(actor, "sprites/renamed.png")["source"] == "uploaded"
