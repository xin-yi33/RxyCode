# main.py - CLI Entry Point

## What Is This Module?
The main entry point for RxyCode. It handles CLI argument parsing, launches the
**OpenTUI frontend by default** (Ink fallback when requested or Bun is missing),
and starts the API server.

## Entry Points
- `rxycode`: Launch the default TUI (OpenTUI when Bun is ready) with an embedded authenticated API server
- `python -m RxyCode`: Same as above
- `python -m RxyCode.RxyCode1_1_0`: Versioned module entry point
- `rxycode --version`: Report the package version without initializing runtime state
- `rxycode --api`: Start the API server only
- `rxycode gui`: Launch Desktop if a Desktop build is already installed (`~/.rxycode/desktop`, `RXYCODE_DESKTOP_DIR`, or `--desktop-dir`). Accepts a flat install, the portable zip wrapper folder, or a Linux AppImage. For `.AppImage` it sets the execute bit and `APPIMAGE_EXTRACT_AND_RUN=1` so missing FUSE does not block startup. The CLI sdist does not ship Electron; download setup.exe / `RxyCode.Desktop-*-win.zip` / AppImage from the current GitHub Release (v1.3.0 does not ship macOS). A CLI-only install raises a ClickException pointing at that Release page instead of implying `rxycode gui` is enough.
- `rxycode config`: Manage model configuration
- `rxycode config add-model <id> <provider-model-id> --base-url <url>`: Add a model; API key comes from `RXYCODE_API_KEY`
- `rxycode config model-limits`: Inspect/set per-model output limits (`inspect` / `set-auto`)

The console script is declared in `pyproject.toml` and implemented by `entrypoint.py`. `_package_root/RxyCode/` provides the stable module bridge while the existing `RxyCode.RxyCode1_1_0.*` import contract remains intact.

## Core: cli()
Click options:
- `--model`, `-m`: Model name to use
- `--api`: Start the API server only
- `--api-port`: API server port, default `8765`
- `--version`: Print the package version and exit
- `--log-level`: Configure runtime logging
- `--print-logs`: Mirror logs to stderr

## Core: _launch_tui(model, port)
Routes to OpenTUI or Ink:

| Env | Behavior |
|-----|----------|
| `RXYCODE_TUI=ink` | Force Ink |
| `RXYCODE_TUI=opentui` | Force OpenTUI — **errors** if Bun or `frontend/opentui-app` missing (no silent fallback) |
| unset / default | Prefer **OpenTUI** when Bun + `frontend/opentui-app` exist (classic dark+pink visuals); else Ink |

## Core: _launch_opentui_tui(model, port)
1. Ensure Bun is available: `_ensure_bun(required=True)` **auto-downloads and
   installs Bun** (`_install_bun_runtime`) when missing; only a failed install
   errors. `RXYCODE_SKIP_BUN_INSTALL=1` skips auto-install.
2. `_ensure_opentui_dependencies()` runs `bun install` in `frontend/opentui-app`
   when dependencies are missing.
3. Start the authenticated loopback API (same token handoff as Ink).
4. Launch `bun run src/index.tsx` in `frontend/opentui-app` with `RXYCODE_API_*` env vars.

`_resolve_tui_backend` also accepts an explicit `auto` value; `_resolve_transport()`
reads `RXYCODE_TRANSPORT` (stdio/http) and `_resolve_model_label()` derives the
model display label.

## Core: _launch_ink_tui(model, port)
Launch sequence:
1. Resolve and validate `frontend/package.json` and `frontend/dist/index.js`.
2. Require a `node` executable on `PATH`.
3. Select an available localhost port.
4. Start the authenticated API server in a daemon thread.
5. Poll `/status` with the generated bearer token until the API is ready.
6. Launch `node frontend/dist/index.js` with the API URL and token in its environment.
7. Shut down the embedded API server when the frontend exits.

Missing runtime assets, Bun/Node.js, API startup failures, and frontend process failures return explicit CLI errors.
