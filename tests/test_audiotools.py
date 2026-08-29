"""Characterize lossless audio trimming (audiotools.py)."""

from __future__ import annotations

import pytest

import media
from audiotools import TrimError, trim


class TestTrimValidation:
    def test_negative_start_rejected(self, wav_bytes):
        with pytest.raises(TrimError):
            trim(wav_bytes, -1, 100)

    def test_end_before_start_rejected(self, wav_bytes):
        with pytest.raises(TrimError):
            trim(wav_bytes, 200, 100)

    def test_unknown_format_rejected(self):
        with pytest.raises(TrimError):
            trim(b"not audio", 0, 100)


class TestTrimWav:
    def test_trim_shortens_duration(self, wav_bytes):
        original = media.inspect_wav(wav_bytes)[0]
        cut = trim(wav_bytes, 0, 400)
        trimmed = media.inspect_wav(cut)[0]
        assert trimmed < original
        assert 380 <= trimmed <= 420

    def test_trimmed_is_valid_wav(self, wav_bytes):
        cut = trim(wav_bytes, 100, 500)
        # Still inspects cleanly and keeps format params.
        _, rate, channels = media.inspect_wav(cut)
        assert rate == 44100
        assert channels == 1

    def test_start_past_end_rejected(self, wav_bytes):
        with pytest.raises(TrimError):
            trim(wav_bytes, 5000, 6000)

    def test_end_clamped_to_length(self, wav_bytes):
        # Requesting past the end clamps rather than raising.
        cut = trim(wav_bytes, 0, 100000)
        assert media.inspect_wav(cut)[0] <= media.inspect_wav(wav_bytes)[0] + 1
