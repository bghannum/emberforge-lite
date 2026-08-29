"""HTTP security tests for the server (server.py, Milestone 1).

These drive the security hardening: the server must serve only generated
pages and actor media, reject attempts to fetch credentials/source/ledgers,
require a same-origin request with a CSRF token on every mutation, and never
leave a partial file behind on a rejected upload.
"""

from __future__ import annotations

import http.client
import threading
from contextlib import contextmanager

import pytest

import build
import generate
import server
from providers.fakes import _png, _wav


@contextmanager
def running_server(root):
    """Start the real handler on an ephemeral port against `root`."""
    server.ROOT = root
    server.ACTORS_DIR = root / "actors"
    build.ROOT = root
    build.ACTORS_DIR = root / "actors"
    build.OUTPUT = root / "gallery.html"
    generate.ACTORS_DIR = root / "actors"
    generate.configure(allow_spend=False)

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
    (root / "actors" / "hero" / "sprites").mkdir(parents=True)
    (root / "actors" / "hero" / "animations").mkdir(parents=True)
    (root / "actors" / "hero" / "sounds").mkdir(parents=True)
    (root / "actors" / "hero" / "sprites" / "base.png").write_bytes(_png(64, 64, b"s"))
    (root / "actors" / "hero" / "sounds" / "hum.wav").write_bytes(_wav(800, b"h"))
    # Sensitive files a naive static server would expose.
    (root / ".env").write_text("OPENAI_API_KEY=sk-secret\n")
    (root / "server.py").write_text("# source\n")
    (root / "actors" / "hero" / "generations.jsonl").write_text('{"prompt": "secret"}\n')
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n")
    return root


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, resp, data


def mutating_headers(port, extra=None):
    h = {
        "Origin": f"http://127.0.0.1:{port}",
        "X-CSRF-Token": server.CSRF_TOKEN,
    }
    if extra:
        h.update(extra)
    return h


class TestServesLegitimate:
    def test_gallery_served(self, data_root):
        with running_server(data_root) as port:
            status, _, body = request(port, "GET", "/gallery.html")
            assert status == 200
            assert b"hero" in body

    def test_actor_page_served(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "GET", "/actor-hero.html")
            assert status == 200

    def test_actor_media_served(self, data_root):
        with running_server(data_root) as port:
            status, resp, _ = request(port, "GET", "/actors/hero/sprites/base.png")
            assert status == 200
            assert resp.getheader("Content-Type") == "image/png"

    def test_root_redirects_to_gallery(self, data_root):
        with running_server(data_root) as port:
            status, resp, _ = request(port, "GET", "/")
            assert status == 302
            assert resp.getheader("Location") == "/gallery.html"


class TestBlocksSensitive:
    @pytest.mark.parametrize(
        "path",
        [
            "/.env",
            "/server.py",
            "/generate.py",
            "/.git/config",
            "/actors/hero/generations.jsonl",
            "/actors/hero/links.json",
            "/pyproject.toml",
            "/credentials.py",
        ],
    )
    def test_sensitive_paths_404(self, data_root, path):
        with running_server(data_root) as port:
            status, _, _ = request(port, "GET", path)
            assert status == 404, f"{path} should be 404, got {status}"

    @pytest.mark.parametrize(
        "path",
        [
            "/../server.py",
            "/actors/../.env",
            "/actors/hero/../../.env",
            "/actors/hero/sprites/../../../.env",
        ],
    )
    def test_traversal_blocked(self, data_root, path):
        with running_server(data_root) as port:
            status, _, body = request(port, "GET", path)
            assert status in (400, 404)
            assert b"secret" not in body


class TestSecurityHeaders:
    def test_headers_present(self, data_root):
        with running_server(data_root) as port:
            _, resp, _ = request(port, "GET", "/gallery.html")
            assert resp.getheader("X-Content-Type-Options") == "nosniff"
            assert resp.getheader("X-Frame-Options") == "DENY"
            assert "Content-Security-Policy" in dict(resp.getheaders())
            assert resp.getheader("Referrer-Policy") == "no-referrer"


class TestHostHeader:
    def test_foreign_host_rejected(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "GET", "/gallery.html", headers={"Host": "evil.example.com"})
            assert status == 400


class TestCsrfAndOrigin:
    def test_rebuild_requires_csrf(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "POST", "/rebuild", body=b"{}",
                                   headers={"Origin": f"http://127.0.0.1:{port}"})
            assert status == 403

    def test_rebuild_rejects_foreign_origin(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "POST", "/rebuild", body=b"{}",
                                   headers={"Origin": "http://evil.example.com",
                                            "X-CSRF-Token": server.CSRF_TOKEN})
            assert status == 403

    def test_rebuild_rejects_missing_origin(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "POST", "/rebuild", body=b"{}",
                                   headers={"X-CSRF-Token": server.CSRF_TOKEN})
            assert status == 403

    def test_rebuild_allowed_with_token_and_origin(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "POST", "/rebuild", body=b"{}", headers=mutating_headers(port))
            assert status == 200

    def test_upload_requires_csrf(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "PUT", "/upload/hero/x.png", body=_png(32, 32, b"u"),
                                   headers={"Origin": f"http://127.0.0.1:{port}"})
            assert status == 403


class TestUploadValidation:
    def test_valid_png_upload(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "PUT", "/upload/hero/new.png", body=_png(32, 32, b"u"),
                                   headers=mutating_headers(port))
            assert status == 200
            assert (data_root / "actors" / "hero" / "sprites" / "new.png").is_file()

    def test_invalid_png_leaves_no_file(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = request(port, "PUT", "/upload/hero/bad.png", body=b"not a real png",
                                   headers=mutating_headers(port))
            assert status == 400
            sprites = list((data_root / "actors" / "hero" / "sprites").iterdir())
            assert [p.name for p in sprites] == ["base.png"]

    def test_oversized_upload_rejected(self, data_root, monkeypatch):
        monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 1024)
        with running_server(data_root) as port:
            big = _png(64, 64, b"big") + b"\x00" * 4096
            status, _, _ = request(port, "PUT", "/upload/hero/big.png", body=big,
                                   headers=mutating_headers(port))
            assert status == 413
            assert not (data_root / "actors" / "hero" / "sprites" / "big.png").exists()


class TestExport:
    def test_export_streams_zip(self, data_root):
        with running_server(data_root) as port:
            status, resp, body = request(port, "GET", "/export/hero")
            assert status == 200
            assert resp.getheader("Content-Type") == "application/zip"
            assert body[:2] == b"PK"
