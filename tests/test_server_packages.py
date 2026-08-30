"""HTTP behaviour of frame packages: serving, timing edits, delete/rename/link."""

from __future__ import annotations

import http.client
import io
import json
import zipfile

import pytest

from emberforge_lite import animmeta, provenance, server
from emberforge_lite.animmeta import Frame, Manifest
from emberforge_lite.providers.fakes import _png, _wav
from tests.test_server_app import call, running_server


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type", ""), data


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "root"
    hero = root / "actors" / "hero"
    for sub in ("sprites", "animations", "sounds", "sheets"):
        (hero / sub).mkdir(parents=True)
    pkg = hero / "animations" / "walk"
    (pkg / "frames").mkdir(parents=True)
    for i in range(3):
        (pkg / "frames" / f"frame_{i:02d}.png").write_bytes(_png(4, 4, f"w{i}".encode()))
    animmeta.save_manifest(
        pkg,
        Manifest(
            name="walk",
            loop=True,
            frames=[Frame(f"frame_{i:02d}.png", 100) for i in range(3)],
            frame_size=(4, 4),
            source={"timing_source": "readme"},
        ),
    )
    (hero / "sheets" / "walk_sheet.png").write_bytes(_png(8, 8, b"sheet"))
    (hero / "sounds" / "hum.wav").write_bytes(_wav(800, b"h"))
    provenance.record_imported(hero, "animations/walk", library_path="lib/walk")
    provenance.record_imported(hero, "sheets/walk_sheet.png", library_path="lib/walk")
    # A stray non-package directory must not be served as one.
    (hero / "animations" / "notapkg" / "frames").mkdir(parents=True)
    (hero / "animations" / "notapkg" / "frames" / "frame_00.png").write_bytes(_png(4, 4, b"x"))
    return root


class TestServePackage:
    def test_manifest_and_frame(self, data_root):
        with running_server(data_root) as port:
            status, ctype, body = _get(port, "/actors/hero/animations/walk/manifest.json")
            assert status == 200 and ctype.startswith("application/json")
            doc = json.loads(body)
            assert doc["name"] == "walk" and len(doc["frames"]) == 3
            status, ctype, body = _get(port, "/actors/hero/animations/walk/frames/frame_01.png")
            assert status == 200 and ctype == "image/png"
            assert body == _png(4, 4, b"w1")

    @pytest.mark.parametrize(
        "path",
        [
            "/actors/hero/animations/walk/other.json",
            "/actors/hero/animations/walk/frames/frame_09.png",
            "/actors/hero/animations/walk/frames/manifest.json",
            "/actors/hero/animations/walk/nope/frame_00.png",
            "/actors/hero/animations/notapkg/frames/frame_00.png",
            "/actors/hero/animations/notapkg/manifest.json",
            "/actors/hero/animations/../hero/animations/walk/manifest.json",
            "/actors/hero/animations/walk/frames/..%2Fmanifest.json",
            "/actors/hero/sprites/walk/frames/frame_00.png",
            "/actors/hero/animations//manifest.json",
        ],
    )
    def test_not_found(self, data_root, path):
        with running_server(data_root) as port:
            status, _, _ = _get(port, path)
            assert status == 404

    def test_symlinked_frame_refused(self, data_root):
        secret = data_root / "secret.png"
        secret.write_bytes(_png(4, 4, b"s"))
        (data_root / "actors" / "hero" / "animations" / "walk" / "frames" / "frame_05.png").symlink_to(secret)
        with running_server(data_root) as port:
            status, _, _ = _get(port, "/actors/hero/animations/walk/frames/frame_05.png")
            assert status == 404

    def test_page_renders_package_card(self, data_root):
        with running_server(data_root) as port:
            status, _, body = _get(port, "/actor-hero.html")
            assert status == 200
            html = body.decode()
            assert 'data-manifest="actors/hero/animations/walk/manifest.json"' in html
            assert "badge-frames" in html
            assert "walk_sheet.png" in html


class TestTiming:
    def test_edit_persists(self, data_root):
        with running_server(data_root) as port:
            status, body = call(
                port, "POST", "/timing", {"slug": "hero", "animation": "walk", "delays": [10, 20, 30], "loop": False}
            )
            assert status == 200
            assert body["total_ms"] == 60
            m = animmeta.load_manifest(data_root / "actors" / "hero" / "animations" / "walk")
            assert m.delays() == [10, 20, 30]
            assert m.loop is False
            assert m.source["timing_source"] == "edited"

    @pytest.mark.parametrize(
        "payload",
        [
            {"slug": "hero", "animation": "walk", "delays": [10, 20]},
            {"slug": "hero", "animation": "walk", "delays": [10, 20, 0]},
            {"slug": "hero", "animation": "walk", "delays": "x"},
            {"slug": "hero", "animation": ""},
        ],
    )
    def test_bad_payload(self, data_root, payload):
        with running_server(data_root) as port:
            status, _ = call(port, "POST", "/timing", payload)
            assert status == 400

    def test_unknown_package(self, data_root):
        with running_server(data_root) as port:
            status, _ = call(port, "POST", "/timing", {"slug": "hero", "animation": "notapkg", "delays": [1]})
            assert status == 404

    def test_requires_csrf(self, data_root):
        with running_server(data_root) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/timing", body=b"{}", headers={"Content-Type": "application/json"})
            assert conn.getresponse().status == 403
            conn.close()


class TestMutations:
    def test_link_unlink_package(self, data_root):
        with running_server(data_root) as port:
            status, _ = call(port, "POST", "/link", {"slug": "hero", "animation": "walk", "sound": "hum.wav"})
            assert status == 200
            links = json.loads((data_root / "actors" / "hero" / "links.json").read_text())
            assert links == {"walk": ["hum.wav"]}
            status, _ = call(port, "POST", "/link", {"slug": "hero", "animation": "notapkg", "sound": "hum.wav"})
            assert status == 400

    def test_trim_links_to_package(self, data_root):
        with running_server(data_root) as port:
            status, body = call(
                port,
                "POST",
                "/trim",
                {"slug": "hero", "sound": "hum.wav", "start_ms": 0, "end_ms": 200, "link_to": "walk"},
            )
            assert status == 200 and body["linked"] is True

    def test_rename_package(self, data_root):
        hero = data_root / "actors" / "hero"
        with running_server(data_root) as port:
            call(port, "POST", "/link", {"slug": "hero", "animation": "walk", "sound": "hum.wav"})
            status, body = call(port, "POST", "/rename", {"slug": "hero", "filename": "walk", "new_name": "stroll.gif"})
            assert status == 200
            assert body["filename"] == "stroll-gif"
            new = hero / "animations" / "stroll-gif"
            assert animmeta.load_manifest(new).name == "stroll-gif"
            assert not (hero / "animations" / "walk").exists()
            assert (hero / "sheets" / "stroll-gif_sheet.png").is_file()
            assert not (hero / "sheets" / "walk_sheet.png").exists()
            assert json.loads((hero / "links.json").read_text()) == {"stroll-gif": ["hum.wav"]}
            assets = provenance.load(hero)["assets"]
            assert "animations/stroll-gif" in assets and "sheets/stroll-gif_sheet.png" in assets
            assert "animations/walk" not in assets

    def test_rename_package_conflict(self, data_root):
        with running_server(data_root) as port:
            status, _ = call(port, "POST", "/rename", {"slug": "hero", "filename": "walk", "new_name": "notapkg"})
            assert status == 409

    def test_delete_package(self, data_root):
        hero = data_root / "actors" / "hero"
        with running_server(data_root) as port:
            call(port, "POST", "/link", {"slug": "hero", "animation": "walk", "sound": "hum.wav"})
            status, body = call(port, "DELETE", "/asset/hero/walk")
            assert status == 200 and body["deleted"] == "walk"
            assert not (hero / "animations" / "walk").exists()
            assert not (hero / "sheets" / "walk_sheet.png").exists()
            assert json.loads((hero / "links.json").read_text()) == {}
            assert provenance.load(hero)["assets"] == {}
            status, _ = call(port, "DELETE", "/asset/hero/notapkg")
            assert status == 400

    def test_export_contains_manifest(self, data_root):
        with running_server(data_root) as port:
            status, _, body = _get(port, "/export/hero")
            assert status == 200
            names = zipfile.ZipFile(io.BytesIO(body)).namelist()
            assert "hero/animations/walk/manifest.json" in names
            assert "hero/animations/walk/frames/frame_00.png" in names

    def test_speed_route_still_gif_only(self, data_root):
        with running_server(data_root) as port:
            status, _, _ = _get(port, "/speed/hero/walk?factor=0.5")
            assert status == 400


def test_module_helpers(tmp_path):
    actor = tmp_path / "hero"
    (actor / "animations" / "pkg").mkdir(parents=True)
    (actor / "animations" / "pkg" / "manifest.json").write_text("{}")
    (actor / "sheets").mkdir()
    assert server._animation_exists(actor, "pkg")
    assert not server._animation_exists(actor, "missing")
    # No sheet: nothing to move, no error.
    server._rename_sheet(actor, "pkg", "other")
    (actor / "sheets" / "pkg_sheet.png").write_bytes(b"x")
    (actor / "sheets" / "other_sheet.png").write_bytes(b"y")
    server._rename_sheet(actor, "pkg", "other")  # target exists: left alone
    assert (actor / "sheets" / "pkg_sheet.png").is_file()
