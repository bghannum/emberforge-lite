"""Trim WAV and MP3 files without decoding. Stdlib only.

WAV is sliced at sample-frame boundaries -- exact. MP3 is cut at MPEG frame
boundaries (~26 ms at 44.1 kHz) by walking the same headers `media.inspect_mp3`
walks; no re-encoding, so the cut is lossless but only frame-accurate, and the
first kept frame may carry a faint glitch if the encoder used the bit reservoir.
Good enough to shorten a sound effect for review; not a mastering tool.
"""

from __future__ import annotations

import struct

from media import MP3_SIGNATURES, WAV_SIGNATURE, Rejected, _MP3_BITRATES, _MP3_RATES


class TrimError(ValueError):
    """The requested trim cannot be performed."""


def trim(data: bytes, start_ms: int, end_ms: int) -> bytes:
    if start_ms < 0 or end_ms <= start_ms:
        raise TrimError("end must be after start, and start cannot be negative")
    if data.startswith(WAV_SIGNATURE):
        return _trim_wav(data, start_ms, end_ms)
    if data.startswith(MP3_SIGNATURES):
        return _trim_mp3(data, start_ms, end_ms)
    raise TrimError("only WAV and MP3 can be trimmed")


def _trim_wav(data: bytes, start_ms: int, end_ms: int) -> bytes:
    if data[8:12] != b"WAVE":
        raise TrimError("not a WAVE file")
    fmt = None
    pcm = None
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            pcm = body
        pos += 8 + size + (size & 1)
    if fmt is None or pcm is None or len(fmt) < 16:
        raise TrimError("WAV is missing its fmt or data chunk")
    audio_format, channels, rate, _, block_align, bits = struct.unpack("<HHIIHH", fmt[:16])
    if audio_format not in (1, 3) or block_align <= 0:
        raise TrimError("only PCM WAV can be trimmed")

    total_ms = len(pcm) // block_align * 1000 // rate
    if start_ms >= total_ms:
        raise TrimError(f"start {start_ms} ms is past the end of a {total_ms} ms sound")
    end_ms = min(end_ms, total_ms)
    a = (start_ms * rate // 1000) * block_align
    b = (end_ms * rate // 1000) * block_align
    cut = pcm[a:b]
    if not cut:
        raise TrimError("the trim would be empty")

    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt)) + fmt + (b"\x00" if len(fmt) & 1 else b"")
    data_chunk = b"data" + struct.pack("<I", len(cut)) + cut + (b"\x00" if len(cut) & 1 else b"")
    body = b"WAVE" + fmt_chunk + data_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _mp3_frames(data: bytes) -> tuple[int, list[tuple[int, int, float]]]:
    """(header_end, [(offset, size, frame_ms), ...]) for every MPEG frame."""
    offset = 0
    if data.startswith(b"ID3"):
        size = 0
        for byte in data[6:10]:
            if byte & 0x80:
                raise Rejected("malformed ID3 size")
            size = (size << 7) | byte
        offset = 10 + size
    header_end = offset

    frames: list[tuple[int, int, float]] = []
    while offset + 4 <= len(data):
        if data[offset] != 0xFF or (data[offset + 1] & 0xE0) != 0xE0:
            offset += 1
            continue
        bitrate = _MP3_BITRATES[(data[offset + 2] & 0xF0) >> 4]
        rate = _MP3_RATES[(data[offset + 2] & 0x0C) >> 2]
        if not bitrate or not rate:
            offset += 1
            continue
        padding = (data[offset + 2] & 0x02) >> 1
        size = int(144 * bitrate * 1000 / rate) + padding
        if size <= 0 or offset + size > len(data):
            break
        frames.append((offset, size, 1152 / rate * 1000))
        offset += size
    if not frames:
        raise TrimError("no MP3 frames found")
    return header_end, frames


def _trim_mp3(data: bytes, start_ms: int, end_ms: int) -> bytes:
    header_end, frames = _mp3_frames(data)
    kept = bytearray(data[:header_end])
    t = 0.0
    any_kept = False
    for offset, size, frame_ms in frames:
        frame_start, frame_end = t, t + frame_ms
        t = frame_end
        # Keep every frame that overlaps the window, so the cut never lands
        # inside a frame.
        if frame_end <= start_ms or frame_start >= end_ms:
            continue
        kept += data[offset : offset + size]
        any_kept = True
    if not any_kept:
        raise TrimError(f"the trim window is outside the {t:.0f} ms sound")
    return bytes(kept)
