"""Data-directory resolution and layout (config.py)."""

from __future__ import annotations

from pathlib import Path

from emberforge_lite import config
from emberforge_lite.config import Paths, paths_for, resolve_data_dir


class TestResolveDataDir:
    def test_explicit_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMBERFORGE_DATA_DIR", str(tmp_path / "env"))
        assert resolve_data_dir(tmp_path / "explicit") == (tmp_path / "explicit").resolve()

    def test_env_var_second(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMBERFORGE_DATA_DIR", str(tmp_path / "env"))
        assert resolve_data_dir(None) == (tmp_path / "env").resolve()

    def test_platform_default_last(self, monkeypatch):
        monkeypatch.delenv("EMBERFORGE_DATA_DIR", raising=False)
        default = resolve_data_dir(None)
        assert default == config.platform_default_data_dir()
        assert default.name == "emberforge-lite"


class TestPlatformDefault:
    def test_macos(self, monkeypatch):
        monkeypatch.setattr(config.sys, "platform", "darwin")
        d = config.platform_default_data_dir()
        assert d == Path.home() / "Library" / "Application Support" / "emberforge-lite"

    def test_linux_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert config.platform_default_data_dir() == tmp_path / "xdg" / "emberforge-lite"

    def test_linux_no_xdg(self, monkeypatch):
        monkeypatch.setattr(config.sys, "platform", "linux")
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        assert config.platform_default_data_dir() == Path.home() / ".local" / "share" / "emberforge-lite"


class TestPaths:
    def test_layout(self, tmp_path):
        p = Paths(tmp_path)
        assert p.actors == tmp_path / "actors"
        assert p.site == tmp_path / "site"
        assert p.tmp == tmp_path / "tmp"

    def test_ensure_creates(self, tmp_path):
        p = paths_for(tmp_path / "data").ensure()
        assert p.actors.is_dir()
        assert p.site.is_dir()
        assert p.tmp.is_dir()
