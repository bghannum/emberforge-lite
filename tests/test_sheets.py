"""Spritesheet composition (sheets.py)."""

from __future__ import annotations

import pytest

from emberforge_lite import animmeta, media, pngtools, sheets
from emberforge_lite.animmeta import Frame, Manifest


def _solid(w, h, rgba):
    return pngtools.encode_rgba(w, h, bytearray(bytes(rgba) * (w * h)))


class TestGridShape:
    @pytest.mark.parametrize(
        "n,shape", [(1, (1, 1)), (4, (2, 2)), (12, (4, 3)), (16, (4, 4)), (20, (5, 4)), (28, (6, 5))]
    )
    def test_near_square(self, n, shape):
        assert sheets.grid_shape(n) == shape

    def test_shrinks_to_fit_width(self):
        # 6 cols of 1000px would be 6000 wide; 4 cols fit under 4096.
        assert sheets.grid_shape(28, cell_width=1000) == (4, 7)

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            sheets.grid_shape(0)


class TestCompose:
    def test_layout_and_pixels(self):
        frames = [_solid(2, 2, (255, 0, 0, 255)), _solid(2, 2, (0, 255, 0, 255)), _solid(2, 2, (0, 0, 255, 255))]
        png, layout = sheets.compose_sheet(frames)
        assert layout == {"cols": 2, "rows": 2, "cell": [2, 2], "frames": 3, "size": [4, 4]}
        w, h, rgba = pngtools.decode_rgba(png)
        assert (w, h) == (4, 4)

        def px(x, y):
            i = (y * w + x) * 4
            return tuple(rgba[i : i + 4])

        assert px(0, 0) == (255, 0, 0, 255)
        assert px(2, 0) == (0, 255, 0, 255)
        assert px(0, 2) == (0, 0, 255, 255)
        assert px(3, 3) == (0, 0, 0, 0)  # empty cell stays transparent

    def test_mismatched_sizes_rejected(self):
        with pytest.raises(media.Rejected):
            sheets.compose_sheet([_solid(2, 2, (0, 0, 0, 255)), _solid(3, 2, (0, 0, 0, 255))])

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            sheets.compose_sheet([])

    def test_oversize_rejected(self, monkeypatch):
        monkeypatch.setattr(media, "MAX_DIMENSION", 3)
        with pytest.raises(media.Rejected):
            sheets.compose_sheet([_solid(2, 2, (0, 0, 0, 255))] * 2)


class TestWriteSheet:
    def test_writes_named_sheet(self, tmp_path):
        anim = tmp_path / "animations" / "walk"
        (anim / "frames").mkdir(parents=True)
        for i in range(4):
            (anim / "frames" / f"frame_{i:02d}.png").write_bytes(_solid(2, 2, (i, i, i, 255)))
        animmeta.save_manifest(
            anim, Manifest(name="walk", loop=True, frames=[Frame(f"frame_{i:02d}.png", 100) for i in range(4)])
        )
        target, layout = sheets.write_sheet(anim, tmp_path / "sheets")
        assert target == tmp_path / "sheets" / "walk_sheet.png"
        assert target.is_file()
        assert layout["size"] == [4, 4]
        assert media.inspect_png(target.read_bytes())[:2] == (4, 4)
