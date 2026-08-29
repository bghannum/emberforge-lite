# emberforge-lite

A small, dependency-free tool for reviewing pixel-art game characters: for
each actor, see its sprites and animations, hear each sound *against* the
animation it belongs to, and generate new ones through the provider APIs —
without leaving the page.

It is one folder per actor on disk, one static page per actor, and a
stdlib-only Python server that reads and writes that folder. No database, no
framework, no `pip install`. Python 3.9+.

## Project status

Emberforge Lite is currently a local-first prototype being prepared for its first public release.
The approved security, packaging, reliability, showcase, and release work is tracked in the
[v0.1 productionization plan](docs/productionization-plan.md). Hosted multi-user operation is not
part of that plan.

## Quick start

```bash
python3 server.py            # http://127.0.0.1:8000/  (offline: fake providers)
python3 server.py --allow-spend   # same, with the real SpriteLab / ElevenLabs / OpenAI APIs
```

Open the URL, type a slug in the **new actor** box (e.g. `gravescribe`),
pick some files, and you have an actor page. Everything else happens on that
page.

## What's on an actor page

- **Upload** — drop or pick files; they are sorted by extension (`.gif` →
  `animations/`, other images → `sprites/`, audio → `sounds/`). Names are
  sanitised; a collision gets a `-2` suffix rather than overwriting.
- **Sprites** — the still images.
- **Animations** — the centre of the page. Each card has:
  - a **Speed** dial (1× … 0.25×) that rewrites the GIF's frame delays on the
    fly so you can watch it at the rate the game will run it — the file on
    disk is untouched;
  - one **▶ Play with sound** pill per linked sound, which restarts the GIF
    from frame 0 in lockstep with the audio;
  - **✂ trim** and **× unlink** on each pill, a **link a sound** picker for
    the actor's unlinked sounds, and a **sheet** download if the animation
    came with a spritesheet.
- **Unlinked sounds** — audio not yet paired with anything, each with a
  player and a trim button so nothing gets lost.
- **Rename / delete** on every asset. Deleting or renaming keeps `links.json`
  and any sibling spritesheet in step. Deletes are permanent (there is a
  confirm, no undo).
- **Export** — a zip of the whole actor folder.
- **Generate** — see below.

Every change rebuilds the pages in-process, so what you see is what is on
disk.

## Generate instead of upload

The **Generate** panel has three tabs. They call the same provider adapters
[emberforge](../emberforge) uses, copied in verbatim (they were already pure
stdlib), minus its brief/approval workflow.

| tab | provider | writes | cost |
|---|---|---|---|
| Animate a sprite | SpriteLab `/animate` | `animations/<actor>_<action>_preview.gif` + `sheets/<actor>_<action>_sheet.png` | 20 credits |
| Sound | ElevenLabs sound effects | `sounds/<actor>_<name>.mp3`, optionally linked to an animation | 40 credits/s requested (800 ms → 32) |
| Source sprite | SpriteLab `/generate` · OpenAI `gpt-image-2` | `sprites/<actor>_source_<provider>.png` | 1 credit (epic) / 6 (mythic) · $0.006 |

**Nothing is spent without two deliberate steps.** The server must be started
with `--allow-spend` — otherwise deterministic fakes answer, and the badge
says so — and every call is **Estimate → Confirm**: Estimate shows the exact
amount (plus the balance where the provider has a free endpoint for it, and
the filename that will be written); Confirm echoes that amount back, and the
server refuses if the estimate has changed underneath it.

Credentials go in `.env` (gitignored) or the environment:

```
SPRITELAB_API_KEY=...
OPENAI_API_KEY=...
ELEVENLABS_API_KEY=...
```

They are never echoed and never reach the browser. A provider without a key
is greyed out.

Worth knowing:

- SpriteLab `/animate` accepts at most 256 px per axis and returns exactly the
  canvas it is given, so the chosen sprite is first fitted onto a 256×256
  canvas with a 16 px margin (nearest-neighbour, content bottom-aligned; the
  same geometry as emberforge's `transforms.py`, reimplemented in
  `pngtools.py`). Generated animations are 256×256 — the web UI's preview
  downloads are 314×314.
- SpriteLab animates at 8 fps. Its web-UI preview GIFs are encoded faster
  (which is why hand-downloaded ones "play a bit fast"); the API's are not.
  Anything fetched from the API has its delays normalised to 8 fps on ingest,
  proportionally, so the ease-out survives. Uploaded files are never modified.
- Animation jobs take 30–90 s. The page polls; the job is recorded before the
  first poll, so if you close the tab or restart the server the actor page
  offers to resume it.
- `actors/<slug>/generations.jsonl` is the audit trail: one line when a call
  is submitted, one when it succeeds, fails, or ends *ambiguous* (the
  provider errored after possibly charging). Nothing is ever auto-retried.
- ElevenLabs' published rate (40 credits/s) is used as the ceiling in the
  estimate; the endpoint has been observed to bill less. The ledger records
  what it actually reported.

## On disk

```
actors/<slug>/
  sprites/            .png .jpg .jpeg .webp
  animations/         .gif
  sounds/             .mp3 .wav .ogg .m4a
  sheets/             spritesheets that came with generated animations (not shown as cards)
  links.json          {"animation.gif": ["sound.mp3", ...]}
  generations.jsonl   append-only log of every provider call
gallery.html          generated index (gitignored)
actor-<slug>.html     generated actor page (gitignored)
.env                  provider keys (gitignored)
```

`actors/` is gitignored: it is private art, paid output, and your prompts.
The folder itself is kept via `actors/.gitkeep`.

Everything can also be driven by hand — drop files into the folders and run
`python3 build.py`; link with `python3 link.py <slug> <animation> <sound>` or
edit `links.json` directly. `build.py` is a full rebuild from disk every time,
so there is nothing to fall out of sync.

## Code map

| file | role |
|---|---|
| `server.py` | `ThreadingHTTPServer`; static files plus JSON routes for upload, link/unlink, rename, delete, trim, speed, export, and generation |
| `build.py` | scans `actors/` and writes `gallery.html` + `actor-<slug>.html`; all markup, CSS and JS live here as templates |
| `generate.py` | estimate → confirm → submit → poll → write; picks fakes or live adapters; owns the ledger |
| `providers/` | adapters copied from emberforge: `spritelab`, `openai_images`, `elevenlabs`, `fakes`, shared `base`/`transport` |
| `media.py` | header-only PNG/GIF/WAV/MP3 inspection with size bounds (from emberforge) |
| `pngtools.py` | stdlib PNG decode → alpha-bbox → nearest-neighbour fit → encode |
| `gifspeed.py` | GIF frame-delay rewriting: `slow_gif` for the speed dial, `set_fps` for ingest |
| `audiotools.py` | WAV sample-exact and MP3 frame-boundary trimming, no re-encode |
| `linking.py` | all `links.json` edits, shared by `link.py` and the server |
| `credentials.py` | `.env` shim; reports which keys exist, never their values |
| `naming.py` | slug/filename sanitising and collision-safe paths |

## What it isn't

Split off from emberforge on 2026-08-28 because its brief/approval/cost-ledger
workflow got in the way of the one thing that mattered: looking at what had
been generated and hearing whether a sound fit. This tool keeps emberforge's
adapters and its spend discipline (explicit arming, per-call confirmation,
an append-only ledger) and drops everything else. It has no opinion about
provenance or rights, no multi-user story, and binds to localhost with no
auth — it is a personal workbench, not a service.
