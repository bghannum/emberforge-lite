# Huntress wind-arrow attack

A 16-frame, non-looping bow attack that gathers wind, releases the arrow toward screen-right, and recovers to idle.

## Playback timing

- Loop: No.
- Engine base playback speed: `15.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `1.380` seconds.
- Uniform-timing fallback: approximately `11.6` FPS.
- Per-frame delays, in milliseconds: `80, 70, 70, 70, 70, 70, 70, 70, 80, 80, 80, 90, 100, 100, 120, 160`.

The authored preview timing is the source of truth; this older package does not include a dedicated engine resource.

## Folder contents

- `huntress_wind_arrow_attack_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Huntress/huntress_wind_arrow_attack/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

