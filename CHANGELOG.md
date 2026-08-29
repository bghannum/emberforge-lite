# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-29

### Added

- Installable package with an `emberforge-lite` console entry point and the
  subcommands `serve`, `build`, `link`, `migrate`, and `demo`.
- A single per-user data directory (`--data-dir`, `EMBERFORGE_DATA_DIR`, or a
  platform default) holding `actors/`, `site/`, and `tmp/`.
- Per-actor asset provenance (`provenance.json`, schema v1) and a UI badge that
  marks each asset generated / uploaded / rights-unknown.
- Structured, redacting local event log.
- An offline `demo` (the owned `evil-treant` sample actor) requiring no network or credentials.
- Packaged static CSS/JS served at `/static/`; a strict Content-Security-Policy;
  in-page toast and modal replacing browser dialogs.
- MIT license, security policy, contributing guide, and architecture, threat
  model, provenance, provider, and release documentation.

### Changed

- HTTP server rewritten with an explicit route allowlist, loopback `Host`
  checks, CSRF + same-origin guards on mutations, security headers, upload
  validation with atomic commits, and streamed exports.
- Per-actor locks and atomic writes for every multi-file mutation; the
  generation ledger reports malformed records and tolerates only an interrupted
  final line; concurrent animation confirmations submit at most once.
- Credentials are read only from the environment or an explicit `--env-file`;
  the repository is never searched for a `.env`.

### Deprecated

- Root `server.py`, `build.py`, and `link.py` are thin launchers that forward to
  the CLI; they are retained through `v0.1.x` and will be removed in `v0.2.0`.

[Unreleased]: https://github.com/bghannum/emberforge-lite/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bghannum/emberforge-lite/releases/tag/v0.1.0
