# Briar Knight lunge attack (deprecated)

A 16-frame, non-looping two-handed lunge. The visual child advances while the combat root remains planted; frames 8–9 are the active window and frame 9 is the presentation damage event.

## Playback timing

- Loop: No.
- Engine base playback speed: `18.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `0.881` seconds.
- Uniform-timing fallback: approximately `18` FPS.
- Per-frame delays, in milliseconds: `83, 56, 56, 67, 56, 44, 44, 39, 36, 50, 44, 50, 56, 56, 61, 83`.

Frames 0 and 15 are identical canonical idle endpoints. This package is deprecated but retained for reference.

## Folder contents

- `briar_knight_lunge_attack_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Briar Knight/briar_knight_attack (deprecated)/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.
