# Gravescribe long battle idle

A 28-frame looping idle with breathing, a planted bookward weight shift, restrained re-grip, robe lag, and asynchronous purple-flame motion.

## Playback timing

- Loop: Yes.
- Engine base playback speed: `10.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `2.910` seconds.
- Uniform-timing fallback: approximately `9.6` FPS.
- Per-frame delays, in milliseconds: `150, 100, 90, 100, 110, 100, 90, 100, 110, 100, 90, 100, 110, 100, 90, 100, 110, 100, 90, 100, 110, 100, 90, 100, 110, 100, 110, 150`.

Frames 0 and 27 are canonical idle copies. Frames 20–26 use a controlled reverse-settle repair because the generated source was clipped.

## Folder contents

- `gravescribe_battle_idle_long_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Gravescribe/gravescribe_battle_idle_long/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

