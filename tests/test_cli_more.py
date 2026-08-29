"""CLI command branches (cli.py) and a couple more adapter paths."""

from __future__ import annotations

import base64
import json

import pytest

from emberforge_lite import cli
from emberforge_lite.config import Paths
from emberforge_lite.demo import DEMO_SLUG, synthesize_demo_actor
from emberforge_lite.providers.base import GenerationRequest, ProviderRejected
from emberforge_lite.providers.fakes import _png, _tiny_gif
from emberforge_lite.providers.spritelab import SpriteLab
from emberforge_lite.providers.transport import Response


class TestCliMigrate:
    def test_migrate_success(self, tmp_path, capsys):
        src = tmp_path / "old"
        (src / "actors" / "knight" / "sprites").mkdir(parents=True)
        (src / "actors" / "knight" / "sprites" / "b.png").write_bytes(_png(32, 32, b"k"))
        rc = cli.main(["migrate", str(src), "--data-dir", str(tmp_path / "new")])
        assert rc == 0
        assert (tmp_path / "new" / "actors" / "knight" / "sprites" / "b.png").is_file()

    def test_migrate_missing_source(self, tmp_path, capsys):
        rc = cli.main(["migrate", str(tmp_path / "ghost"), "--data-dir", str(tmp_path / "new")])
        assert rc == 1
        assert "error" in capsys.readouterr().err

    def test_migrate_corrupt_media(self, tmp_path, capsys):
        src = tmp_path / "old"
        (src / "actors" / "k" / "sprites").mkdir(parents=True)
        (src / "actors" / "k" / "sprites" / "bad.png").write_bytes(b"not a png")
        rc = cli.main(["migrate", str(src), "--data-dir", str(tmp_path / "new")])
        assert rc == 1


class TestCliLink:
    def test_link_missing_animation(self, tmp_path, capsys):
        paths = Paths(tmp_path / "data").ensure()
        synthesize_demo_actor(paths.actors)
        rc = cli.main(["link", DEMO_SLUG, "nope.gif", "nope.wav", "--data-dir", str(paths.data_dir)])
        assert rc == 1
        assert "error" in capsys.readouterr().err


class TestSpriteLabMore:
    def _fit(self):
        return _png(64, 64, b"src")

    def test_preview_gif(self):
        submit = Response(200, json.dumps({"job_id": "j1"}).encode())
        with_gif = Response(
            200,
            json.dumps(
                {
                    "status": "succeeded",
                    "gif_b64": base64.b64encode(_tiny_gif((6, 8))).decode(),
                }
            ).encode(),
        )
        from tests.test_provider_contracts import FakeTransport

        p = SpriteLab(key="t", transport=FakeTransport(submit, with_gif))
        r = p.submit(GenerationRequest(stage="animation", prompt="x", source_png=self._fit(), frames=8))
        gif = p.preview_gif(r.job_id)
        assert gif[:6] in (b"GIF87a", b"GIF89a")

    def test_estimate_rejects_zero_batch(self):
        from tests.test_provider_contracts import FakeTransport

        p = SpriteLab(key="t", transport=FakeTransport())
        with pytest.raises(ProviderRejected):
            p.estimate(
                GenerationRequest(stage="animation", prompt="x", source_png=self._fit(), frames=8, candidate_count=0)
            )
