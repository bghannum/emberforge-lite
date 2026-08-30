---
name: emberforge-lite
display_name: Emberforge Lite
description: >-
  Organize, review, link, trim, export, and (only when explicitly authorized)
  generate game-character sprite/animation/sound assets through the local
  Emberforge Lite application.
brand_color: "#38bdf8"
default_prompt: "Use $emberforge-lite to review and organize my actor assets."
---

# Emberforge Lite skill

Use this skill to drive the **local** Emberforge Lite application on the user's
machine through its CLI. Emberforge Lite keeps one folder per game-character
("actor") of sprites, animations, and sounds, serves a review workbench on
loopback, and can generate new assets through provider APIs.

## When to use

- The user wants to organize, review, link sounds to animations, trim a sound,
  rename or delete an asset, or export an actor.
- The user asks to generate a sprite, animation, or sound **and** has explicitly
  authorized spending.

## How to invoke

Everything goes through the installed CLI — never re-implement its logic.

```
emberforge-lite serve [--port 8000] [--data-dir PATH]      # review workbench (offline)
emberforge-lite build [--data-dir PATH]                     # regenerate the static site
emberforge-lite link ACTOR ANIMATION SOUND [--data-dir PATH]
emberforge-lite migrate SOURCE [--data-dir DEST]
emberforge-lite import SOURCE [--data-dir PATH] [--include-deprecated] [--actor SLUG]   # sprite library -> actors
emberforge-lite demo                                        # offline synthetic actor
```

1. **Check the CLI is installed:** run `emberforge-lite --version`. If it is
   missing, tell the user to install it and stop — do **not** install software
   yourself:

   ```
   pipx install git+https://github.com/bghannum/emberforge-lite.git@v0.1.0
   ```

2. **Default to offline.** Run without `--allow-spend`. Reviewing, linking,
   trimming, renaming, and exporting never require credentials or spend.

## Hard constraints

- **Never add `--allow-spend`, submit a generation, delete an asset, or migrate
  data without explicit authorization from the user for that specific action.**
  These spend money or destroy/move data.
- **Never install software silently.** If the CLI or `pipx` is missing, explain
  the documented install step and let the user run it.
- **Never handle API keys.** Credentials come from the user's environment or an
  `--env-file` they control; do not read, print, or write key values.
- Keep this skill self-contained: call the CLI, don't duplicate its scripts or
  documentation.

## Typical offline flow

```
emberforge-lite --version
emberforge-lite build --data-dir ~/emberforge-data
emberforge-lite serve --data-dir ~/emberforge-data     # then open the printed URL
```

Then review actors in the browser, link sounds to animations, trim as needed,
and export an actor when it is ready.
