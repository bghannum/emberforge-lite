# Contributing

Thanks for your interest in Emberforge Lite. It is a small, standard-library
Python project; contributions that keep it that way are the easiest to accept.

## Ground rules

- **The installed runtime stays dependency-free.** Everything under
  `src/emberforge_lite/` must import only the Python standard library. Test,
  lint, and packaging tools live in the `dev` extra and never at runtime.
- **No live-provider calls in tests.** The offline fakes exercise the same
  code paths deterministically. Tests must pass with no network and no keys.
- **Supported Python:** 3.9–3.13, macOS and Linux (Windows is best-effort).

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before you open a PR

```bash
ruff format . && ruff check .
pytest
```

Please add or update tests for any behavior change — the suite is the
characterization safety net that lets the internals move without regressing the
workflow. Keep commits focused and describe the *why*, not just the *what*.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the module layout and data
flow, [docs/threat-model.md](docs/threat-model.md) for the security boundary,
[docs/provenance-format.md](docs/provenance-format.md) for the on-disk metadata,
and [docs/providers.md](docs/providers.md) for how provider adapters work.
