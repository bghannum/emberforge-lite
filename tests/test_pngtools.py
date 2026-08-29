"""Characterize PNG decode/fit/encode (pngtools.py)."""

from __future__ import annotations

import pytest

import media
import pngtools
from pngtools import PngUnsupported, decode_rgba, fit_png


class TestDecode:
    def test_decode_rgba_shape(self, png_bytes):
        w, h, rgba = decode_rgba(png_bytes)
        assert (w, h) == (64, 64)
        assert len(rgba) == 64 * 64 * 4

    def test_animated_rejected(self, gif_bytes):
        with pytest.raises((PngUnsupported, media.Rejected)):
            decode_rgba(gif_bytes)


class TestFit:
    def test_fit_produces_canvas_png(self, png_bytes):
        out, plan = fit_png(png_bytes)
        w, h, frames = media.inspect_png(out)
        assert (w, h, frames) == (
            pngtools.DEFAULT_CANVAS,
            pngtools.DEFAULT_CANVAS,
            1,
        )

    def test_plan_records_geometry(self, png_bytes):
        _, plan = fit_png(png_bytes)
        assert plan["canvas"] == [pngtools.DEFAULT_CANVAS, pngtools.DEFAULT_CANVAS]
        assert plan["resampling"] == "nearest"
        assert plan["source_size"] == [64, 64]

    def test_fit_is_submittable_to_256_cap(self, png_bytes):
        out, _ = fit_png(png_bytes)
        w, h, _ = media.inspect_png(out)
        assert max(w, h) <= 256

    def test_custom_canvas_and_margin(self, png_bytes):
        out, plan = fit_png(png_bytes, canvas=128, margin=8)
        assert plan["canvas"] == [128, 128]
        assert media.inspect_png(out)[0] == 128
