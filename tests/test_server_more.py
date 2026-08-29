"""Further server happy-path branches (sheets, source gen, sniff, jobs)."""

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


def _jpeg(width=8, height=8) -> bytes:
    # Minimal JPEG magic is enough for the server's sniff check.
    return b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    hero = r / "actors" / "hero"
    for sub in ("sprites", "animations", "sounds", "sheets"):
        (hero / sub).mkdir(parents=True)
    (hero / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
    # An animation with a paired spritesheet, so delete/rename touch the sheet.
    (hero / "animations" / "act_preview.gif").write_bytes(FAKE_PREVIEW_GIF)
    (hero / "sheets" / "act_sheet.png").write_bytes(_png(128, 32, b"sheet"))
    (hero / "sounds" / "hum.wav").write_bytes(_wav(800, b"h"))
    return r


def call(port, method, path, payload=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": server.CSRF_TOKEN}
    body = raw
    if payload is not None:
        body = json.dumps(payload).encode()
        h["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=h)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    parsed = json.loads(data) if data and resp.getheader("Content-Type", "").startswith("application/json") else data
    return resp.status, parsed


class TestSheets:
    def test_delete_animation_removes_sheet(self, root):
        with running_server(root) as port:
            status, _ = call(port, "DELETE", "/asset/hero/act_preview.gif")
            assert status == 200
            assert not (root / "actors" / "hero" / "sheets" / "act_sheet.png").exists()

    def test_rename_animation_moves_sheet(self, root):
        with running_server(root) as port:
            status, _ = call(
                port, "POST", "/rename", {"slug": "hero", "filename": "act_preview.gif", "new_name": "wait_preview.gif"}
            )
            assert status == 200
            assert (root / "actors" / "hero" / "sheets" / "wait_sheet.png").is_file()


class TestUploadSniff:
    def test_jpeg_upload_via_sniff(self, root):
        with running_server(root) as port:
            status, _ = call(port, "PUT", "/upload/hero/pic.jpg", raw=_jpeg())
            assert status == 200
            assert (root / "actors" / "hero" / "sprites" / "pic.jpg").is_file()

    def test_bad_jpeg_rejected(self, root):
        with running_server(root) as port:
            status, _ = call(port, "PUT", "/upload/hero/pic.jpg", raw=b"not a jpeg")
            assert status == 400


class TestTrimWithLink:
    def test_trim_links_to_animation(self, root):
        with running_server(root) as port:
            status, body = call(
                port,
                "POST",
                "/trim",
                {"slug": "hero", "sound": "hum.wav", "start_ms": 0, "end_ms": 400, "link_to": "act_preview.gif"},
            )
            assert status == 200
            assert body["linked"] is True


class TestSourceGeneration:
    def test_source_end_to_end(self, root):
        with running_server(root) as port:
            _, est = call(
                port,
                "POST",
                "/estimate",
                {"slug": "hero", "kind": "source", "prompt": "a knight", "provider": "openai"},
            )
            status, body = call(
                port,
                "POST",
                "/generate/source",
                {"slug": "hero", "prompt": "a knight", "provider": "openai", "confirm_amount": est["amount"]},
            )
            assert status == 200
            assert body["filename"].endswith(".png")


class TestJobsListing:
    def test_open_job_listed_then_cached(self, root):
        with running_server(root) as port:
            _, est = call(
                port,
                "POST",
                "/estimate",
                {"slug": "hero", "kind": "animation", "prompt": "lunge", "sprite": "base.png", "action": "lunge"},
            )
            _, sub = call(
                port,
                "POST",
                "/generate/animation",
                {
                    "slug": "hero",
                    "prompt": "lunge",
                    "sprite": "base.png",
                    "action": "lunge",
                    "confirm_amount": est["amount"],
                },
            )
            job_id = sub["job_id"]
            # It is open until advanced.
            _, jobs = call(port, "GET", "/jobs/hero")
            assert any(j["job_id"] == job_id for j in jobs["open"])
            # Drive to terminal, then a repeat advance returns the cached result.
            for _ in range(6):
                _, last = call(port, "GET", f"/job/hero/{job_id}")
                if last["state"] != "running":
                    break
            assert last["state"] == "succeeded"
            _, again = call(port, "GET", f"/job/hero/{job_id}")
            assert again["state"] == "succeeded"


class TestServePageMissing:
    def test_missing_actor_page_404(self, root):
        with running_server(root) as port:
            status, _ = call(port, "GET", "/actor-ghost.html")
            assert status == 404
