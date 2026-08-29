# Threat model

Emberforge Lite is a **single-user, local-first** tool. This document states
what it defends against and, just as importantly, what it does not.

## Assets worth protecting

- **Provider API keys** (SpriteLab, OpenAI, ElevenLabs) — spending them costs
  real money.
- **Local files** outside the actor tree — source code, Git metadata, other
  files on the machine.
- **Prompts and the spend ledger** — potentially sensitive content the user did
  not intend to publish.
- **Actor assets** — art the user may have rights to but not redistribution
  rights.

## Untrusted inputs

- **Files dropped in by the user** (uploads) and **files returned by providers**
  are both untrusted. Every image and audio file is validated by parsing only
  its header/chunk stream — dimensions, frame counts, durations, and projected
  decode size are bounded *before* any decoder runs, so a decompression-bomb or
  malformed file is rejected without exhausting memory.
- **Request paths and filenames** are sanitized (traversal stripped) and every
  served path is resolved and confined to its permitted root.

## What the server defends against

- **Local files leaking through the server.** Only generated pages, packaged
  static assets, and actor media are servable. Credentials, `.git`, Python
  source, prompts, ledgers, and path-traversal attempts return `404`.
- **DNS rebinding.** The server binds to `127.0.0.1` and rejects a `Host` header
  that is not a loopback name.
- **Cross-site requests / CSRF.** Every state-changing request must carry a
  same-origin `Origin` and a per-process CSRF token minted at startup and
  injected into served pages. A strict CSP (`default-src 'none'`, no external
  origins, no inline scripts) limits what a page can do.
- **Partial or hostile uploads.** Uploads are size-capped (64 MiB default,
  configurable), validated before commit, and written through a temporary file
  with an atomic rename, so a rejected or interrupted upload leaves no state.
- **Corruption from concurrent or interrupted writes.** Per-actor locks and
  atomic temp-file-and-replace writes ensure a reader sees only the old or the
  new complete file; the append-only ledger tolerates only an interrupted final
  line.
- **Accidental double-spend.** An animation job is reserved under the actor lock
  before submission, and every generate call must echo the exact estimate it was
  shown.

## Out of scope (explicit non-goals)

- **Multi-user or hosted operation.** There is no authentication, no
  authorization, and no tenant isolation. Do not expose the server beyond a
  trusted local machine. If you do, rotate your provider keys.
- **Defending a compromised local account.** Anything running as the user can
  read the data directory and environment.
- **Protecting against the provider.** Rights and charges are recorded as the
  provider reports them; verify provider terms yourself (see
  [providers.md](providers.md)).
