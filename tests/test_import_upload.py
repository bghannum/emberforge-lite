"""Browser folder import: staging of uploaded paths, import_folder, POST /import."""

from __future__ import annotations

import http.client
import json
import uuid

import pytest

from emberforge_lite import animmeta, importer, server
from emberforge_lite.importer import ImportFailure, ImportSummary
from emberforge_lite.providers.fakes import _png
from tests.test_importer import README_TMPL, make_package
from tests.test_server_app import running_server


def _readme(delays):
    return README_TMPL.format(title="t", loop="No", fps="10.0", delays=", ".join(map(str, delays)), prose="")


def _files(prefix="hero_walk", frames=2, readme=True):
    out = [(f"{prefix}/frames/frame_{i:02d}.png", _png(4, 4, f"u{i}".encode())) for i in range(frames)]
    if readme:
        out.append((f"{prefix}/README.md", _readme([40 + i for i in range(frames)]).encode()))
    return out


class TestStage:
    def test_writes_only_wanted_files(self, tmp_path):
        files = _files() + [("hero_walk/.DS_Store", b"x"), ("hero_walk/tools/build.swift", b"y")]
        top = importer.stage_uploaded_files(files, tmp_path)
        assert top == tmp_path / "hero_walk"
        assert (top / "frames" / "frame_01.png").is_file()
        assert (top / "README.md").is_file()
        assert not (top / ".DS_Store").exists()
        assert not (top / "tools").exists()

    @pytest.mark.parametrize(
        "bad",
        [
            [("../x/frames/a.png", b"")],
            [("hero/frames/../../a.png", b"")],
            [("a/b/c/d/e.png", b"")],
            [("one/frames/a.png", b""), ("two/frames/a.png", b"")],
            [],
            [("hero/frames/a.txt", b"")],
        ],
    )
    def test_rejects(self, tmp_path, bad):
        with pytest.raises(ImportFailure):
            importer.stage_uploaded_files(bad, tmp_path)

    def test_limits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(importer, "MAX_UPLOAD_FILES", 1)
        with pytest.raises(ImportFailure):
            importer.stage_uploaded_files(_files(), tmp_path)
        monkeypatch.setattr(importer.media, "MAX_FILE_BYTES", 10)
        with pytest.raises(ImportFailure):
            importer.stage_uploaded_files(_files(frames=1, readme=False), tmp_path)


class TestImportFolder:
    def test_single_animation(self, tmp_path):
        folder = make_package(tmp_path / "lib" / "hero_walk", delays=[10, 20, 30])
        actor = tmp_path / "actors" / "hero"
        summary = ImportSummary()
        importer.import_folder(folder, actor, library_root=tmp_path / "lib", summary=summary)
        assert summary.animations == 1 and summary.actors == 0
        assert animmeta.load_manifest(actor / "animations" / "hero_walk").delays() == [10, 20, 30]

    def test_character_folder(self, tmp_path):
        char = tmp_path / "lib" / "Hero"
        make_package(char / "hero_walk")
        make_package(char / "hero_run (deprecated)")
        (char / "hero_idle_game.png").write_bytes(_png(4, 4, b"i"))
        actor = tmp_path / "actors" / "hero"
        summary = ImportSummary()
        importer.import_folder(char, actor, library_root=tmp_path / "lib", summary=summary)
        assert summary.animations == 1 and summary.sprites == 1
        assert (actor / "animations" / "hero_walk").is_dir()
        assert any("deprecated" in s for s in summary.skipped)
        summary = ImportSummary()
        importer.import_folder(char, actor, library_root=tmp_path / "lib", include_deprecated=True, summary=summary)
        assert (actor / "animations" / "hero_run").is_dir()

    def test_unrecognised(self, tmp_path):
        folder = tmp_path / "junk"
        folder.mkdir()
        (folder / "a.txt").write_text("x")
        with pytest.raises(ImportFailure):
            importer.import_folder(folder, tmp_path / "actors" / "hero", library_root=tmp_path, summary=ImportSummary())


def _multipart(files, fields=()):
    boundary = f"----efl{uuid.uuid4().hex}"
    body = b""
    for name, value in fields:
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    for rel, data in files:
        body += (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{rel}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + data
            + b"\r\n"
        )
    body += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", body


def _post_import(port, slug, files, fields=(), content_type=None, raw=None):
    ctype, body = _multipart(files, fields)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {
        "Origin": f"http://127.0.0.1:{port}",
        "X-CSRF-Token": server.CSRF_TOKEN,
        "Content-Type": content_type or ctype,
    }
    conn.request("POST", f"/import/{slug}", body=raw if raw is not None else body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, json.loads(data)


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "root"
    (root / "actors" / "hero" / "sprites").mkdir(parents=True)
    (root / "tmp").mkdir()
    server.TMP_DIR = root / "tmp"
    return root


class TestImportRoute:
    def test_imports_animation_folder(self, data_root):
        with running_server(data_root) as port:
            status, body = _post_import(port, "hero", _files())
            assert status == 200, body
            assert body["animations"] == 1 and body["frames"] == 2
            m = animmeta.load_manifest(data_root / "actors" / "hero" / "animations" / "hero_walk")
            assert m.delays() == [40, 41]
            assert m.source["library"] == "browser upload"
            assert (data_root / "actors" / "hero" / "sheets" / "hero_walk_sheet.png").is_file()
            assert not any(server.TMP_DIR.iterdir())  # staging cleaned up
            html = (data_root / "actor-hero.html").read_text()
            assert 'data-action="import-folder"' in html

    def test_character_folder_and_deprecated_flag(self, data_root):
        files = _files("Hero/hero_walk") + _files("Hero/hero_run (deprecated)")
        with running_server(data_root) as port:
            status, body = _post_import(port, "hero", files)
            assert status == 200 and body["animations"] == 1
            assert any("deprecated" in s for s in body["skipped"])
            status, body = _post_import(port, "hero", files, fields=[("include_deprecated", "1")])
            assert status == 200 and body["animations"] == 2

    def test_creates_new_actor(self, data_root):
        with running_server(data_root) as port:
            status, body = _post_import(port, "newbie", _files())
            assert status == 200
            assert (data_root / "actors" / "newbie" / "animations" / "hero_walk").is_dir()

    def test_rejections(self, data_root):
        with running_server(data_root) as port:
            status, body = _post_import(port, "hero", [("junk/notes.txt", b"x")])
            assert status == 400
            status, body = _post_import(port, "hero", [("../evil/frames/a.png", b"x")])
            assert status == 400
            status, body = _post_import(port, "hero", _files(), content_type="application/json")
            assert status == 400
            status, body = _post_import(port, "hero", _files(), content_type="multipart/form-data")
            assert status == 400
            status, body = _post_import(port, "hero", [], raw=b"")
            assert status == 400
            status, body = _post_import(
                port,
                "hero",
                _files(readme=False, frames=1),
                raw=b"garbage",
                content_type="multipart/form-data; boundary=zzz",
            )
            assert status == 400
            assert not any(server.TMP_DIR.iterdir())

    def test_bad_frame_reported_not_crashed(self, data_root):
        files = _files() + [("hero_walk/frames/frame_05.png", b"not a png")]
        with running_server(data_root) as port:
            status, body = _post_import(port, "hero", files)
            assert status == 200 and body["animations"] == 0
            assert any("rejected" in s for s in body["skipped"])

    def test_too_large_and_requires_csrf(self, data_root, monkeypatch):
        monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 100)
        with running_server(data_root) as port:
            status, _ = _post_import(port, "hero", _files())
            assert status == 413
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/import/hero", body=b"x", headers={"Content-Type": "text/plain"})
            assert conn.getresponse().status == 403
            conn.close()
            status, _ = _post_import(port, "", _files())
            assert status in (400, 404)
