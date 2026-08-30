# Huntress battle idle

A restrained 16-frame looping combat idle with breathing, a planted weight shift, and subtle bow and hair motion.

## Playback timing

- Loop: Yes.
- Engine base playback speed: `10.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `1.630` seconds.
- Uniform-timing fallback: approximately `9.8` FPS.
- Per-frame delays, in milliseconds: `110, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 120`.

Use this as the short idle loop; the long battle idle provides a more varied alternative.

## Folder contents

- `huntress_battle_idle_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Huntress/huntress_battle_idle/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

