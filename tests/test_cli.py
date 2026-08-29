"""End-to-end packaging behavior: split data-dir layout, demo, CLI (Milestone 2).

Verifies that with actors/ and site/ as siblings under one data directory, the
served pages still resolve their media through the /actors/ route.
"""

from __future__ import annotations

import http.client
import threading
from contextlib import contextmanager

from emberforge_lite import build, cli, generate, server
from emberforge_lite.config import Paths
from emberforge_lite.demo import DEMO_SLUG, synthesize_demo_actor


@contextmanager
def serving(paths: Paths):
    """Configure and start the server against a real split layout, in a thread."""
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


def get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, resp, data


class TestDemoSynthesis:
    def test_creates_valid_actor(self, tmp_path):
        actors = tmp_path / "actors"
        actors.mkdir()
        actor = synthesize_demo_actor(actors)
        assert actor.name == DEMO_SLUG
        assert list((actor / "sprites").iterdir())
        assert list((actor / "animations").iterdir())
        assert list((actor / "sounds").iterdir())
        assert (actor / "links.json").is_file()
        assert (actor / generate.LEDGER_NAME).is_file()


class TestSplitLayoutServing:
    def test_media_resolves_across_split(self, tmp_path):
        # actors/ and site/ are siblings; pages live in site/, media in actors/.
        paths = Paths(tmp_path / "data").ensure()
        actor = synthesize_demo_actor(paths.actors)
        with serving(paths) as port:
            # Pages are generated under site/, not next to actors/.
            assert (paths.site / "gallery.html").is_file()
            assert (paths.site / f"actor-{DEMO_SLUG}.html").is_file()
            assert not (paths.actors / "gallery.html").exists()

            # The actor page emits actors/<slug>/... URLs that the server serves.
            status, _, body = get(port, f"/actor-{DEMO_SLUG}.html")
            assert status == 200
            assert f"actors/{DEMO_SLUG}/".encode() in body

            sprite = next((actor / "sprites").iterdir()).name
            status, resp, _ = get(port, f"/actors/{DEMO_SLUG}/sprites/{sprite}")
            assert status == 200
            assert resp.getheader("Content-Type") == "image/png"


class TestCliBuild:
    def test_build_writes_site(self, tmp_path, capsys):
        data = tmp_path / "data"
        rc = cli.main(["build", "--data-dir", str(data)])
        assert rc == 0
        assert (data / "site" / "gallery.html").is_file()

    def test_link_command(self, tmp_path):
        paths = Paths(tmp_path / "data").ensure()
        synthesize_demo_actor(paths.actors)
        anim = f"{DEMO_SLUG.replace('-', '_')}_idle_preview.gif"
        sound = f"{DEMO_SLUG.replace('-', '_')}_chime.wav"
        rc = cli.main(["link", DEMO_SLUG, anim, sound, "--data-dir", str(paths.data_dir)])
        assert rc == 0
