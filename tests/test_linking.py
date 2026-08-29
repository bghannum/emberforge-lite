"""Characterize sound<->animation link bookkeeping (linking.py)."""

from __future__ import annotations

import json

import pytest

from emberforge_lite.linking import (
    add_link,
    remove_animation,
    remove_link,
    remove_sound,
    rename_animation,
    rename_sound,
)


@pytest.fixture
def actor(tmp_path):
    """An actor dir with one animation and two sounds on disk."""
    slug = "hero"
    d = tmp_path / slug
    (d / "animations").mkdir(parents=True)
    (d / "sounds").mkdir(parents=True)
    (d / "animations" / "idle.gif").write_bytes(b"g")
    (d / "sounds" / "hum.mp3").write_bytes(b"a")
    (d / "sounds" / "buzz.mp3").write_bytes(b"a")
    return tmp_path, slug


def links_of(actors_dir, slug):
    f = actors_dir / slug / "links.json"
    return json.loads(f.read_text()) if f.is_file() else {}


class TestAddLink:
    def test_creates_links_file(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        assert links_of(actors_dir, slug) == {"idle.gif": ["hum.mp3"]}

    def test_is_idempotent(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        assert links_of(actors_dir, slug) == {"idle.gif": ["hum.mp3"]}

    def test_appends_second_sound(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        add_link(actors_dir, slug, "idle.gif", "buzz.mp3")
        assert links_of(actors_dir, slug) == {"idle.gif": ["hum.mp3", "buzz.mp3"]}

    def test_missing_animation_raises(self, actor):
        actors_dir, slug = actor
        with pytest.raises(FileNotFoundError):
            add_link(actors_dir, slug, "nope.gif", "hum.mp3")

    def test_missing_sound_raises(self, actor):
        actors_dir, slug = actor
        with pytest.raises(FileNotFoundError):
            add_link(actors_dir, slug, "idle.gif", "nope.mp3")


class TestRemoveLink:
    def test_removes_and_prunes_empty_key(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        assert remove_link(actors_dir, slug, "idle.gif", "hum.mp3") is True
        assert links_of(actors_dir, slug) == {}

    def test_returns_false_when_absent(self, actor):
        actors_dir, slug = actor
        assert remove_link(actors_dir, slug, "idle.gif", "hum.mp3") is False


class TestRemoveAnimationAndSound:
    def test_remove_animation_drops_key(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        remove_animation(actors_dir, slug, "idle.gif")
        assert links_of(actors_dir, slug) == {}

    def test_remove_sound_prunes_everywhere(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        add_link(actors_dir, slug, "idle.gif", "buzz.mp3")
        remove_sound(actors_dir, slug, "hum.mp3")
        assert links_of(actors_dir, slug) == {"idle.gif": ["buzz.mp3"]}


class TestRename:
    def test_rename_animation_moves_key(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        rename_animation(actors_dir, slug, "idle.gif", "wait.gif")
        assert links_of(actors_dir, slug) == {"wait.gif": ["hum.mp3"]}

    def test_rename_sound_updates_values(self, actor):
        actors_dir, slug = actor
        add_link(actors_dir, slug, "idle.gif", "hum.mp3")
        rename_sound(actors_dir, slug, "hum.mp3", "drone.mp3")
        assert links_of(actors_dir, slug) == {"idle.gif": ["drone.mp3"]}
