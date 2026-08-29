"""Bound untrusted media before anything decodes it, and hash it.

Provider files and metadata are untrusted (the threat model (docs/threat-model.md)), and so is anything a
user drops in. Every limit in the threat model (docs/threat-model.md) is enforced here using
only header and chunk-stream parsing: nothing in this module decodes pixel data,
so a hostile file cannot exhaust memory on the way to being rejected.

`tools/probe_validate.py` is a thin command-line front end over this.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

# Limits from docs/threat-model.md.
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_DECODED_BYTES = 64 * 1024 * 1024
#: A spritesheet is long and thin: sixteen 256px frames in a horizontal strip is
#: 4096x256. At 2048 this rejected any animation over eight frames, which is a
#: product decision that had ended up encoded as a security bound.
#:
#: What actually bounds memory is MAX_DECODED_BYTES, and that is unchanged. What
#: changes is which check binds first: at 2048 a square image projected to 17MB,
#: a quarter of the budget, so the per-axis limit was doing the work. At 4096 a
#: square single-frame image projects to exactly 67,108,864 bytes -- the budget,
#: to the byte -- so the decode check is now the binding one and admits it by a
#: hair. That is the bound working as designed rather than a gap, but it is a
#: real widening and not the no-op it would be convenient to call it. The shape
#: this exists for needs far less: a 16-frame sheet is 4096x256, or 4.2MB.
MAX_DIMENSION = 4096
MAX_FRAMES = 64

# Bounds on the parsers themselves, so a hostile file cannot spin them.
MAX_CHUNKS = 10_000
MAX_GIF_BLOCKS = 100_000

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
GIF_SIGNATURES = (b"GIF87a", b"GIF89a")

#: An animation sound is short. Ten seconds is the manifest's own ceiling; this
#: allows headroom above it so a slightly long candidate can still be reviewed
#: and rejected rather than refused before anyone hears it.
MAX_AUDIO_MS = 30_000
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 192_000
MAX_CHANNELS = 2

#: Bounds the MP3 frame walk, the same way MAX_CHUNKS bounds the PNG one.
MAX_MP3_FRAMES = 5_000

WAV_SIGNATURE = b"RIFF"
MP3_SIGNATURES = (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa")

#: MPEG-1 Layer III bitrates and sample rates, indexed as the header encodes
#: them. Enough to measure a duration; not a decoder.
_MP3_BITRATES = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0)
_MP3_RATES = (44100, 48000, 32000, 0)


class Rejected(Exception):
    """The asset violates a limit or is malformed. Never partially accepted."""


def _check_projected_decode(width: int, height: int, frames: int) -> None:
    if width <= 0 or height <= 0:
        raise Rejected(f"non-positive dimensions {width}x{height}")
    if max(width, height) > MAX_DIMENSION:
        raise Rejected(f"{width}x{height} exceeds the {MAX_DIMENSION}px limit")
    if frames > MAX_FRAMES:
        raise Rejected(f"{frames} frames exceeds the {MAX_FRAMES}-frame limit")
    projected = width * height * 4 * frames
    if projected > MAX_DECODED_BYTES:
        raise Rejected(
            f"projected decode of {projected} bytes "
            f"({width}x{height} x {frames} frames x RGBA) "
            f"exceeds the {MAX_DECODED_BYTES}-byte limit"
        )


def inspect_png(data: bytes) -> tuple[int, int, int]:
    """Walk the PNG chunk stream. Returns (width, height, frames).

    Two things are deliberately not trusted:

    * acTL's position. An APNG may place it after a large ancillary chunk, so a
      prefix-only scan would miss it and treat the file as static.
    * acTL's declared count. A file can declare one frame while carrying many
      more fcTL frame controls, so the controls are counted and the larger of
      the two wins.

    Per-frame fcTL geometry is bounded too: a small IHDR does not license an
    oversized frame.
    """
    if len(data) < 8 + 25:
        raise Rejected("too short to contain a PNG header")

    offset = 8
    width = height = None
    frames = 1
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    declared_frames = 1
    fctl_count = 0
    max_width = max_height = 0

    for _ in range(MAX_CHUNKS):
        if offset == len(data):
            break
        if offset + 8 > len(data):
            raise Rejected("truncated chunk header")

        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        body = offset + 8

        # Guard against a declared length that overflows the file.
        if length > len(data) or body + length + 4 > len(data):
            raise Rejected(f"chunk {ctype!r} declares {length} bytes past end of file")

        if ctype == b"IHDR":
            if seen_ihdr:
                raise Rejected("multiple IHDR chunks")
            if length != 13:
                raise Rejected(f"IHDR is {length} bytes, expected 13")
            width, height = struct.unpack(">II", data[body : body + 8])
            max_width, max_height = width, height
            seen_ihdr = True
        elif ctype == b"acTL":
            if length < 8:
                raise Rejected("malformed acTL chunk")
            (declared_frames,) = struct.unpack(">I", data[body : body + 4])
        elif ctype == b"fcTL":
            if length < 26:
                raise Rejected("malformed fcTL chunk")
            fctl_count += 1
            if fctl_count > MAX_FRAMES:
                raise Rejected(f"more than {MAX_FRAMES} fcTL frame controls")
            fw, fh = struct.unpack(">II", data[body + 4 : body + 12])
            max_width = max(max_width, fw)
            max_height = max(max_height, fh)
        elif ctype in (b"IDAT", b"fdAT"):
            seen_idat = True
        elif ctype == b"IEND":
            seen_iend = True
            offset = body + length + 4
            break

        offset = body + length + 4
    else:
        raise Rejected(f"more than {MAX_CHUNKS} chunks")

    if not seen_ihdr or width is None or height is None:
        raise Rejected("no IHDR chunk")
    if not seen_idat:
        raise Rejected("no image data; the file is incomplete")
    if not seen_iend:
        raise Rejected("no IEND chunk; the download is truncated at a chunk boundary")

    # Trust neither the declared count nor the header geometry on its own.
    frames = max(declared_frames, fctl_count, 1)
    _check_projected_decode(max_width, max_height, frames)
    return width, height, frames


#: PNG colour types that carry a per-pixel alpha channel: 4 is grey+alpha and
#: 6 is truecolour+alpha. Type 3 (indexed) can also be transparent, but only via
#: a tRNS chunk, which is why that case is checked separately.
_ALPHA_COLOUR_TYPES = frozenset({4, 6})
_INDEXED_COLOUR_TYPE = 3


def png_has_alpha(data: bytes) -> bool:
    """Whether a PNG can represent transparency at all.

    A header read, not a decode: the answer is in IHDR's colour-type byte, plus
    the presence of a tRNS chunk for indexed images. Bounding before decoding is
    the rule for every other property of provider output and there is no reason
    for this one to be the exception.

    "Can represent" rather than "does have". An RGBA image whose every pixel is
    opaque still passes, because the question this answers is whether a sprite
    could have a transparent background -- not whether this particular one does.
    Deciding that needs the pixels, and a provider that returned a fully opaque
    RGBA image has done something different from one that returned RGB.
    """
    try:
        inspect_png(data)
    except Rejected:
        return False

    offset = 8
    colour_type: int | None = None
    for _ in range(MAX_CHUNKS):
        if offset + 8 > len(data):
            break
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        ctype = data[offset + 4 : offset + 8]
        body = offset + 8
        if length > len(data) or body + length + 4 > len(data):
            break
        if ctype == b"IHDR" and length == 13:
            colour_type = data[body + 9]
            if colour_type in _ALPHA_COLOUR_TYPES:
                return True
        elif ctype == b"tRNS":
            return colour_type == _INDEXED_COLOUR_TYPE
        elif ctype == b"IDAT":
            # tRNS must precede IDAT, so by here the answer is settled.
            break
        offset = body + length + 4
    return False


def inspect_gif(data: bytes) -> tuple[int, int, int]:
    """Scan the GIF block stream far enough to count frames. No decoding.

    Each image descriptor carries its own geometry, which may exceed the logical
    screen. Bounding only the screen would let a 1x1 GIF carry a 65535x65535
    frame, so every descriptor is checked and the largest wins.
    """
    if len(data) < 13:
        raise Rejected("too short to contain a GIF header")

    width, height = struct.unpack("<HH", data[6:10])
    max_width, max_height = width, height
    packed = data[10]
    offset = 13

    # Skip the global color table if present, so block parsing starts aligned.
    if packed & 0x80:
        offset += 3 * (2 ** ((packed & 0x07) + 1))

    def skip_sub_blocks(pos: int) -> int:
        for _ in range(MAX_GIF_BLOCKS):
            if pos >= len(data):
                raise Rejected("truncated sub-block stream")
            size = data[pos]
            pos += 1
            if size == 0:
                return pos
            pos += size
        raise Rejected("unterminated sub-block stream")

    frames = 0
    for _ in range(MAX_GIF_BLOCKS):
        if offset >= len(data):
            raise Rejected("truncated block stream")
        marker = data[offset]

        if marker == 0x3B:  # trailer
            break
        if marker == 0x21:  # extension
            if offset + 2 > len(data):
                raise Rejected("truncated extension block")
            offset = skip_sub_blocks(offset + 2)
        elif marker == 0x2C:  # image descriptor
            frames += 1
            if frames > MAX_FRAMES:
                raise Rejected(f"more than {MAX_FRAMES} frames")
            if offset + 10 > len(data):
                raise Rejected("truncated image descriptor")
            frame_w, frame_h = struct.unpack("<HH", data[offset + 5 : offset + 9])
            max_width = max(max_width, frame_w)
            max_height = max(max_height, frame_h)
            local_packed = data[offset + 9]
            offset += 10
            if local_packed & 0x80:
                offset += 3 * (2 ** ((local_packed & 0x07) + 1))
            offset += 1  # LZW minimum code size
            offset = skip_sub_blocks(offset)
        else:
            raise Rejected(f"unknown block marker 0x{marker:02x}")
    else:
        raise Rejected(f"more than {MAX_GIF_BLOCKS} blocks")

    if frames == 0:
        raise Rejected("no image data")

    _check_projected_decode(max_width, max_height, frames)
    return width, height, frames


def resolve_within(root: Path, candidate: Path) -> Path:
    """Resolve a path and refuse anything that escapes `root`.

    Checking for symlinks and traversal segments separately is not enough: a
    symlinked *parent directory*, or a path assembled from pieces that are each
    individually harmless, can still land outside. Resolving both sides and
    comparing is the check that actually holds.
    """
    resolved_root = root.resolve()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise Rejected(f"path cannot be resolved: {exc}") from exc

    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise Rejected(f"{candidate} resolves outside the permitted root {root}")

    return resolved


def validate_source(path: Path, *, root: Path | None = None) -> str:
    """Validate a file that will be used as an actor SOURCE.

    Stricter than `validate`. A source must be a still PNG: the design package
    §7 accepts only non-animated PNG for source input, and the reason is
    concrete. Pillow opens an animated GIF or APNG happily and hands back its
    first frame, so a multi-frame file would be silently reduced to one frame on
    its way to the provider, and nobody would learn that the other frames had
    been discarded.
    """
    summary = validate(path, root=root)

    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise Rejected("a source sprite must be a PNG; GIF is accepted only for provider output")

    _, _, frames = inspect_png(data)
    if frames > 1:
        raise Rejected(f"a source sprite must be a still image; this PNG declares {frames} frames")

    return summary


def validate(path: Path, *, root: Path | None = None) -> str:
    """Validate one asset. Raises Rejected, or returns a one-line summary.

    `root`, when given, confines the path: anything resolving outside it is
    refused before it is read at all.
    """
    if root is not None:
        resolve_within(root, path)

    if path.is_symlink():
        raise Rejected("is a symlink")
    if not path.is_file():
        raise Rejected("is not a regular file")

    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise Rejected(f"{size} bytes exceeds the {MAX_FILE_BYTES}-byte limit")
    if size == 0:
        raise Rejected("is empty")

    data = path.read_bytes()

    if data.startswith(PNG_SIGNATURE):
        kind = "PNG"
        width, height, frames = inspect_png(data)
    elif data.startswith(GIF_SIGNATURES):
        kind = "GIF"
        width, height, frames = inspect_gif(data)
    else:
        raise Rejected("not a PNG or GIF; the probe expects only these formats")

    return f"{kind} {width}x{height}, {frames} frame(s), {size} bytes"


def sha256_file(path: Path) -> str:
    """Content hash of a file, read in bounded chunks.

    Identity in this system is by content, never by filename: a path can be
    repointed, and an approval that names a file rather than its bytes is an
    approval of whatever happens to be there later.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def inspect_wav(data: bytes) -> tuple[int, int, int]:
    """Header-only WAV check. Returns `(duration_ms, sample_rate, channels)`.

    Reads the RIFF chunk table without decoding a sample, for the same reason
    `inspect_png` exists: the decoder is what a hostile file attacks, so the
    bounds have to be established before anything is handed to one.
    """
    if len(data) < 44 or not data.startswith(WAV_SIGNATURE) or data[8:12] != b"WAVE":
        raise Rejected("not a WAV file")
    if len(data) > MAX_FILE_BYTES:
        raise Rejected(f"{len(data)} bytes exceeds the {MAX_FILE_BYTES}-byte limit")

    offset = 12
    sample_rate = channels = bits = 0
    data_bytes = 0
    for _ in range(MAX_CHUNKS):
        if offset + 8 > len(data):
            break
        kind = data[offset : offset + 4]
        (size,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        body = offset + 8

        if kind == b"fmt " and size >= 16 and body + 16 <= len(data):
            _, channels, sample_rate, _, _, bits = struct.unpack("<HHIIHH", data[body : body + 16])
        elif kind == b"data":
            data_bytes = min(size, len(data) - body)

        # Chunks are word-aligned, and a zero-size chunk would spin this forever.
        offset = body + size + (size & 1)
        if size == 0:
            offset += 1
    else:
        raise Rejected(f"more than {MAX_CHUNKS} RIFF chunks")

    if not sample_rate or not channels:
        raise Rejected("the WAV header declares no format chunk")
    if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
        raise Rejected(f"sample rate {sample_rate} is outside the accepted range")
    if channels > MAX_CHANNELS:
        raise Rejected(f"{channels} channels exceeds the {MAX_CHANNELS}-channel limit")

    frame_bytes = max(1, channels * max(1, bits // 8))
    duration_ms = int(data_bytes / frame_bytes / sample_rate * 1000)
    if duration_ms > MAX_AUDIO_MS:
        raise Rejected(f"{duration_ms}ms exceeds the {MAX_AUDIO_MS}ms limit")
    return duration_ms, sample_rate, channels


def inspect_mp3(data: bytes) -> tuple[int, int, int]:
    """Header-only MP3 check. Returns `(duration_ms, sample_rate, channels)`.

    Walks frame headers to measure length. A compressed format is where a small
    file can claim to be a very long one, which is exactly the case a size limit
    alone does not catch.
    """
    if len(data) > MAX_FILE_BYTES:
        raise Rejected(f"{len(data)} bytes exceeds the {MAX_FILE_BYTES}-byte limit")
    if not data.startswith(MP3_SIGNATURES):
        raise Rejected("not an MP3 file")

    offset = 0
    if data.startswith(b"ID3"):
        if len(data) < 10:
            raise Rejected("truncated ID3 tag")
        # Syncsafe integer: seven bits per byte.
        size = 0
        for byte in data[6:10]:
            if byte & 0x80:
                raise Rejected("malformed ID3 size")
            size = (size << 7) | byte
        offset = 10 + size

    duration_ms = 0.0
    sample_rate = channels = 0
    frames = 0
    while offset + 4 <= len(data) and frames < MAX_MP3_FRAMES:
        if data[offset] != 0xFF or (data[offset + 1] & 0xE0) != 0xE0:
            offset += 1
            continue

        bitrate = _MP3_BITRATES[(data[offset + 2] & 0xF0) >> 4]
        rate = _MP3_RATES[(data[offset + 2] & 0x0C) >> 2]
        if not bitrate or not rate:
            offset += 1
            continue

        padding = (data[offset + 2] & 0x02) >> 1
        channels = 1 if (data[offset + 3] & 0xC0) >> 6 == 3 else 2
        sample_rate = rate
        frame_bytes = int(144 * bitrate * 1000 / rate) + padding
        if frame_bytes <= 0:
            raise Rejected("malformed MP3 frame length")

        duration_ms += 1152 / rate * 1000
        if duration_ms > MAX_AUDIO_MS:
            raise Rejected(f"{duration_ms:.0f}ms exceeds the {MAX_AUDIO_MS}ms limit")
        offset += frame_bytes
        frames += 1

    if not frames:
        raise Rejected("no MP3 frame headers were found")
    if frames >= MAX_MP3_FRAMES:
        raise Rejected(f"more than {MAX_MP3_FRAMES} MP3 frames")
    return int(duration_ms), sample_rate, channels


def inspect_audio(data: bytes) -> tuple[int, int, int]:
    """Whichever audio format this is, bounded the same way."""
    if data.startswith(WAV_SIGNATURE):
        return inspect_wav(data)
    if data.startswith(MP3_SIGNATURES):
        return inspect_mp3(data)
    raise Rejected("not a WAV or MP3 file")


def audio_kind(data: bytes) -> str:
    """The format the bytes actually are, not the one a caller expected.

    Labelling audio by what was requested is how an MP3 comes to be stored as a
    `.wav` and refused by its own validator after it has already been paid for.
    """
    if data.startswith(WAV_SIGNATURE):
        return "wav"
    if data.startswith(MP3_SIGNATURES):
        return "mp3"
    raise Rejected("not a WAV or MP3 file")
