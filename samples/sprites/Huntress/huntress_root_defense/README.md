# Huntress root defense

A 16-frame, non-looping defensive animation in which roots gather around the planted Huntress before the effect settles.

## Playback timing

- Loop: No.
- Engine base playback speed: `15.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `1.430` seconds.
- Uniform-timing fallback: approximately `11.2` FPS.
- Per-frame delays, in milliseconds: `80, 70, 70, 70, 70, 70, 80, 80, 90, 90, 90, 90, 100, 100, 120, 160`.

The authored preview timing is the source of truth; this older package does not include a dedicated engine resource.

## Folder contents

- `huntress_root_defense_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Huntress/huntress_root_defense/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

