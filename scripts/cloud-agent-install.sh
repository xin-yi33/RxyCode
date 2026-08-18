#!/usr/bin/env bash
# =============================================================================
# RxyCode Cloud Agent setup — idempotent bootstrap for a fresh environment.
#
# Prepares the full development experience on top of Cursor's default image
# (Python 3.12 + Node 22 already present):
#   * Backend  : Python runtime + dev/test deps, editable install, uv
#   * Frontends: Ink (npm), protocol-client (bun), OpenTUI (bun)
#
# Python packages are installed into the *system* site-packages (via sudo) so
# that every subprocess resolves the editable `RxyCode` package — this includes
# pytest-xdist workers and the `python3 -m appserver` process the TS frontends
# spawn over stdio. A user-site (~/.local) install is NOT loaded by those child
# interpreters and breaks the layered test suite.
#
# Safe to run repeatedly.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

# Elevate only when needed: run as-is if already root, use sudo when available,
# otherwise best-effort without it (surfaces a clear error if a step needs root).
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  SUDO=""
fi

log "System: python3-venv (ensurepip) for the isolated-install distribution tests"
# The packaging gate (tests/system/test_installed_package.py) and CI wheel smoke
# build throwaway venvs with `python3 -m venv`, which needs ensurepip.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq python3-venv
fi

log "System: ensure a bare 'python' resolves to python3"
# The base image only ships 'python3'. RxyCode's bash tool and the evals runner
# shell out to a bare 'python' at runtime, so expose it on the global PATH.
if ! command -v python >/dev/null 2>&1; then
  $SUDO ln -sf "$(command -v python3)" /usr/local/bin/python
fi
python --version

if [ -n "$SUDO" ]; then
  PIP=("$SUDO" python3 -m pip install --break-system-packages)
else
  PIP=(python3 -m pip install --break-system-packages)
fi

log "Backend: Python dependencies (system site-packages)"
# Debian ships setuptools/wheel in /usr/lib/python3/dist-packages that pip cannot
# uninstall to upgrade; install the newer required versions alongside in /usr/local
# (earlier on sys.path) instead of trying to replace the distro copies.
"${PIP[@]}" --ignore-installed setuptools wheel
"${PIP[@]}" -r requirements.txt -r requirements-dev.txt
"${PIP[@]}" -e . --no-deps
# uv backs the packaging / distribution test gate.
"${PIP[@]}" uv

log "Toolchain: Bun runtime (for OpenTUI + protocol-client)"
if ! command -v bun >/dev/null 2>&1; then
  export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
  curl -fsSL https://bun.sh/install | bash
  # Put bun on the global PATH so a fresh login shell finds it without profile edits.
  $SUDO ln -sf "$BUN_INSTALL/bin/bun" /usr/local/bin/bun
fi
bun --version

log "Frontend: Ink fallback TUI (frontend/)"
( cd frontend && npm ci && npm run build )

log "Frontend: protocol client (frontend/protocol-client/)"
( cd frontend/protocol-client && bun install --frozen-lockfile )

log "Frontend: OpenTUI default shell (frontend/opentui-app/)"
( cd frontend/opentui-app && bun install --frozen-lockfile )

log "RxyCode Cloud Agent setup complete."
