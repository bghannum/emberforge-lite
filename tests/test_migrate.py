"""Validating, non-destructive migration (migrate.py)."""

from __future__ import annotations

import pytest

from emberforge_lite import media
from emberforge_lite.config import Paths
from emberforge_lite.migrate import MigrationError, migrate
from emberforge_lite.providers.fakes import _png, _wav


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "old"
    knight = src / "actors" / "knight"
    (knight / "sprites").mkdir(parents=True)
    (knight / "sounds").mkdir(parents=True)
    (knight / "sprites" / "base.png").write_bytes(_png(64, 64, b"k"))
    (knight / "sounds" / "hit.wav").write_bytes(_wav(500, b"h"))
    (knight / "links.json").write_text("{}")
    (knight / "generations.jsonl").write_text('{"event": "succeeded"}\n')
    # Things that must be excluded / left behind.
    (src / ".env").write_text("OPENAI_API_KEY=secret")
    (knight / "actor-knight.html").write_text("<html>generated</html>")
    return src


class TestMigrate:
    def test_copies_media_and_metadata(self, source, tmp_path):
        dest = Paths(tmp_path / "new")
        summary = migrate(source, dest)
        assert summary["actors"] == 1
        assert (dest.actors / "knight" / "sprites" / "base.png").is_file()
        assert (dest.actors / "knight" / "sounds" / "hit.wav").is_file()
        assert (dest.actors / "knight" / "links.json").is_file()
        assert (dest.actors / "knight" / "generations.jsonl").is_file()

    def test_excludes_generated_html(self, source, tmp_path):
        dest = Paths(tmp_path / "new")
        migrate(source, dest)
        assert not (dest.actors / "knight" / "actor-knight.html").exists()

    def test_leaves_source_untouched(self, source, tmp_path):
        dest = Paths(tmp_path / "new")
        migrate(source, dest)
        assert (source / ".env").is_file()
        assert (source / "actors" / "knight" / "sprites" / "base.png").is_file()

    def test_refuses_nonempty_destination(self, source, tmp_path):
        dest = Paths(tmp_path / "new").ensure()
        (dest.actors / "existing").mkdir()
        with pytest.raises(MigrationError):
            migrate(source, dest)

    def test_rejects_corrupt_media(self, source, tmp_path):
        (source / "actors" / "knight" / "sprites" / "bad.png").write_bytes(b"not a png")
        dest = Paths(tmp_path / "new")
        with pytest.raises(media.Rejected):
            migrate(source, dest)

    def test_missing_source(self, tmp_path):
        dest = Paths(tmp_path / "new")
        with pytest.raises(MigrationError):
            migrate(tmp_path / "does-not-exist", dest)
