# Architecture

Emberforge Lite is one folder per actor on disk, one static HTML page per actor,
and a standard-library Python server that reads and writes that folder. No
database, no framework, no runtime dependencies.

## Data flow

```
                 emberforge-lite serve
                          │
          ┌───────────────┼────────────────┐
          │               │                │
      web layer       generation        storage
     (server.py,     (generate.py,      (storage.py,
      build.py,       providers/)       provenance.py,
      static/)                          logs.py)
          │               │                │
          └───────────────┼────────────────┘
                          ▼
                   <data-dir>/
                     actors/<slug>/{sprites,animations,sounds,sheets}
                     actors/<slug>/{links.json,generations.jsonl,provenance.json}
                     site/{gallery.html,actor-<slug>.html}
                     tmp/  logs/
```

A browser action (upload, link, trim, rename, delete, generate) hits the server,
which mutates the actor folder under that actor's lock, rebuilds the affected
static pages from disk, and returns JSON. The page then reloads to show the new
state. Rebuild-from-disk is the single source of truth: the pages are always a
pure function of the folder.

## Modules

| Module | Responsibility |
|---|---|
| `cli.py` | Argument parsing and the `serve`/`build`/`link`/`migrate`/`import`/`demo` commands. |
| `importer.py` | `import`: walk a sprite library, detect each animation folder's layout with an adapter, and write frame packages. |
| `animmeta.py` | Frame-package `manifest.json` model and the README / profile.json / GIF timing parsers with their precedence. |
| `sheets.py` | Compose a package's frames into a near-square grid spritesheet. |
| `config.py` | Resolve the data directory and expose the `actors`/`site`/`tmp` layout. |
| `server.py` | HTTP handler: routing, security guards, upload/mutation endpoints, generation endpoints, export. |
| `build.py` | Render `gallery.html` and `actor-<slug>.html` from the actor tree. |
| `static/` | Packaged `app.css` and `app.js` (event-delegated, CSP-safe). |
| `generate.py` | Estimate → confirm → submit → poll → write → ledger, plus provenance. |
| `providers/` | Provider adapters (`spritelab`, `openai_images`, `elevenlabs`), the deterministic `fakes`, and the shared `base`/`transport` contract. |
| `storage.py` | Per-actor locks, atomic writes, filename reservation, stale-temp cleanup. |
| `provenance.py` | Per-asset `provenance.json` (schema v1). |
| `logs.py` | Structured, redacting local event log. |
| `media.py`, `pngtools.py`, `audiotools.py`, `gifspeed.py`, `naming.py`, `linking.py` | Header-only media validation, PNG fitting, lossless trimming, GIF timing, name hygiene, and link bookkeeping. |

## Animation packages

An animation is either a GIF file (`animations/<name>.gif`) or a **frame
package** — a directory holding ordered PNG frames plus a manifest that records
exactly how long each frame is shown:

```
actors/<slug>/animations/<name>/
  manifest.json     schema_version 1: name, loop, fps_hint, frame_size,
                    frames[{file, delay_ms}], events, resulting_state, source
  frames/frame_00.png ...
actors/<slug>/sheets/<name>_sheet.png     composed grid (row-major), same convention as generated sheets
```

The manifest is the source of truth for timing. A GIF cannot be: its delay
field is in centiseconds, so an authored 35 ms frame becomes 40 ms. The browser
therefore does not decode anything for a package; `app.js` fetches
`manifest.json` and the frames (`GET /actors/<slug>/animations/<name>/{manifest.json,frames/<file>.png}`)
and steps a canvas with an accumulator, holding the last frame when `loop` is
false. Edited delays go through `POST /timing`, which validates the list against
the manifest under the actor lock and marks `source.timing_source` as `edited`.

`emberforge-lite import SOURCE` builds packages from a library laid out as one
folder per character and one per animation. Each animation folder goes to the
first *adapter* whose `detect` accepts it; an adapter returns the ordered frame
files and resolved timing. Only the frames-folder adapter is implemented; the
atlas-grid and GIF adapters are declared stubs so the slot for slicing a sheet or
decoding a GIF is explicit. Timing precedence is README delays (ms, exact) >
`_production/**/*_profile.json` (either `frame_delays_seconds` or
`playback_fps` + `frame_duration_multipliers`, accepted only when its
`animation` names this package) > preview-GIF delays (lossy) > uniform. Folders
suffixed ` (deprecated)` are skipped unless `--include-deprecated`; `_production`
and OS metadata are never imported. Re-running replaces each package in place.

The browser path is `POST /import/<slug>` with a `multipart/form-data` body
whose part filenames are paths relative to the picked folder
(`webkitRelativePath`). The parts are staged under `tmp/` by
`importer.stage_uploaded_files`, which confines every path component, keeps only
frame PNGs, preview GIFs, READMEs, and JSON, and requires a single top-level
folder; the staged folder then goes through `importer.import_folder`, the same
code the CLI uses, and the staging directory is removed whatever happens.

Link, rename, delete, and export treat a package like a GIF animation: links are
keyed by the directory name, `sheet_for` resolves `sheets/<name>_sheet.png`, and
delete removes the directory, its sheet, links, and provenance as one locked step.

## Design constraints

- **Standard library only at runtime.** Media is validated by header/chunk
  parsing, never by decoding pixel data, so a hostile file is bounded before any
  decoder sees it (see [threat-model.md](threat-model.md)).
- **Static page generation**, not a client framework. Pages are regenerated
  from disk after every change.
- **Loopback only.** The server is a local tool, not a hosted service.
