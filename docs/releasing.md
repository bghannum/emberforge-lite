# Releasing

Emberforge Lite is installed from a tagged GitHub release with `pipx`; it is not
published to PyPI for `v0.1.0`.

## Prerequisites (owner tasks)

Before tagging a public release, complete the owner-only checks in the
[productionization plan](productionization-plan.md) §10: licensing review,
provider-terms review, credential hygiene (rotate keys if the server was ever
exposed), and showcase approval.

## Build

Because a deprecated root `build.py` launcher exists, `python -m build` in the
repo root imports that shim instead of the PyPA build tool. Build with the
`pyproject-build` console script, which does not put the working directory on
`sys.path`:

```bash
pip install build
pyproject-build            # writes dist/*.whl and dist/*.tar.gz
```

## Verify a clean install

```bash
python3 -m venv /tmp/efl-check && /tmp/efl-check/bin/pip install dist/emberforge_lite-*.whl
/tmp/efl-check/bin/emberforge-lite demo      # runs offline, no keys
```

## Tag and release

1. Update `CHANGELOG.md` and the version in `pyproject.toml`.
2. Create a signed tag: `git tag -s v0.1.0 -m "v0.1.0"` and push it.
3. CI re-runs, builds the wheel and sdist, generates checksums, and attaches the
   artifacts to a GitHub Release.
4. Installation for users:

   ```bash
   pipx install git+https://github.com/bghannum/emberforge-lite.git@v0.1.0
   ```

Keep PyPI publishing disabled for `v0.1.0`. Protect `main` with required CI once
the workflow lands.
