# Pips & Peril sprite library

## Character layout

Each character directory keeps its canonical gameplay idle at the character root:

- `Briar Knight/briar_knight_idle_game.png`
- `Gravescribe/gravescribe_idle_game.png`
- `Huntress/huntress_idle_game.png`

Each animation directory contains exactly:

```text
animation_name/
├── README.md
├── animation_name_preview.gif
└── frames/
    ├── frame_00.png
    └── ...
```

The README is the timing and integration contract. It must state the engine base playback speed, runtime speed scale, loop behavior, variable or uniform timing mode, total duration, uniform-FPS fallback, exact per-frame delays, event or peak frames, and endpoint behavior.

The preview GIF carries the authored presentation timing. The `frames/` directory is the runtime-neutral ordered RGBA sequence.

## Production archive

Generated sources, cleaned sources, atlases, engine resources, controllers, metadata, prompts, endpoint copies, and exporter tools live in `_production/`, mirroring the character and animation paths. See `_production/README.md`.

Use nearest-neighbor texture filtering, disable mipmaps, and keep PNG compression lossless.
