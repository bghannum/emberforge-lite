# Gravescribe hit recoil

A 16-frame, non-looping reaction to a hit from screen-right, carrying the robe and purple fire through the stagger before recovering to idle.

## Playback timing

- Loop: No.
- Engine base playback speed: `12.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `0.995` seconds.
- Uniform-timing fallback: approximately `15.8` FPS.
- Per-frame delays, in milliseconds: `60, 35, 40, 45, 50, 50, 60, 65, 60, 60, 60, 65, 70, 75, 80, 120`.

Frame 1 is the impact cue. Recoil offsets belong on the visual child rather than the combat root.

## Folder contents

- `gravescribe_hit_recoil_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Gravescribe/gravescribe_hit_recoil/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.
