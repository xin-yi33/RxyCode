# RxyCode v1.2.11

RxyCode is a local plan-and-execute coding agent. Type `rxycode` in a terminal to open OpenTUI. Protocol version stays `1.1.0`.

> **v1.2.11 is the current CLI release.** This GitHub Release publishes **one** installable asset: `rxycode-1.2.11.tar.gz`. It does **not** add Windows, macOS, or Linux Desktop binaries. The **v1.2.10** Desktop release remains published.

## What changed

- Expert-team runtime (`core/agents/`) is in the tree and **off by default** (`settings.agents.enabled=false`).
- Split top-level packages share one module identity (`core` is `RxyCode.RxyCode1_1_0.core`).
- Long tool writes, Windows tool-output decoding, and empty HTTP 200 responses are more reliable.
- GitHub `docs/` now contains only `agent/`, `assets/`, `imgs/`, `modules/`, `release-notes/`, `quickstart.md`, and `GUI.md`.

## Highlights

- **One download** — `rxycode-1.2.11.tar.gz` (source distribution). Install with pip or uv.
- **Desktop stays on v1.2.10** — `RxyCode.Desktop-1.2.10-win.zip`, setup.exe, dmg, and AppImage remain on the still-open v1.2.10 release.
- **Expert teams stay optional** — Coordinator + SOP state machine + budget gates. Default is solo AgentV2.
- **CLI is still OpenTUI** — type `rxycode` in cmd or any terminal.

## Details

### Added

- **Expert-team runtime** — AgentSpec / TeamSpec, deterministic SopMachine, Coordinator (schedule only), BudgetGuard, mechanical verifier, ModeRouter, JSON-RPC worker bridge, builtin `software_dev` SOP (`core/agents/`).
- **Docs** — `docs/agent/`, `docs/quickstart.md`. Screenshots live in `docs/imgs/`.

### Fixed

- Stdio OpenTUI and Desktop now route `/team`, `/team-multi`, `/solo`, `/why-mode`, and `/agents` through `Session.prompt`, so expert teams actually start. Builtin `software_dev` is listed by `team/list`. Coordinator dispatches roles through the live AgentV2 instead of a stub. When `agents.enabled=false` (the default), ordinary prompts skip ModeRouter so concurrent sessions and `session/interrupt` keep AgentV2 latency.
- `software_dev` plan stage no longer requires a verbatim `expected_output` match (`goal_satisfied`) before implement.
- Expert-team `delegate_request` prompt includes a `<ROLE>` section; architect / coder / auditor / delegate stages have few-shot examples.
- Large streamed writes no longer die at a 15s idle cutoff (idle 30s, cap 90s; tool-arg wait 60s).
- appserver JSON-RPC stdio limit raised to 8MiB (was 64KiB), so a long Final Answer does not kill the worker.
- Windows tool output decodes with `errors=replace` instead of crashing on mixed UTF-8 / GBK.
- One retry when a provider returns HTTP 200 then silence.
- CLI-only install notes no longer tell you to run `rxycode gui` without a Desktop build.
- Published sdist still does not ship `evals`, `.coveragerc`, `AGENTS.md`, or repo test scripts.
- Linux AppImage launch helpers (`APPIMAGE_EXTRACT_AND_RUN=1`, `--no-sandbox`) stay in the CLI launcher; this tag does not republish an AppImage.
- Weekly CI no longer treats live-provider 401/quota/circuit-breaker as an AgentV2 quality regression.
- Provider 401/quota text no longer echoes `sk-` / `ark-` keys into logs or answers.
- GitHub Actions no longer stores or injects `RXYCODE_LIVE_API_KEY`.

### Changed

- Product version **1.2.11** in `pyproject.toml`, installers, OpenTUI/Ink headers, MCP `clientInfo`, and Desktop package metadata. Protocol version stays `1.1.0`.
- Release workflow builds and uploads **sdist only**. No desktop matrix on this tag.

## Install

CLI / OpenTUI (no Electron):

```powershell
# Windows
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.11/install.ps1 | iex"
rxycode
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.11/install.sh | sh
rxycode
```

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.11"
rxycode
```

From this release asset:

```bash
python -m pip install rxycode-1.2.11.tar.gz
rxycode
```

**Desktop GUI** is not attached here. Download it from [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) (`rxycode-desktop-1.2.10-setup.exe` or `RxyCode.Desktop-1.2.10-win.zip`, plus macOS dmg / Linux AppImage). A CLI-only install cannot start Electron.

## Assets

- `rxycode-1.2.11.tar.gz`
