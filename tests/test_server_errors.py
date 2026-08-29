"""Server error and edge branches (server.py), for coverage and contract."""

from __future__ import annotations

import http.client
import json
import threading
from contextlib import contextmanager

import pytest

from emberforge_lite import build, generate, server
from emberforge_lite.pngtools import fit_png
from emberforge_lite.providers.fakes import FAKE_PREVIEW_GIF, _png, _wav


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
def port(tmp_path):
    root = tmp_path / "root"
    hero = root / "actors" / "hero"
    for sub in ("sprites", "animations", "sounds"):
        (hero / sub).mkdir(parents=True)
    (hero / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
    (hero / "animations" / "idle.gif").write_bytes(FAKE_PREVIEW_GIF)
    (hero / "sounds" / "hum.wav").write_bytes(_wav(800, b"h"))
    with running_server(root) as p:
        yield p


def call(port, method, path, payload=None, raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": server.CSRF_TOKEN}
    if headers:
        h.update(headers)
    body = raw
    if payload is not None:
        body = json.dumps(payload).encode()
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


class TestGetErrors:
    def test_unknown_route(self, port):
        assert call(port, "GET", "/nope")[0] == 404

    def test_speed_not_gif(self, port):
        assert call(port, "GET", "/speed/hero/base.png")[0] == 400

    def test_speed_missing_animation(self, port):
        assert call(port, "GET", "/speed/hero/missing.gif")[0] == 404

    def test_export_unknown_actor(self, port):
        assert call(port, "GET", "/export/ghost")[0] == 404

    def test_job_unknown(self, port):
        assert call(port, "GET", "/job/hero/deadbeef")[0] == 404

    def test_favicon(self, port):
        assert call(port, "GET", "/favicon.ico")[0] == 204

    def test_jobs_empty(self, port):
        status, data = call(port, "GET", "/jobs/hero")
        assert status == 200
        assert json.loads(data)["open"] == []


class TestUploadErrors:
    def test_unsupported_extension(self, port):
        assert call(port, "PUT", "/upload/hero/x.txt", raw=b"hi")[0] == 400

    def test_empty_body(self, port):
        assert call(port, "PUT", "/upload/hero/x.png", raw=b"")[0] in (400, 411)

    def test_bad_route(self, port):
        assert call(port, "PUT", "/nope/hero/x.png", raw=b"data")[0] == 404


class TestDeleteErrors:
    def test_unknown_asset(self, port):
        assert call(port, "DELETE", "/asset/hero/ghost.png")[0] == 404

    def test_unsupported_extension(self, port):
        assert call(port, "DELETE", "/asset/hero/x.txt")[0] == 400

    def test_bad_route(self, port):
        assert call(port, "DELETE", "/nope/hero/x.png")[0] == 404


class TestPostErrors:
    def test_unknown_post(self, port):
        assert call(port, "POST", "/nope", {})[0] == 404

    def test_link_missing_files(self, port):
        assert call(port, "POST", "/link", {"slug": "hero", "animation": "no.gif", "sound": "no.wav"})[0] == 400

    def test_unlink_not_linked(self, port):
        assert call(port, "POST", "/unlink", {"slug": "hero", "animation": "idle.gif", "sound": "hum.wav"})[0] == 404

    def test_trim_missing_sound(self, port):
        assert call(port, "POST", "/trim", {"slug": "hero", "sound": "ghost.wav", "end_ms": 400})[0] == 404

    def test_trim_bad_range(self, port):
        assert (
            call(port, "POST", "/trim", {"slug": "hero", "sound": "hum.wav", "start_ms": 500, "end_ms": 100})[0] == 400
        )

    def test_rename_unknown(self, port):
        assert call(port, "POST", "/rename", {"slug": "hero", "filename": "ghost.png", "new_name": "x.png"})[0] == 404

    def test_rename_type_mismatch(self, port):
        assert call(port, "POST", "/rename", {"slug": "hero", "filename": "hum.wav", "new_name": "hum.png"})[0] == 400

    def test_rename_conflict(self, port):
        # Upload a second sprite, then rename base.png onto it.
        call(port, "PUT", "/upload/hero/other.png", raw=_png(32, 32, b"o"))
        assert (
            call(port, "POST", "/rename", {"slug": "hero", "filename": "base.png", "new_name": "other.png"})[0] == 409
        )

    def test_estimate_missing_prompt(self, port):
        assert call(port, "POST", "/estimate", {"slug": "hero", "kind": "sound"})[0] == 400

    def test_generate_bad_confirm(self, port):
        status, _ = call(
            port,
            "POST",
            "/generate/sound",
            {"slug": "hero", "prompt": "hum", "duration_ms": 800, "confirm_amount": "0.01"},
        )
        assert status == 409
