# RxyCode OpenTUI dual-entry shell

Isolated Bun package for the OpenTUI TUI (React 19.2+) so the main Ink
`frontend/` app can stay on React 18.

## Launch

```bash
# from repo root (preferred via main.py)
set RXYCODE_TUI=opentui
# or default when bun is on PATH

# direct
cd frontend/opentui-app
bun install
bun run start
```

Env (same as Ink): `RXYCODE_API_PORT`, `RXYCODE_API_URL`, `RXYCODE_API_TOKEN`,
`RXYCODE_E2E_BYPASS_TTY=1` (skip TTY check).

## Probe

```bash
bun run probe
```

## Tests

```bash
bun test
```

## Terminal lifecycle

`createCliRenderer({ useAlternateScreen: true })` owns stdin and the alternate
screen. On exit / SIGINT / SIGTERM we call `renderer.destroy()` which leaves the
alternate screen and restores the cursor. Do not dual-read stdin with Ink's
`stdinBridge` on this path.
