# Huntress jump bow attack

A 16-frame, non-looping aerial bow attack with takeoff, airborne shot presentation, landing, and recovery.

## Playback timing

- Loop: No.
- Engine base playback speed: `18.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `1.240` seconds.
- Uniform-timing fallback: approximately `12.9` FPS.
- Per-frame delays, in milliseconds: `80, 60, 60, 60, 60, 60, 70, 70, 80, 80, 80, 80, 80, 80, 100, 140`.

The authored preview timing is the source of truth; this older package does not include a dedicated engine resource.

## Folder contents

- `huntress_jump_bow_attack_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Huntress/huntress_jump_bow_attack/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

