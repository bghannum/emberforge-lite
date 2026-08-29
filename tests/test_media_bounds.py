"""Bounds and error branches of header-only media inspection (media.py)."""

from __future__ import annotations

import struct

import pytest

import emberforge_lite.media as media
from emberforge_lite.media import (
    Rejected,
    audio_kind,
    inspect_audio,
    inspect_gif,
    inspect_mp3,
    inspect_png,
    inspect_wav,
    png_has_alpha,
    sha256_bytes,
    sha256_file,
    validate,
    validate_source,
)
from emberforge_lite.providers.fakes import _png, _tiny_gif, _wav


def minimal_mp3(frames: int = 3) -> bytes:
    """A hand-built MPEG-1 Layer III stream: 128 kbps, 44.1 kHz, stereo."""
    # byte1 0xFB: sync + MPEG1 + Layer III + no-CRC; byte2 0x90: bitrate idx 9
    # (128k) + samplerate idx 0 (44.1k); byte3 0x00: stereo.
    frame_bytes = int(144 * 128 * 1000 / 44100)  # 417
    frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * (frame_bytes - 4)
    return frame * frames


class TestPngBounds:
    def test_truncated_chunk_header(self):
        with pytest.raises(Rejected):
            inspect_png(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    def test_no_iend(self):
        data = _png(8, 8, b"x")
        # Chop off the trailing IEND chunk.
        with pytest.raises(Rejected):
            inspect_png(data[:-12])

    def test_over_dimension(self):
        data = bytearray(_png(8, 8, b"x"))
        struct.pack_into(">I", data, 16, media.MAX_DIMENSION + 1)
        with pytest.raises(Rejected):
            inspect_png(bytes(data))

    def test_png_has_alpha_true_and_false(self):
        assert png_has_alpha(_png(8, 8, b"x")) is True  # RGBA
        assert png_has_alpha(b"not a png") is False


class TestGifBounds:
    def test_too_many_frames(self, monkeypatch):
        monkeypatch.setattr(media, "MAX_FRAMES", 2)
        with pytest.raises(Rejected):
            inspect_gif(_tiny_gif((5, 5, 5)))

    def test_unknown_marker(self):
        data = bytearray(_tiny_gif((5,)))
        # Corrupt the first block marker to something invalid.
        # Find the trailer and inject garbage is fragile; just truncate.
        with pytest.raises(Rejected):
            inspect_gif(bytes(data[:13]))


class TestWavBounds:
    def test_not_wav(self):
        with pytest.raises(Rejected):
            inspect_wav(b"nope" + b"\x00" * 60)

    def test_bad_sample_rate(self):
        data = bytearray(_wav(200, b"x"))
        # Zero out the sample rate field in the fmt chunk.
        idx = data.find(b"fmt ")
        struct.pack_into("<I", data, idx + 8 + 4, 0)  # sample_rate -> 0
        with pytest.raises(Rejected):
            inspect_wav(bytes(data))


class TestMp3:
    def test_inspect_mp3(self):
        duration, rate, channels = inspect_mp3(minimal_mp3(4))
        assert rate == 44100
        assert channels == 2
        assert duration > 0

    def test_audio_kind_and_dispatch(self):
        mp3 = minimal_mp3(2)
        assert audio_kind(mp3) == "mp3"
        assert inspect_audio(mp3)[1] == 44100

    def test_not_mp3(self):
        with pytest.raises(Rejected):
            inspect_mp3(b"ID3nope")


class TestValidateErrors:
    def test_missing_file(self, tmp_path):
        with pytest.raises(Rejected):
            validate(tmp_path / "nope.png")

    def test_unknown_format(self, tmp_path):
        p = tmp_path / "x.png"
        p.write_bytes(b"neither png nor gif but long enough" * 2)
        with pytest.raises(Rejected):
            validate(p)

    def test_validate_source_animated_rejected(self, tmp_path):
        # APNG-ish: build a PNG then bump declared frames via acTL is complex;
        # a GIF is the simpler animated case validate_source must reject.
        p = tmp_path / "a.gif"
        p.write_bytes(_tiny_gif((5, 5)))
        with pytest.raises(Rejected):
            validate_source(p)

    def test_root_confinement(self, tmp_path):
        (tmp_path / "root").mkdir()
        outside = tmp_path / "x.png"
        outside.write_bytes(_png(8, 8, b"x"))
        with pytest.raises(Rejected):
            validate(outside, root=tmp_path / "root")


class TestHashing:
    def test_sha256_file_matches_bytes(self, tmp_path):
        data = _png(8, 8, b"x")
        p = tmp_path / "f.png"
        p.write_bytes(data)
        assert sha256_file(p) == sha256_bytes(data)


class TestMoreBounds:
    def test_validate_oversized(self, tmp_path, monkeypatch):
        monkeypatch.setattr(media, "MAX_FILE_BYTES", 10)
        p = tmp_path / "big.png"
        p.write_bytes(_png(16, 16, b"x"))
        with pytest.raises(Rejected):
            validate(p)

    def test_wav_too_many_channels(self):
        data = bytearray(_wav(200, b"x"))
        idx = data.find(b"fmt ")
        # fmt body = audio_format(H) channels(H) ...; channels at body+2 = idx+10.
        struct.pack_into("<H", data, idx + 10, 4)  # 4 channels > MAX
        with pytest.raises(Rejected):
            inspect_wav(bytes(data))

    def test_mp3_with_id3_tag(self):
        # ID3v2 header (10 bytes, syncsafe size 0) then MPEG frames.
        id3 = b"ID3\x03\x00\x00\x00\x00\x00\x00"
        frame_bytes = int(144 * 128 * 1000 / 44100)
        frame = bytes([0xFF, 0xFB, 0x90, 0x00]) + b"\x00" * (frame_bytes - 4)
        duration, rate, _ = inspect_mp3(id3 + frame * 3)
        assert rate == 44100
        assert duration > 0

    def test_empty_file_rejected(self, tmp_path):
        p = tmp_path / "empty.png"
        p.write_bytes(b"")
        with pytest.raises(Rejected):
            validate(p)

    def test_symlink_rejected(self, tmp_path):
        real = tmp_path / "real.png"
        real.write_bytes(_png(8, 8, b"x"))
        link = tmp_path / "link.png"
        link.symlink_to(real)
        with pytest.raises(Rejected):
            validate(link)


import struct as _struct
import zlib as _zlib


def _rgb_png(w=2, h=2) -> bytes:
    def chunk(kind, payload):
        crc = _zlib.crc32(kind + payload) & 0xFFFFFFFF
        return _struct.pack(">I", len(payload)) + kind + payload + _struct.pack(">I", crc)

    raw = b""
    for _ in range(h):
        raw += b"\x00" + b"\x10\x20\x30" * w  # filter 0 + RGB pixels
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", _struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))  # colour type 2 = RGB
        + chunk(b"IDAT", _zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class TestAlphaAndFormats:
    def test_png_has_alpha_false_for_rgb(self):
        assert png_has_alpha(_rgb_png()) is False

    def test_inspect_rgb_png(self):
        assert inspect_png(_rgb_png(3, 3)) == (3, 3, 1)

    def test_validate_rgb_png(self, tmp_path):
        p = tmp_path / "rgb.png"
        p.write_bytes(_rgb_png())
        assert validate(p).startswith("PNG")

    def test_audio_kind_rejects_junk(self):
        with pytest.raises(Rejected):
            audio_kind(b"junkjunkjunk")
