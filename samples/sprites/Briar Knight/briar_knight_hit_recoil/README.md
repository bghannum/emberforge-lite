# Briar Knight hit recoil

A 16-frame, non-looping reaction to a heavy hit from screen-right, followed by a controlled recovery to canonical idle.

## Playback timing

- Loop: No.
- Engine base playback speed: `20.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `0.995` seconds.
- Uniform-timing fallback: approximately `15.8` FPS.
- Per-frame delays, in milliseconds: `60, 35, 40, 45, 50, 50, 60, 65, 60, 60, 60, 65, 70, 75, 80, 120`.

Frame 1 is the impact cue. Apply recoil offsets to the visual child, not the combat root.

## Folder contents

- `briar_knight_hit_recoil_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Briar Knight/briar_knight_hit_recoil/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.
