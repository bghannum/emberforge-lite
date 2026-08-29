"""Rewrite a GIF's per-frame delay times to change playback speed.

Pure stdlib, no re-encoding: walks the GIF89a/87a block structure and
scales the 2-byte delay field inside each Graphic Control Extension.
Pixel data is never touched. Returns the original bytes unchanged if the
file doesn't parse as a well-formed GIF (never raises on bad input).
"""

from statistics import median

MIN_FACTOR = 0.05
MAX_FACTOR = 4.0
MIN_DELAY_UNITS = 10  # browsers render a 0/1 delay as ~100ms; floor scaling from there

#: SpriteLab animates at 8 fps; its web-UI preview GIFs are encoded faster
#: (median 6-8 cs, i.e. 12.5-16.7 fps), which is why they "play a bit fast".
NATIVE_FPS = 8


def gce_delays(data: bytes) -> list[int]:
    """Every Graphic Control Extension delay in the file, in 1/100 s, in order."""
    delays: list[int] = []
    try:
        if data[:6] not in (b"GIF87a", b"GIF89a"):
            return delays
        n = len(data)
        packed = data[10]
        pos = 13
        if packed & 0x80:
            pos += 3 * (2 << (packed & 0x07))
        while pos < n:
            marker = data[pos]
            if marker == 0x21:
                if data[pos + 1] == 0xF9:
                    block_size = data[pos + 2]
                    delays.append(data[pos + 4] | (data[pos + 5] << 8))
                    pos = pos + 3 + block_size
                    if pos < n and data[pos] == 0x00:
                        pos += 1
                else:
                    pos = _skip_subblocks(data, pos + 2)
            elif marker == 0x2C:
                desc_pos = pos + 1
                local_packed = data[desc_pos + 8]
                pos = desc_pos + 9
                if local_packed & 0x80:
                    pos += 3 * (2 << (local_packed & 0x07))
                pos += 1
                pos = _skip_subblocks(data, pos)
            elif marker == 0x3B:
                break
            else:
                break
    except IndexError:
        pass
    return delays


def set_fps(data: bytes, fps: int = NATIVE_FPS) -> bytes:
    """Rescale the delays so the *median* frame plays at `fps`.

    Proportional, not uniform: the eased-out timing and the end-of-loop hold that
    the preview encoder applied are kept; only the overall rate moves. A file
    already within 1 cs of the target is returned untouched.
    """
    delays = [d if d > 1 else MIN_DELAY_UNITS for d in gce_delays(data)]
    if not delays:
        return data
    current = median(delays)
    target = 100 / fps
    if abs(current - target) <= 1:
        return data
    return slow_gif(data, current / target)


def _skip_subblocks(data: bytes, pos: int) -> int:
    n = len(data)
    while pos < n:
        size = data[pos]
        pos += 1
        if size == 0:
            return pos
        pos += size
    return pos


def slow_gif(data: bytes, factor: float) -> bytes:
    if factor == 1:
        return data
    factor = max(MIN_FACTOR, min(factor, MAX_FACTOR))

    try:
        if data[:6] not in (b"GIF87a", b"GIF89a"):
            return data

        out = bytearray(data)
        n = len(data)
        packed = data[10]
        pos = 13
        if packed & 0x80:  # global color table present
            pos += 3 * (2 << (packed & 0x07))

        while pos < n:
            marker = data[pos]
            if marker == 0x21:  # extension
                label = data[pos + 1]
                if label == 0xF9:  # Graphic Control Extension
                    start = pos
                    block_size = data[start + 2]
                    delay_pos = start + 4
                    old_delay = data[delay_pos] | (data[delay_pos + 1] << 8)
                    effective = old_delay if old_delay > 1 else MIN_DELAY_UNITS
                    new_delay = max(1, min(round(effective / factor), 0xFFFF))
                    out[delay_pos] = new_delay & 0xFF
                    out[delay_pos + 1] = (new_delay >> 8) & 0xFF
                    pos = start + 3 + block_size
                    if pos < n and data[pos] == 0x00:
                        pos += 1
                else:
                    pos = _skip_subblocks(data, pos + 2)
            elif marker == 0x2C:  # image descriptor
                desc_pos = pos + 1
                local_packed = data[desc_pos + 8]
                pos = desc_pos + 9
                if local_packed & 0x80:
                    pos += 3 * (2 << (local_packed & 0x07))
                pos += 1  # LZW minimum code size
                pos = _skip_subblocks(data, pos)
            elif marker == 0x3B:  # trailer
                break
            else:
                return data  # unrecognized structure, bail out safely

        return bytes(out)
    except IndexError:
        return data
