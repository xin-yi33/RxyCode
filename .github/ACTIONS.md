# GitHub Actions

The workflows in this directory make the test and distribution paths exercise
the installed application instead of a checkout-specific import shim.

## Continuous integration

`workflows/ci.yml` runs on pushes, pull requests, and manual dispatches. The
weekly schedule is reserved for the opt-in live-provider lane.

Both Linux and Windows jobs install runtime and development dependencies, then
install the checkout with:

```console
python -m pip install -e . --no-deps
```

This editable install creates the real `RxyCode.RxyCode1_1_0` package namespace
from `pyproject.toml`; CI does not create namespace symlinks or Windows
junctions. Each platform also builds a wheel with `python -m build --wheel
--no-isolation`, validates its metadata with `twine check`, installs it without
dependencies into a temporary `--system-site-packages` virtual environment,
clears `PYTHONPATH`, and executes the console/module version entrypoints, help,
and a fresh-home non-TTY session through `/exit`. These checks prove that the
packaged command works independently of the source tree and does not terminate
before entering the first-run UI.

The existing test lanes remain in place:

- Linux runs unit, integration, contract, serial, and legacy regression tests,
  combines their coverage data, and enforces both coverage thresholds.
- Windows runs backend contract/system tests, the frontend build and Vitest
  suite, the cross-shell installer/package contracts, and the real ConPTY
  end-to-end tests.
- Live-provider tests run only on the weekly schedule or a manual dispatch with
  `run_live=true`; missing credentials fail before a network call.

All jobs upload their existing diagnostics even when a test step fails.

## Releases

`workflows/release.yml` runs only when a tag matching `v*` is pushed. It:

1. requires the tag without its leading `v` to equal `[project].version` in
   `pyproject.toml`;
2. builds both the wheel and source distribution without build isolation and
   runs `twine check`;
3. installs the produced wheel in temporary Linux and Windows environments and
   executes the packaged `rxycode` command with `--version` and `--help`;
4. after both platform checks pass, uses the preinstalled GitHub CLI to create a
   GitHub Release and upload the wheel and source distribution.

The workflow deliberately does not publish to PyPI. It uses only GitHub-owned
workflow actions and grants `contents: write` solely to the final release job.
For a reproducible release, update `pyproject.toml` first and push the matching
tag, for example `v1.2.0`.

## Local distribution check

Run the same packaging gate locally from the repository root:

```console
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pip install -e . --no-deps
python -m build --wheel --no-isolation
python -m twine check dist/*.whl
rxycode --version
rxycode --help
```

See `docs/modules/tests.md` for marker conventions, fixture rules, and the full
local test commands.
