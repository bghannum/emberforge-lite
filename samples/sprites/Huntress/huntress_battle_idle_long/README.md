# Huntress long battle idle

A 28-frame looping combat idle with breathing, a planted weight shift, bow-hand readiness adjustment, and asynchronous hair motion.

## Playback timing

- Loop: Yes.
- Engine base playback speed: `10.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `3.190` seconds.
- Uniform-timing fallback: approximately `8.8` FPS.
- Per-frame delays, in milliseconds: `160, 110, 100, 110, 120, 110, 100, 110, 120, 110, 100, 110, 120, 110, 100, 110, 120, 110, 100, 110, 120, 110, 100, 110, 120, 110, 120, 160`.

Frames 0 and 27 are exact canonical idle copies. There are no gameplay event hooks.

## Folder contents

- `huntress_battle_idle_long_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Huntress/huntress_battle_idle_long/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

