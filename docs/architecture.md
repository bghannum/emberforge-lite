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
| `cli.py` | Argument parsing and the `serve`/`build`/`link`/`migrate`/`demo` commands. |
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

## Design constraints

- **Standard library only at runtime.** Media is validated by header/chunk
  parsing, never by decoding pixel data, so a hostile file is bounded before any
  decoder sees it (see [threat-model.md](threat-model.md)).
- **Static page generation**, not a client framework. Pages are regenerated
  from disk after every change.
- **Loopback only.** The server is a local tool, not a hosted service.
