# Briar Knight long battle idle

A 28-frame looping armored breathing cycle with a planted weight shift, grip adjustment, and gentle cape lag. The sword stays low and combat-ready.

## Playback timing

- Loop: Yes.
- Engine base playback speed: `10.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `3.430` seconds.
- Uniform-timing fallback: approximately `8.2` FPS.
- Per-frame delays, in milliseconds: `180, 120, 110, 110, 120, 130, 110, 110, 120, 130, 120, 110, 110, 120, 130, 120, 110, 110, 120, 130, 120, 110, 110, 120, 130, 120, 120, 180`.

Frames 0 and 27 are exact canonical idle copies. There are no gameplay event hooks.

## Folder contents

- `briar_knight_battle_idle_long_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Briar Knight/briar_knight_battle_idle_long/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

