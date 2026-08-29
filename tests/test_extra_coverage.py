"""A few remaining branches: demo fallback, estimate balance, fit cache."""

from __future__ import annotations

from emberforge_lite import build, demo, generate
from emberforge_lite.pngtools import fit_png
from emberforge_lite.providers.fakes import _png


def test_demo_install_fallback_synthesizes(tmp_path, monkeypatch):
    # When the packaged demo_assets are absent, run installs by synthesizing.
    monkeypatch.setattr(demo, "DEMO_ASSETS", tmp_path / "missing")
    actors = tmp_path / "actors"
    actors.mkdir()
    demo._install_demo_actor(actors)
    assert (actors / demo.DEMO_SLUG / "sprites").is_dir()


class TestEstimateExtras:
    def _env(self, tmp_path, monkeypatch):
        site = tmp_path / "site"
        actors = site / "actors"
        (actors / "hero" / "sprites").mkdir(parents=True)
        (actors / "hero" / "sprites" / "base.png").write_bytes(fit_png(_png(64, 64, b"s"))[0])
        monkeypatch.setattr(generate, "ACTORS_DIR", actors)
        monkeypatch.setattr(build, "ACTORS_DIR", actors)
        monkeypatch.setattr(build, "ROOT", site)
        monkeypatch.setattr(build, "OUTPUT", site / "gallery.html")
        generate.configure(allow_spend=False)
        generate._fit_cache.clear()
        return actors

    def test_animation_estimate_includes_balance(self, tmp_path, monkeypatch):
        self._env(tmp_path, monkeypatch)
        est = generate.estimate("hero", "animation", {"prompt": "lunge", "sprite": "base.png", "action": "lunge"})
        # FakeSpriteLab exposes credits(), so the estimate carries a balance.
        assert est["balance"] is not None
        assert "balance" in est["display"]

    def test_fitted_source_cache_hit(self, tmp_path, monkeypatch):
        actors = self._env(tmp_path, monkeypatch)
        d = actors / "hero"
        a = generate.fitted_source(d, "base.png")
        b = generate.fitted_source(d, "base.png")  # cache hit path
        assert a is b
