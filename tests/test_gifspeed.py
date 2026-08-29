"""Characterize GIF delay rewriting (gifspeed.py)."""

from __future__ import annotations

import gifspeed
from gifspeed import gce_delays, set_fps, slow_gif


class TestGceDelays:
    def test_reads_delays(self, gif_bytes):
        assert gce_delays(gif_bytes) == [6, 8]

    def test_non_gif_returns_empty(self):
        assert gce_delays(b"not a gif") == []


class TestSlowGif:
    def test_factor_one_is_identity(self, slow_gif_bytes):
        assert slow_gif(slow_gif_bytes, 1) == slow_gif_bytes

    def test_factor_is_a_speed_multiplier(self, slow_gif_bytes):
        # delay = effective / factor: factor < 1 slows down (longer delays).
        out = slow_gif(slow_gif_bytes, 0.5)
        assert gce_delays(out) == [100, 100, 100, 100]

    def test_factor_above_one_speeds_up(self, slow_gif_bytes):
        out = slow_gif(slow_gif_bytes, 2.0)
        assert gce_delays(out) == [25, 25, 25, 25]

    def test_factor_clamped_to_max(self, slow_gif_bytes):
        # factor above MAX_FACTOR (4.0) is clamped: 50/4 -> round(12.5) == 12.
        out = slow_gif(slow_gif_bytes, 1000.0)
        assert gce_delays(out) == [12, 12, 12, 12]

    def test_non_gif_returned_unchanged(self):
        assert slow_gif(b"not a gif", 2.0) == b"not a gif"


class TestSetFps:
    def test_normalizes_to_native(self, gif_bytes):
        # gif_bytes median delay is 7cs (~14fps); set_fps(8) slows it toward 12.5cs.
        out = set_fps(gif_bytes, gifspeed.NATIVE_FPS)
        assert out != gif_bytes
        delays = gce_delays(out)
        assert max(delays) > 8

    def test_empty_delays_returns_input(self):
        assert set_fps(b"not a gif") == b"not a gif"
