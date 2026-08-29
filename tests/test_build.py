"""Characterize static HTML generation (build.py)."""

from __future__ import annotations

import pytest

import build
from providers.fakes import FAKE_PREVIEW_GIF, _png, _wav


@pytest.fixture
def build_env(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    actors = site / "actors"
    actors.mkdir()
    monkeypatch.setattr(build, "ROOT", site)
    monkeypatch.setattr(build, "ACTORS_DIR", actors)
    monkeypatch.setattr(build, "OUTPUT", site / "gallery.html")
    return site, actors


def _populate(actors, slug="gravescribe"):
    d = actors / slug
    (d / "sprites").mkdir(parents=True)
    (d / "animations").mkdir(parents=True)
    (d / "sounds").mkdir(parents=True)
    (d / "sprites" / "base.png").write_bytes(_png(64, 64, b"s"))
    (d / "animations" / "idle.gif").write_bytes(FAKE_PREVIEW_GIF)
    (d / "sounds" / "hum.wav").write_bytes(_wav(800, b"h"))
    return d


class TestBuild:
    def test_writes_gallery_and_actor_pages(self, build_env):
        site, actors = build_env
        _populate(actors)
        count = build.build()
        assert count == 1
        assert (site / "gallery.html").is_file()
        assert (site / "actor-gravescribe.html").is_file()

    def test_gallery_lists_actor(self, build_env):
        site, actors = build_env
        _populate(actors)
        build.build()
        gallery = (site / "gallery.html").read_text()
        assert "gravescribe" in gallery

    def test_stale_actor_page_removed(self, build_env):
        site, actors = build_env
        _populate(actors)
        build.build()
        # Remove the actor and rebuild: its page should be cleaned up.
        import shutil

        shutil.rmtree(actors / "gravescribe")
        build.build()
        assert not (site / "actor-gravescribe.html").exists()

    def test_empty_actors_builds_gallery_only(self, build_env):
        site, actors = build_env
        count = build.build()
        assert count == 0
        assert (site / "gallery.html").is_file()


class TestRenderHelpers:
    def test_asset_count(self, build_env):
        site, actors = build_env
        d = _populate(actors)
        assert build.asset_count(d) == 3

    def test_load_links_empty(self, build_env):
        site, actors = build_env
        d = _populate(actors)
        assert build.load_links(d) == {}
