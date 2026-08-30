# Briar Knight rose bloom (deprecated)

A 16-frame, non-looping transformation that grows thorny briars and roses over the armor and finishes on a persistent rosebound state.

## Playback timing

- Loop: No.
- Engine base playback speed: `15.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `1.380` seconds.
- Uniform-timing fallback: approximately `11.6` FPS.
- Per-frame delays, in milliseconds: `80, 70, 70, 70, 70, 70, 70, 70, 80, 80, 80, 90, 100, 100, 120, 160`.

Frame 12 is the visual peak. The final frame is a resulting-state idle rather than the original idle. This package is deprecated.

## Folder contents

- `briar_knight_rose_bloom_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Briar Knight/briar_knight_rose_bloom (deprecated)/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

