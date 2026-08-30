# Gravescribe dark mist

A 16-frame, non-looping cast that channels smoke from the open book toward an off-screen target on the right, then returns to idle.

## Playback timing

- Loop: No.
- Engine base playback speed: `18.0` FPS.
- Runtime `speed_scale`: `1.0`.
- Timing mode: variable per-frame durations.
- Total duration: `1.240` seconds.
- Uniform-timing fallback: approximately `12.9` FPS.
- Per-frame delays, in milliseconds: `80, 60, 60, 60, 60, 60, 70, 70, 80, 80, 80, 80, 80, 80, 100, 140`.

Frame 9 is the visual peak. Targeting and damage remain owned by game logic.

## Folder contents

- `gravescribe_dark_mist_preview.gif`: authored timing preview.
- `frames/`: ordered transparent gameplay PNGs.
- `README.md`: animation intent, timing, and integration notes.

Source atlases, aligned atlases, engine resources, controllers, timing metadata, generation prompts, endpoint copies, and exporter tools are preserved under `../../_production/Gravescribe/gravescribe_dark_mist/`.

Use nearest-neighbor texture filtering, no mipmaps, and lossless PNG.

