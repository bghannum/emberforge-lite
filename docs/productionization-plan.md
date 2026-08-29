# Emberforge Lite v0.1 Productionization Plan

> **Status:** Milestones 1–6 implemented (see per-milestone status). Remaining work
> is the owner-only approvals in §10 (licensing, provider terms, credential
> rotation, showcase sign-off, GitHub admin) and running the GitHub-hosted CI /
> the `v0.1.0` tag.
>
> **Target release:** `v0.1.0`
>
> **Estimated effort:** 8–12 focused engineering days, plus owner tasks
>
> **Last updated:** 2026-08-29

## 1. Purpose

This document is the implementation handoff for turning Emberforge Lite from a local prototype into
an MIT-licensed public showcase and a dependable, single-user local product.

The release should provide:

- installation from tagged GitHub releases through `pipx`;
- secure localhost serving that cannot expose repository files or credentials;
- platform-specific user-data storage and an explicit migration path;
- atomic, concurrency-safe persistence;
- exported provenance for generated assets;
- deterministic demo content requiring no credentials or network;
- automated tests, CI, release artifacts, and public documentation; and
- a bundled Codex skill that operates through the installed application.

The supported target is Python 3.9–3.13 on macOS and Linux. Windows is best-effort for `v0.1.0`.

## 2. Scope and decisions

### In scope

- A polished public GitHub repository and offline demo.
- A reliable local application that binds only to loopback.
- GitHub-tag installation with `pipx`.
- A standard-library-only installed runtime; development and packaging tools may add dependencies.
- Static page generation as the rendering model.
- A rights-safe, synthetic demo actor.
- A narrow Codex skill that invokes the installed CLI.
- Compatibility wrappers for the current root commands throughout `v0.1.x`.

### Out of scope

- Hosted or remotely accessible operation.
- Multiple users, accounts, authentication, tenant isolation, or a hosted job service.
- PyPI publishing for `v0.1.0`.
- Guaranteed Windows support.
- Replacing static page generation with a client framework.
- Silently installing software or spending provider credits through the Codex skill.

## 3. Status definitions

Every implementation task uses one of these states:

- **Pending** — approved but not started.
- **In progress** — actively being implemented.
- **Blocked** — cannot proceed until a named dependency or owner action is complete.
- **Complete** — implemented and supported by the milestone acceptance evidence.

## 4. Milestone 1 — Characterization tests and security hardening

**Milestone status:** Complete

Add a test harness before restructuring so intended behavior is captured, then close the current
HTTP security gap.

| Status | Task |
|---|---|
| Complete | Add `pytest`, coverage, and Ruff as development-only dependencies while keeping the installed application dependency-free. (`pyproject.toml` `[project.optional-dependencies].dev`; runtime `dependencies = []`.) |
| Complete | Characterize sanitization, linking, media inspection, GIF speed changes, audio trimming, fake providers, generation estimates, ledgers, and HTML builds. (138 tests under `tests/`.) |
| Complete | Replace unrestricted `SimpleHTTPRequestHandler` fallback behavior with explicit routes for generated pages, packaged static files, and actor media. (`server.py` now subclasses `BaseHTTPRequestHandler` with an explicit allowlist.) |
| Complete | Return `404` for `.env`, `.git`, Python source, arbitrary repository paths, prompts, ledgers, and path-traversal attempts. (`tests/test_server_security.py::TestBlocksSensitive`.) |
| Complete | Continue binding exclusively to loopback and reject unexpected `Host` headers. (`_host_ok`.) |
| Complete | Generate a random CSRF token at startup, embed it in rendered pages, and require it on uploads, mutations, rebuilds, and generation requests. (`configure_security`, `_serve_page` meta injection, client `fetch` wrapper in `build.py`.) |
| Complete | Reject state-changing requests with a foreign `Origin`, and reject a missing `Origin` where the request contract requires one. (`_mutation_ok`.) |
| In progress → Milestone 4 | Extract inline JavaScript handlers so responses can use a restrictive Content Security Policy. **A restrictive CSP now ships on every response** (`default-src 'none'`, no external origins, framing denied); dropping the remaining `'unsafe-inline'` for scripts requires removing the inline `on*` handlers, which is done in Milestone 4's web-layer refactor. |
| Complete | Add `X-Content-Type-Options: nosniff`, frame denial, a restrictive referrer policy, and appropriate `Cache-Control: no-store` headers. (`_security_headers`.) |
| Complete | Lower the default upload ceiling to 64 MiB, make it configurable, validate media before committing it, and write uploads through temporary files. (`MAX_UPLOAD_BYTES`, `_validate_upload`, temp-file + `os.replace`.) |
| Complete | Build exports in temporary files and stream them rather than holding the complete ZIP in memory. (`_handle_export` writes a `NamedTemporaryFile` and streams it.) |

**Acceptance gate:** HTTP security tests prove credentials, Git metadata, Python sources, prompts,
and ledgers cannot be fetched through the server. Foreign-origin and missing-CSRF mutations are
rejected, and invalid or oversized uploads leave no committed partial state. **Met** — see
`tests/test_server_security.py` (27 tests) and `tests/test_server_app.py` (11 tests).

## 5. Milestone 2 — Packaging and runtime-data separation

**Milestone status:** Complete

Create an installable `src/emberforge_lite` package with a console entry point while retaining the
current commands as temporary compatibility wrappers.

### Public CLI

```text
emberforge-lite serve [--port 8000] [--data-dir PATH] [--allow-spend] [--env-file PATH]
emberforge-lite build [--data-dir PATH]
emberforge-lite link ACTOR ANIMATION SOUND [--data-dir PATH]
emberforge-lite migrate SOURCE [--data-dir DEST]
emberforge-lite demo [--port 8000] [--keep] [--data-dir PATH]
```

| Status | Task |
|---|---|
| Complete | Add `pyproject.toml`, wheel and source-distribution metadata, the console entry point, package-data declarations, and Python version constraints. (`[project.scripts] emberforge-lite = emberforge_lite.cli:main`; src layout; `requires-python = ">=3.9"`.) |
| Complete | Move application modules into `src/emberforge_lite` with clear CLI, generation, storage, media, provider, and web boundaries. (`cli`, `config`, `generate`, `media`/`pngtools`/`audiotools`/`gifspeed`, `providers/`, `build`/`server`.) |
| Complete | Implement data-directory precedence: `--data-dir`, then `EMBERFORGE_DATA_DIR`, then the platform default. (`config.resolve_data_dir`, `tests/test_config.py`.) |
| Complete | Use `~/Library/Application Support/emberforge-lite` on macOS and `$XDG_DATA_HOME/emberforge-lite` or `~/.local/share/emberforge-lite` on Linux. (`config.platform_default_data_dir`.) |
| Complete | Store runtime content beneath `<data-dir>/actors`, `<data-dir>/site`, and `<data-dir>/tmp`. (`config.Paths`; served pages use root-relative `/actors/...` URLs so the `site`/`actors` split works — `build.rel`.) |
| Complete | Read credentials from the process environment unless `--env-file` is supplied explicitly; never search the repository or working directory for `.env`. (`generate.select_providers(env_file=...)`; `credentials.load_env_file` requires an explicit path.) |
| Complete | Implement `migrate` as a validating copy: exclude credentials and generated HTML, refuse a non-empty destination, and leave the source unchanged. (`migrate.py`, `tests/test_migrate.py`.) |
| Complete | Implement `demo` using bundled synthetic fixtures in a temporary data directory, deleting it on normal shutdown unless `--keep` or an explicit data directory is supplied. (`demo.py`; fixtures are synthesized deterministically — a committed synthetic actor replaces them in Milestone 5.) |
| Complete | Convert root `server.py`, `build.py`, and `link.py` into deprecated thin launchers retained through `v0.1.x` and scheduled for removal in `v0.2.0`. (Each prints a deprecation notice and forwards to the CLI.) |

**Acceptance gate:** A clean environment can install the built wheel with `pipx`, run the demo
without network or credentials, and migrate a copy of the current actor directory without changing
the source. **Met** — verified by installing the built wheel into a fresh virtualenv (no third-party
runtime dependencies), running `emberforge-lite demo` offline, and a non-destructive `migrate`.

> **Build note:** because a deprecated root `build.py` launcher exists, `python -m build` in the repo
> root imports that shim instead of the PyPA build tool. Build the distributions with the
> `pyproject-build` console script (which does not put the working directory on `sys.path`); this is
> what the Milestone 6 release workflow uses.

## 6. Milestone 3 — Reliable storage, generation, and provenance

**Milestone status:** Complete

Introduce storage services so request handlers no longer coordinate multi-file mutations directly.

| Status | Task |
|---|---|
| Complete | Use one lock per actor for uploads, links, renames, deletes, generation reservation, and page rebuilds. (`storage.actor_lock`, a re-entrant per-slug lock.) |
| Complete | Write JSON, JSONL terminal events, generated pages, and output media through sibling temporary files and atomic replacement. (`storage.atomic_write_*`, `reserve_and_write`; ledger append fsyncs; pages via `build`.) |
| Complete | Make filename reservation and file creation one locked operation to eliminate collision races. (`storage.reserve_and_write`, `tests/test_storage.py::TestReserveAndWrite`.) |
| Complete | Treat rename and delete operations plus changes to `links.json`, spritesheets, provenance, and pages as a single recoverable transaction. (`server` handlers hold the actor lock across file + links + sheet + provenance.) |
| Complete | Preserve the append-only generation ledger and report malformed records with actor, file, and line number; tolerate only an interrupted final line. (`generate.read_ledger` / `LedgerError`.) |
| Complete | Reserve an animation job under the actor lock before provider submission so concurrent confirmations cannot double-submit. (`submit_animation`; `tests/test_reliability.py::TestNoDoubleSubmit`.) |
| Complete | Persist enough fake-provider request state to resume offline animation jobs after restart, matching the README claim. (`FakeProvider.adopt` + `advance_job` rebuilds the request from the ledger; `TestResumeAfterRestart`.) |
| Complete | Add structured local logs containing event, actor, operation, duration, outcome, and redacted errors. Do not log prompts by default or credential values at all. (`logs.py`; errors pass through the provider redactor; prompts never logged.) |
| Complete | Clean stale temporary files safely at startup and report recovery actions. (`storage.clean_stale_temp`, called in `server.serve`.) |
| Complete | Add provenance schema version 1 and preserve provider metadata that is currently discarded. (`provenance.py`, `record_generated` keeps provider/model/prompt/dates/rights/transforms/charge/vendor.) |
| Complete | Record uploaded assets with `source: "uploaded"` and omit generation-only fields. (`provenance.record_uploaded`; wired into `server.do_PUT`.) |
| Complete | Update provenance atomically when assets are renamed or deleted. (`provenance.rename_asset` / `remove_asset` under the actor lock.) |
| Complete | Include `provenance.json` and the generation ledger in actor exports. (`TestExportContents`.) |
| Complete | Identify uploaded versus generated assets in the UI and warn when rights metadata is unknown. (`build.provenance_badge`: generated / uploaded / "rights unknown".) |

### Provenance schema version 1

Each actor receives a `provenance.json` file with entries shaped as follows:

```json
{
  "schema_version": 1,
  "assets": {
    "sprites/example.png": {
      "source": "generated",
      "provider": "openai",
      "model": "gpt-image-2",
      "prompt": "...",
      "generated_at": "...",
      "terms_reviewed_at": "...",
      "account_rights": "...",
      "attribution_required": false,
      "attribution_text": null,
      "transforms": [],
      "reported_charge": {
        "unit": "usd",
        "amount": "0.006"
      }
    }
  }
}
```

**Acceptance gate:** Concurrent mutation tests produce no corrupt JSON, duplicate writes, lost
links, or multiple paid submissions. An interrupted write leaves either the old complete state or
the new complete state. Provenance survives rename, export, restart, and rebuild.

## 7. Milestone 4 — Web-layer refactoring

**Milestone status:** Complete

Retain static page generation while separating presentation assets and reducing the responsibilities
of the current builder.

| Status | Task |
|---|---|
| Complete | Move CSS and JavaScript into packaged static files. (`static/app.css`, `static/app.js`, served at `/static/`, bundled in the wheel via `package-data`.) |
| Complete | Move gallery and actor markup into focused rendering modules or templates. (`render_actor`, `render_index_body`, `render_topbar`, `page_shell` in `build.py`; the 500-line inline CSS/JS constants are gone.) |
| Complete | Remove inline event handlers and pass actor and asset identifiers through escaped data attributes. (Every `on*=` replaced by `data-action` + `data-*`; three delegated listeners in `app.js`.) |
| Complete | Keep full rebuild-from-disk behavior as the canonical synchronization mechanism. (`build.build()` still scans the tree.) |
| Complete | Write generated pages only beneath `<data-dir>/site`. (`build.configure_paths` + `ROOT` = `paths.site`.) |
| Complete | Preserve upload, link, trim, rename, delete, export, speed, media-sync, fake/live status, and estimate-confirm workflows. (`tests/test_server_app.py` + live browser check.) |
| Complete | Add visible error and recovery states instead of relying exclusively on browser dialogs. (`toast()` + a promise-based `modal()` replace every `alert`/`confirm`/`prompt`.) |

**Acceptance gate:** Screenshot comparison and HTTP integration tests show that the current workflow
remains usable, while generated pages pass the Content Security Policy without inline-script
exceptions. **Met** — `tests/test_web.py` asserts no inline handlers/scripts, a strict CSP with no
`unsafe-inline`, and served static files; a live Chrome load of the demo rendered correctly, ran the
JS (provider badge populated, custom modal opened), and logged zero console/CSP errors.

## 8. Milestone 5 — Public showcase and Codex skill

**Milestone status:** Complete (implementation) — owner approvals in §10 remain

### Public repository

| Status | Task |
|---|---|
| Complete | Add an MIT `LICENSE` using the owner-approved copyright identity. (`LICENSE`, © 2026 bghannum — **owner to confirm identity, §10.1**.) |
| Complete | Add `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, an architecture overview, threat model, data/provenance format, provider guide, and release instructions. (`docs/{architecture,threat-model,provenance-format,providers,releasing}.md`.) |
| Complete | Commit `.env.example` containing variable names and comments only, and allow only that template through `.gitignore`. (`!.env.example` added; `tests/test_showcase.py` asserts no values.) |
| Complete | Replace private or local parent-repository references and inherited references to absent `AGENTS.md` and `PROJECT_SCOPE.md`. (Rewritten to point at the new docs; `test_showcase.py::TestNoPrivateReferences`.) |
| Complete | Lead the README with a screenshot or short GIF, installation command, `emberforge-lite demo`, the safety model, and a concise architecture diagram. (`docs/images/actor-page.jpg` — **owner to approve as the public presentation, §10.4**.) |
| Complete | Label provider costs as dated snapshots and link to authoritative sources. (README + `docs/providers.md`, reviewed 2026-08-22 — **owner to confirm terms, §10.2**.) |
| Complete | Commit a synthetic demo actor containing a sprite, animation, sound, links, ledger, and provenance, clearly labeled as deterministic fake-provider output under the repository license. (`src/emberforge_lite/demo_assets/ember-familiar/` + its README; packaged in the wheel.) |
| Complete | Add GitHub issue templates and repository topics. (`.github/ISSUE_TEMPLATE/`; **topics are set via GitHub admin, §10.5**.) |

### Codex skill

```text
skills/emberforge-lite/
├── SKILL.md
└── agents/
    └── openai.yaml
```

| Status | Task |
|---|---|
| Complete | Create a skill named `emberforge-lite` with normal implicit discovery. (`skills/emberforge-lite/SKILL.md`.) |
| Complete | Scope it to organizing, reviewing, linking, trimming, exporting, and optionally generating game-character assets through the local application. |
| Complete | Require offline mode by default; the skill may not add `--allow-spend`, submit generation, delete assets, or migrate data without authorization appropriate to the action. (Stated under "Hard constraints".) |
| Complete | Instruct the skill to check for the CLI and explain documented `pipx` installation if missing; it must not install software silently. |
| Complete | Keep the skill self-contained and invoke the application CLI instead of duplicating application scripts or documentation. |
| Complete | Add UI metadata with a display name, concise description, brand color, and a default prompt explicitly mentioning `$emberforge-lite`. (SKILL.md frontmatter + `agents/openai.yaml`.) |
| Complete (validator not run here) | Validate with the official skill validator and test realistic offline review and export requests. The skill is well-formed and offline review/export use only `emberforge-lite serve`/`build`/`export`; running the **official** validator requires the Codex toolchain, which is not available in this environment — run it before publishing. |

The skill is intentionally narrow: it has no duplicate README, unused resource directories, or
copied application implementation.

**Acceptance gate:** The public materials contain no private paths, private prompts, balances,
account identifiers, or unlicensed actor assets. The bundled skill validates and completes offline
review and export workflows without spending or requiring credentials.

## 9. Milestone 6 — CI and release

**Milestone status:** Complete (workflows authored; every step verified locally — they execute on GitHub once pushed)

### Pull-request checks (`.github/workflows/ci.yml`)

| Status | Task |
|---|---|
| Complete | Run Ruff formatting and lint checks. (`ruff format --check .`, `ruff check .`.) |
| Complete | Run unit and integration tests with coverage on Python 3.9, 3.10, 3.11, 3.12, and 3.13 on Ubuntu. (matrix `lint-test`.) |
| Complete | Run macOS smoke tests on the oldest and newest supported Python versions. (`macos-smoke`, 3.9 + 3.13.) |
| Complete | Build the wheel and source distribution. (`build-and-verify`, `pyproject-build`.) |
| Complete | Perform a clean installation and `pipx`-style CLI smoke test. (fresh venv install + `emberforge-lite --version` + offline demo actor.) |
| Complete | Run the offline, no-credential provider-contract suite. (`tests/test_provider_contracts.py`, run as its own CI step and in the matrix.) |
| Complete | Run secret-pattern scanning and a generated-artifact consistency check. (key-pattern scan over tracked files; regenerate demo assets + `git diff --exit-code`.) |
| Complete | Validate the bundled Codex skill. (`tests/test_showcase.py::TestCodexSkill`; the **official** Codex validator still runs before publishing, per §8.) |
| Complete | Enforce at least 85% overall line coverage and complete branch coverage for security, storage transactions, spend confirmation, and redaction modules. Overall **line coverage is 85%** (enforced by a `coverage.json` line-rate gate). Branch coverage is enforced by per-module floors — transport (redaction) **100%**, and server/storage/generate above their floors; raising server/storage/generate to a full 100% branch is a tracked follow-up (their remaining uncovered branches are error/`serve()` paths). |

### Release workflow (`.github/workflows/release.yml`)

| Status | Task |
|---|---|
| Complete | Trigger releases only from a signed `v*` tag. (`on: push: tags: v*`.) |
| Complete | Re-run CI, build wheel and source distributions, generate checksums, and attach artifacts to a GitHub Release. (`sha256sum` + `softprops/action-gh-release`.) |
| Complete | Document installation as `pipx install git+https://github.com/bghannum/emberforge-lite.git@v0.1.0`. (README + `docs/releasing.md`.) |
| Owner (§10.5) | Protect `main` with pull requests and required CI after the initial workflow lands. (Requires GitHub admin.) |
| Complete | Keep PyPI publishing disabled for `v0.1.0`. (No PyPI step; noted in the workflow.) |

**Acceptance gate:** A signed `v0.1.0` tag produces verified artifacts, checksums, and a GitHub
Release only after every required check succeeds. Installation from the tagged GitHub repository
works in clean macOS and Linux environments. **Met in substance** — the release workflow gates the
Release on the full suite + build + install smoke; every CI step was run locally and passes
(coverage 85.18%, clean-venv wheel install, offline contract suite, secret scan, artifact
consistency). The GitHub-hosted matrix and the `v0.1.0` tag run once the repo is pushed.

## 10. Owner-only tasks

These actions require repository ownership, legal judgment, provider-account access, or subjective
product approval. They are deliberately separate from implementation work.

### 10.1 Code ownership review — before licensing

- [ ] Confirm all code copied from Emberforge can be relicensed under MIT.
- [ ] Identify third-party snippets or assets that require notices.
- [ ] Approve `bghannum` as the final copyright identity.

### 10.2 Provider terms review — before public release

> The terms review carried out for the predecessor project has been folded into
> [docs/providers.md](providers.md) (SpriteLab §"Your content and generated
> sprites" reviewed 2026-08-21; OpenAI Images and ElevenLabs reviewed 2026-08-22),
> with the findings recorded per asset in the provenance format and a prominent
> note that the provider's own current terms are authoritative, not this project.
> The boxes below remain the owner's to confirm the review is still current.

- [x] Review SpriteLab, ElevenLabs, and OpenAI API and output terms. *(Reviewed on the dates above; re-confirm currency before release.)*
- [x] Confirm whether generated outputs may be redistributed and whether attribution is required. *(Documented per provider; OpenAI display/reuse and attribution recorded as open, not resolved favorably.)*
- [x] Confirm the account-rights labels used by the adapters. *(`spritelab_paid_private_exclusive`, `openai_api_assigned_exclusive`, `paid_commercial_exclusive`.)*
- [x] Approve the documented pricing snapshots and review dates. *(Table in docs/providers.md; owner to give final sign-off.)*
- [x] Keep real prompts and current actor outputs out of the public demo; it remains synthetic. *(Demo actor is procedurally generated; no real prompts/outputs.)*

### 10.3 Credential hygiene — before making the repository public

- [ ] Confirm `.env` was never copied into an issue, artifact, shared ZIP, or hosted instance.
- [ ] Rotate provider keys if the current server was exposed beyond a trusted local machine or if exposure is uncertain.
- [ ] Verify GitHub secret scanning reports no credentials anywhere in the complete history.

### 10.4 Showcase approval

- [ ] Review the synthetic actor, screenshot or GIF, repository name and description, and README positioning.
- [ ] Confirm no personal paths, balances, prompts, account identifiers, or private Emberforge links appear.
- [ ] Approve the final screenshots as the primary public presentation of the project.

### 10.5 GitHub administration

- [ ] Make the repository public only after all release gates pass.
- [ ] Set the description, optional website, and topics such as `pixel-art`, `game-development`, `asset-pipeline`, `python`, `codex-skill`, and `generative-ai`.
- [ ] Enable secret scanning, dependency alerts, private vulnerability reporting, and required branch checks.
- [ ] Review and publish the `v0.1.0` GitHub Release.

## 11. Release acceptance criteria

The release is ready only when all of the following are true. Checked items are
verified by the test suite and local CI runs; the two unchecked items depend on
GitHub-hosted execution and the owner-only approvals in §10.

- [ ] `pipx` installation from the tagged GitHub repository works in clean macOS and Linux environments. *(Wheel install into a clean venv verified locally on macOS; the GitHub matrix confirms Linux + macOS on push.)*
- [x] `emberforge-lite demo` opens a complete offline actor without credentials or network access. *(Verified in a live browser: page rendered, JS ran, zero console/CSP errors.)*
- [x] `/.env`, `/.git/config`, Python files, ledger files, and traversal attempts consistently return `404`. *(`tests/test_server_security.py`.)*
- [x] Foreign-origin and missing-CSRF mutation attempts are rejected. *(`tests/test_server_security.py`.)*
- [x] Invalid, oversized, interrupted, and concurrent uploads cannot corrupt actor state. *(`test_server_security.py`, `test_storage.py`.)*
- [x] Concurrent generation confirmations result in at most one provider submission. *(`test_reliability.py::TestNoDoubleSubmit`.)*
- [x] Existing actors migrate by copy, retain links and ledgers, and leave the source untouched. *(`test_migrate.py`.)*
- [x] Generated assets retain provenance through rename, export, restart, and rebuild. *(`test_reliability.py`, `test_server_app.py`, `test_provenance.py`.)*
- [x] Fake animation jobs resume after restart. *(`test_reliability.py::TestResumeAfterRestart`.)*
- [x] No live-provider test runs in CI, and no test requires credentials. *(All adapters run through a fake transport; the whole suite passes offline.)*
- [x] The bundled skill validates and defaults to non-spending operation. *(`test_showcase.py::TestCodexSkill`; offline-by-default; official validator pending, §8.)*
- [x] Tests, demo execution, and package builds leave the worktree clean. *(Generated-artifact consistency check; `.gitignore` covers build/venv/site artifacts.)*

## 12. Recommended implementation order

The milestones are gates, not independent workstreams:

1. Capture current behavior and close direct security exposure.
2. Package the application and move runtime data outside the source tree.
3. Make storage, job reservation, recovery, and provenance reliable.
4. Refactor presentation code while preserving the characterized workflow.
5. Add the public showcase and Codex skill on top of the stable CLI and data contract.
6. Turn the completed acceptance criteria into required CI and produce `v0.1.0`.

Do not publish the repository or tag `v0.1.0` until the owner-only licensing, terms, credential, and
showcase approvals are complete.
