"""Web-layer refactor (Milestone 4): no inline JS, strict CSP, static files."""

from __future__ import annotations

import http.client
import re
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from emberforge_lite import build, generate, server
from emberforge_lite.config import Paths
from emberforge_lite.demo import DEMO_SLUG, synthesize_demo_actor

STATIC = Path(server.__file__).parent / "static"


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


@pytest.fixture
def demo_port(tmp_path):
    paths = Paths(tmp_path / "data").ensure()
    synthesize_demo_actor(paths.actors)
    with serving(paths) as port:
        yield port


def get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp, body


class TestNoInlineJavaScript:
    def test_actor_page_has_no_inline_handlers(self, demo_port):
        _, body = get(demo_port, f"/actor-{DEMO_SLUG}.html")
        text = body.decode()
        assert not re.search(r"on(click|change|input|submit|load)\s*=", text)

    def test_actor_page_has_no_inline_script_or_style(self, demo_port):
        _, body = get(demo_port, f"/actor-{DEMO_SLUG}.html")
        text = body.decode()
        # Only external references, never inline blocks.
        assert '<script src="/static/app.js"' in text
        assert '<link rel="stylesheet" href="/static/app.css">' in text
        assert not re.search(r"<script>(?!\s*</script>).", text)
        assert "<style>" not in text

    def test_actor_page_uses_data_actions(self, demo_port):
        _, body = get(demo_port, f"/actor-{DEMO_SLUG}.html")
        assert b'data-action="delete"' in body
        assert b'data-action="play"' in body


class TestStrictCsp:
    def test_csp_has_no_unsafe_inline(self, demo_port):
        resp, _ = get(demo_port, f"/actor-{DEMO_SLUG}.html")
        csp = resp.getheader("Content-Security-Policy")
        assert "unsafe-inline" not in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp


class TestStaticFiles:
    def test_css_served(self, demo_port):
        resp, body = get(demo_port, "/static/app.css")
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/css; charset=utf-8"
        assert b".gen-tab" in body

    def test_js_served(self, demo_port):
        resp, body = get(demo_port, "/static/app.js")
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/javascript; charset=utf-8"
        assert b"addEventListener" in body

    def test_static_traversal_blocked(self, demo_port):
        resp, _ = get(demo_port, "/static/../server.py")
        assert resp.status in (400, 404)

    def test_unknown_static_404(self, demo_port):
        resp, _ = get(demo_port, "/static/nope.txt")
        assert resp.status == 404


class TestNoBrowserDialogs:
    def test_app_js_has_no_alert_confirm_prompt(self):
        js = (STATIC / "app.js").read_text()
        assert "alert(" not in js
        # confirm(/prompt( only as our modalConfirm/modalPrompt helpers.
        assert not re.search(r"(?<![a-zA-Z])confirm\(", js)
        assert not re.search(r"(?<![a-zA-Z])prompt\(", js)
        assert "modalConfirm(" in js
        assert "modalPrompt(" in js
