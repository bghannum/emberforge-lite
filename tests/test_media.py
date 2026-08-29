"""Characterize header-only media inspection and bounds (media.py)."""

from __future__ import annotations

import struct

import pytest

from emberforge_lite import media
from emberforge_lite.media import (
    Rejected,
    audio_kind,
    inspect_audio,
    inspect_gif,
    inspect_png,
    inspect_wav,
    png_has_alpha,
    resolve_within,
    sha256_bytes,
    validate,
    validate_source,
)
from emberforge_lite.providers.fakes import _png


class TestInspectPng:
    def test_still_png(self, png_bytes):
        assert inspect_png(png_bytes) == (64, 64, 1)

    def test_too_short(self):
        with pytest.raises(Rejected):
            inspect_png(b"\x89PNG\r\n\x1a\n")

    def test_dimension_over_limit(self):
        big = _png(1, 1, b"x")
        # Rewrite IHDR to claim an over-limit width.
        data = bytearray(big)
        struct.pack_into(">I", data, 16, media.MAX_DIMENSION + 1)
        with pytest.raises(Rejected):
            inspect_png(bytes(data))

    def test_alpha_detection_rgba(self, png_bytes):
        assert png_has_alpha(png_bytes) is True


class TestInspectGif:
    def test_two_frame_gif(self, gif_bytes):
        w, h, frames = inspect_gif(gif_bytes)
        assert (w, h, frames) == (2, 2, 2)

    def test_too_short(self):
        with pytest.raises(Rejected):
            inspect_gif(b"GIF89a")


class TestInspectAudio:
    def test_wav_duration(self, wav_bytes):
        duration, rate, channels = inspect_wav(wav_bytes)
        assert rate == 44100
        assert channels == 1
        assert 780 <= duration <= 820

    def test_audio_kind_wav(self, wav_bytes):
        assert audio_kind(wav_bytes) == "wav"

    def test_inspect_audio_dispatches(self, wav_bytes):
        assert inspect_audio(wav_bytes)[1] == 44100

    def test_non_audio_rejected(self):
        with pytest.raises(Rejected):
            audio_kind(b"not audio")


class TestValidate:
    def test_validate_png_summary(self, tmp_path, png_bytes):
        p = tmp_path / "s.png"
        p.write_bytes(png_bytes)
        summary = validate(p)
        assert summary.startswith("PNG 64x64")

    def test_validate_rejects_empty(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        with pytest.raises(Rejected):
            validate(p)

    def test_validate_rejects_symlink(self, tmp_path, png_bytes):
        real = tmp_path / "real.png"
        real.write_bytes(png_bytes)
        link = tmp_path / "link.png"
        link.symlink_to(real)
        with pytest.raises(Rejected):
            validate(link)

    def test_validate_source_rejects_gif(self, tmp_path, gif_bytes):
        p = tmp_path / "a.gif"
        p.write_bytes(gif_bytes)
        with pytest.raises(Rejected):
            validate_source(p)

    def test_validate_source_accepts_still_png(self, tmp_path, png_bytes):
        p = tmp_path / "s.png"
        p.write_bytes(png_bytes)
        assert validate_source(p).startswith("PNG")


class TestResolveWithin:
    def test_inside_root_ok(self, tmp_path):
        (tmp_path / "sub").mkdir()
        target = tmp_path / "sub" / "f.png"
        target.write_bytes(b"x")
        assert resolve_within(tmp_path, target) == target.resolve()

    def test_escape_rejected(self, tmp_path):
        outside = tmp_path.parent / "outside.png"
        with pytest.raises(Rejected):
            resolve_within(tmp_path / "root", outside)


def test_sha256_bytes_stable():
    assert sha256_bytes(b"abc") == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
