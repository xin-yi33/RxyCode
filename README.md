<!-- README_SYNC: source=working-tree; updated=2026-10-26 -->
<div align="center">

**English** · [简体中文](./README.zh-CN.md)

# RxyCode

**An MIT-licensed coding agent with a headless Python core. Run the CLI/OpenTUI on your machine, or use the same harness from a browser.**

[⭐ Star this repo](https://github.com/xin-yi33/RxyCode) if you want a local agent that plans, runs tools, checks its own writes, and asks before risky operations.

[![Version](https://img.shields.io/badge/version-1.4.5-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.5)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml/badge.svg)](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml)
[![Web CI](https://github.com/xin-yi33/RxyCode/actions/workflows/web-ci.yml/badge.svg)](https://github.com/xin-yi33/RxyCode/actions/workflows/web-ci.yml)
[![Stars](https://img.shields.io/github/stars/xin-yi33/RxyCode?style=social)](https://github.com/xin-yi33/RxyCode/stargazers)

<p>
  <img src="docs/imgs/cli-demo-cover.png" alt="RxyCode OpenTUI session" width="800">
</p>

<p align="center"><sub>Existing OpenTUI capture. v1.4.5 adds the terminal polish and engine changes listed below; the CLI entry point is unchanged.</sub></p>

[⭐ Star](https://github.com/xin-yi33/RxyCode) &nbsp;·&nbsp; [⚡ Quick start](#-quick-start-five-steps) &nbsp;·&nbsp; [🔑 What is different](#-what-is-different) &nbsp;·&nbsp; [🖥️ Surfaces](#️-surfaces) &nbsp;·&nbsp; [Docs](docs/)

</div>

RxyCode is a coding agent you can run locally or from a browser. The core is a headless Python process (`Session` over `AgentV2`); OpenTUI, the Ink fallback, the Desktop shell, and the Web console are clients. The CLI runs on your machine. The hosted Web console runs each turn inside a cloud sandbox and cannot read your disk unless you explicitly pair a machine with `rxycode connect` or upload a file.

The CLI is the primary surface for v1.4.5. It plans, calls tools, runs commands, and verifies the result. Bring an OpenAI-compatible model key; model traffic goes to the endpoint you configure, not through a mandatory relay.

> **v1.4.5 · 2026-10-26.** Persistent shell state, write-time diagnostics, subagent collaboration tools, stricter permission tiers, and the Web BYOK workspace with attachments, artifacts, and previews. Product metadata is `1.4.5`; JSON-RPC stays `1.1.0`; the import namespace `RxyCode1_1_0` is unchanged. The GitHub Release publishes one sdist, `rxycode-1.4.5.tar.gz` — no wheel, no new Desktop installer, and no PyPI 1.4.5 upload.

---

## 🔑 What is different

**1. A shell that keeps state, without keeping permission.**
The agent's interactive `bash` now reuses one managed shell per session, so `export`, `cd`, `source venv/bin/activate`, and shell functions survive across calls. Every command still goes through the same argument validation, risk classification, approval gate, journal, output cap, and OS sandbox. Cancelling or losing the shell discards the process tree and reports the state loss honestly; it does not replay the command. `RXYCODE_MANAGED_SHELL=0` disables the path. Docker mode stays one-container-per-command.

**2. Checks run when the file is written.**
`write`, `edit`, and `patch` share one post-write entry. Python gets a real `compile()` plus an optional Ruff pass; JavaScript gets `node --check`; TS/TSX uses the project's own `tsc` configuration. The result has separate `written` and `diagnostics.status` fields, and only `pass` counts as a pass. Missing checkers report `unavailable` or `not_checked` instead of a fake success. Project-supplied executable checker config (for example ESLint flat config) requires explicit trust; the safe checks still run, and no dependencies are installed on demand.

**3. Subagents you can address, not just spawn.**
Built-in child agents (`explore`, `general`, `reviewer`, `scout`) run in isolated sessions with their own context, tool scope, permission policy, and budget. The model can call `spawn_subagent` in `sync`, `async`, or `stream` mode, then use `send_message_to_subagent`, `list_agents`, and `cancel_subagent`. Parent/child attribution comes from the runtime, not from text the child can forge. `/children` shows the tree; `@explore` routes a request; `RXYCODE_SUBAGENTS=0` restores the single-agent baseline.

**4. Permission tiers with a hard floor.**
`confirm_all` auto-approves reads, but every edit and every shell command asks. `auto_edit` also auto-approves file edits, while shell still asks. `full_auto` removes prompts for ordinary tools but never overrides the hard denylist. Shell approval is never below WRITE: a READ shell command is lifted to WRITE, while a DANGER command stays DANGER. Plan mode is read-only at the execution layer, not just in the prompt. Write targets stay inside the project root or the configured output directory; the audit log records the decision. On the hosted Web worker, `full` is only an approval profile: the turn still runs in the per-run sandbox with the same mounts, network policy, and writable domain.

**5. One harness, several surfaces.**
OpenTUI talks to the core over stdio JSON-RPC through `appserver`; the API server exposes HTTP + SSE; the Web worker calls the same `Session.prompt` path. The wire protocol is still `1.1.0`. Tool discovery follows the same contract: MCP/plugin schemas load on demand through `tool_search`, and every MCP tool call passes the same gate and audit path. This is why a fix in the agent loop or a tool contract applies to every surface instead of being re-implemented per client.

**6. A cloud workspace that is explicit about the boundary.**
The Web console requires a user-owned BYOK model key; there is no platform-model fallback. Runs, events, approvals, and artifacts are durable on PostgreSQL. Files can be uploaded into the tenant workspace; finished files appear in an artifact manifest with signed download links and image/HTML/text previews. A cloud run cannot touch your computer by default. Pairing a machine with `rxycode connect` is the explicit bridge, and every shell call still goes through a local approval inbox.

---

## ⚡ Quick start (five steps)

### 1. Check the runtime

Python 3.10+ is required. The CLI installer also provisions Bun for OpenTUI. Node.js 20+ is only needed for the Ink fallback or a Desktop source build.

### 2. Run from the tagged source, or install the CLI

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.4.5" rxycode
```

Install it permanently:

```bash
uv tool install --force --refresh "git+https://github.com/xin-yi33/RxyCode.git@v1.4.5"
```

macOS / Linux installer:

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.5/install.sh | sh
```

Windows PowerShell installer:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.5/install.ps1 | iex"
```

The installer creates an isolated tool environment; it does not modify system Python packages. See [docs/quickstart.md](docs/quickstart.md) for the full matrix.

### 3. Add a model

```bash
rxycode
```

Inside OpenTUI, run `/addmodel`. The wizard stores the key with Windows DPAPI or a POSIX `0600` credential file, masks it in the UI, and never writes it to the transcript. `rxycode config add-model <id> <provider-model-id> --base-url <url>` is the headless equivalent; it reads the key from `RXYCODE_API_KEY`, never from argv.

### 4. Give it a task

Try a small one first:

```text
Create a single-file click-counter.html in this folder, then open it and verify the button increments.
```

Approve file writes or shell calls when the gate asks. In Plan mode the agent can read and propose, but writes are refused. In Build mode it can execute, and the result is checked before it is reported.

### 5. Pick a surface

- **CLI / OpenTUI:** `rxycode`
- **Headless API:** `rxycode --api` (default port `8765`)
- **Web:** [rxycode.xyz](https://rxycode.xyz) — early preview; sign in and bring your own model key
- **Desktop:** source is under `frontend/desktop-app/`; v1.4.5 publishes no new Desktop binary. `rxycode gui` only launches an already installed Desktop tree.

---

## 📦 Install and release artifacts

v1.4.5 publishes exactly one GitHub Release asset: `rxycode-1.4.5.tar.gz` (source distribution). The v1.4.5 release does **not** include a wheel, `.exe`, `.dmg`, or `.AppImage`, and there is no PyPI 1.4.5 release. The `.github/workflows/release.yml` workflow rejects non-sdist artifacts before publishing.

From a downloaded sdist:

```bash
python -m pip install --no-cache-dir --force-reinstall rxycode-1.4.5.tar.gz
```

Upgrade an existing CLI install:

```bash
uv tool install --force --refresh "git+https://github.com/xin-yi33/RxyCode.git@v1.4.5"
```

From source:

```bash
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -e .
rxycode
```

Docker:

```bash
docker compose up -d api
docker compose run --rm tui
```

The compose stack listens on `8765` inside its network and requires `RXYCODE_API_TOKEN` in `.env`; add a `ports:` mapping if you need host access. The TUI service needs an interactive TTY.

### Desktop

There is no new Desktop installer for 1.4.5. The Electron source remains in `frontend/desktop-app/`; run it with `npm install && npm run dev`. For a packaged app, older releases such as [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) and [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) remain available; neither is a 1.4.5 build. The v1.2.10 Windows portable asset is `RxyCode.Desktop-1.2.10-win.zip`; its installer is `rxycode-desktop-1.2.10-setup.exe`. Both are historical and are not 1.4.5 installers. `rxycode gui` launches an installed tree from `~/.rxycode/desktop`, `RXYCODE_DESKTOP_DIR`, or `--desktop-dir`; a CLI-only install cannot start it. Details: [docs/GUI.md](docs/GUI.md).

---

## 🖥️ Surfaces

### CLI / OpenTUI

OpenTUI is the default terminal client. It shows streaming text, tool calls, approvals, the child-agent tree, thinking, and the todo list.

| Key | Action |
|---|---|
| `Tab` | Switch Build / Plan / Compose |
| `Ctrl+P` | Command palette |
| `Ctrl+T` | Toggle thinking |
| `Ctrl+E` | Toggle the todo checklist |
| `Enter` | Send |
| `Shift+Enter` / `Ctrl+Enter` | Newline |
| `Esc` | Cancel or dismiss |
| `Ctrl+C` | Copy / cancel / clear; twice within 2s to quit |

| Command | Action |
|---|---|
| `/build` | Plan, execute, verify |
| `/plan` | Read-only analysis and plan |
| `/compose` | Plan then build in one flow |
| `/addmodel` | Add a provider |
| `/models` `/model <name>` | List / switch models |
| `/permission` | `confirm_all` / `auto_edit` / `full_auto` |
| `/agents on` `/team <task>` | Expert team (off by default) |
| `/children` `/child` `/parent` | Child-agent tree |
| `/memory add/list/search` | Cross-session facts |
| `/language` | UI language |
| `/help` | Full command reference |

The default work mode is Build. Plan is read-only at the execution layer. Compose is a plan followed by a build. The expert team is off by default and is intended for modular work, not everyday edits.

### Headless API

```bash
rxycode --api
```

This is the FastAPI HTTP + SSE adapter, not an interactive TUI. It uses the same `Session` and protocol mapping as the other clients.

## 🌐 RxyCode Web

The live instance is [rxycode.xyz](https://rxycode.xyz). It is a small community deployment and an early preview, not a production SLA.

<p>
  <img src="docs/assets/rxycode-web-console-v1.4.4.png" alt="RxyCode Web console" width="800">
</p>

<p align="center"><sub>Existing v1.4.4 console capture; v1.4.5 adds the interaction and attachment changes below.</sub></p>

- **BYOK only.** The console lists only user-owned model connections. A platform model reference is rejected; there is no admin bypass.
- **Durable runs.** PostgreSQL stores runs, events, approvals, and leases. Redis is used for SSE fan-out, not as the source of truth.
- **Attachments.** Upload, paste, or drop a file; the run binds the staged attachment to the task transactionally. DOCX/XLSX/PPTX and ODT/ODS/ODP text extraction is built in; a failed import fails the run instead of silently dropping the file.
- **Artifacts and previews.** A finished turn registers changed files in a manifest with signed download links. HTML/text previews are served from a private bucket with a CSP sandbox; images stream as images. PDF/Office preview is not claimed.
- **Questions and timeline.** Question cards are ordered, single-select, and post exactly once. Thinking and task-list blocks are expandable. These are model output and run events, not hidden host state.
- **Mobile and older Chromium.** The console is tested at a 390px viewport and on Chromium 90/98/148; Playwright Firefox/WebKit also cover key paths. Real iOS/Vivo devices are not verified.
- **Device bridge.** `rxycode connect --url <wss-url> --code <one-time-code> --device-id <name> --capability shell` pairs a local machine over outbound WSS. The cloud can then send shell calls to that machine through an approval inbox, confined to the directory where `connect` was started.

The table is a release-evidence map, not a promise of uniform deployment. `shipped` rows cite an on-disk evidence directory and test file; `experimental` means the path is present and tested but lacks a dedicated release-evidence package; `blocked` names the current limitation.

| Capability | Status | Evidence | Verification |
|---|---|---|---|
| Tenant login and CSRF/Origin write gate | shipped | `evidence/web/WEB-W2-C02` | `tests/web/w2/test_w2_c02_module.py` |
| Durable runs with fenced worker leases | shipped | `evidence/web/WEB-W2-C03` | `tests/web/w2/test_w2_c03_module.py` |
| Event store, outbox, SSE replay and reconnect | shipped | `evidence/web/WEB-W7-C02` | `tests/web/w7/test_w7_c02_module.py` |
| Persisted approval/question state and cross-day resume contract | shipped | `evidence/web/WEB-W2-C06` | `tests/web/w2/test_w2_c06_unit.py` |
| React workbench: login, sessions, diffs, PTY and artifacts | shipped | `evidence/web/WEB-W3-C06` | `tests/web/w3/test_w3_c06_module.py` |
| Local Full runner, device pairing and emergency stop | shipped | `evidence/web/WEB-W4-C06` | `tests/web/w4/test_w4_c06_module.py` |
| Email-code auth, ALTCHA and rate ceilings | shipped | `evidence/web/WEB-W9-C01` | `tests/web/w9/test_rate_and_device.py`, `tests/web/w9/test_email_codes.py` |
| Single-device login lock | shipped | `evidence/web/WEB-W9-C01` | `tests/web/w9/test_rate_and_device.py` |
| BYOK key vault and model picker | shipped | `evidence/web/WEB-W10-C01` | `tests/web/w9/test_byok_api.py`, `tests/web/w9/test_byok_crypto.py` |
| Attachment staging, transactional binding and document text extraction | experimental | — | `tests/web/w11/test_w11_c07_unit.py`, `tests/web/w11/test_w11_attachments_staging.py` |
| Artifact manifest, signed download and Range support | shipped | `evidence/web/WEB-W3-C06` | `tests/web/w11/test_w11_c07_unit.py` |
| Image, HTML and text previews | experimental | — | `tests/web/w11/test_w11_c09_unit.py` |
| Session workspace file list and download | shipped | `evidence/web/WEB-W12-C01` | `tests/web/w9/test_session_files.py` |
| Device bridge and local approval inbox | shipped | `evidence/web/WEB-W13-C01` | `tests/web/w4/test_w4_c05_module.py` |
| Per-run cloud sandbox with tenant filesystem isolation | shipped | `evidence/web/WEB-W5-C02` | `tests/web/w5/test_w5_c02_unit.py` |
| Reproducible agent evals and baseline comparison | shipped | `evidence/web/WEB-W7-C03` | `tests/web/w7/test_w7_c03_unit.py` |
| OpenTelemetry spans and per-run cost ledger | shipped | `evidence/web/WEB-W7-C04` | `tests/web/w7/test_w7_c04_unit.py` |
| Compose deployment, HTTPS gateway and confined turns | shipped | `evidence/web/WEB-W7-C05` | `tests/web/w7/test_w7_c05_module.py` |
| Security review corpus for auth, injection and data leaks | shipped | `evidence/web/WEB-W7-C01` | `tests/web/w7/test_w7_c01_unit.py` |
| Manual public browser smoke: login, BYOK, takeover, cancel, files | shipped | `evidence/web/WEB-W10-C02` | `tests/web/w9/test_e2e.py`, `tests/web/w9/test_version.py` |
| Hosted public demo URL | shipped | `evidence/web/WEB-W10-C02` | `tests/web/w9/test_version.py` |
| Anonymous cloud run over HTTP | blocked: visitors must sign in before sending a task | — | — |
| Public worker executing `local:*` targets | blocked: cloud-only placement gate rejects local targets | — | — |
| PDF and Office artifact preview | blocked: capability reports `pdf=false`, `office=false` | — | — |
| Standalone Playwright npm E2E in `apps/web` | blocked: `apps/web` has no independent Playwright npm E2E target or dependency; Python browser tests under `tests/web` exist | — | — |

The public worker executes only `cloud:{tenant}:{workspace}` targets inside the per-run sandbox. A cloud run cannot read your home directory. Uploading a file or pairing a device is an explicit action. Self-hosting and boundaries: [docs/deploy/web-runbook.md](docs/deploy/web-runbook.md); user guide: [docs/product/web-user-guide.md](docs/product/web-user-guide.md); design: [docs/architecture/web-system-design.md](docs/architecture/web-system-design.md).

---

## 🏗️ Architecture

```text
rxycode (OpenTUI) / rxycode gui / rxycode --api / Web browser
                     │
                     ▼  stdio JSON-RPC / HTTP+SSE / Web SSE
     appserver (worker subprocess + watchdog)   rxycode_server + worker
                     │                                   │
                     └─────────────────┬─────────────────┘
                                       ▼
                          Session (headless facade, no UI)
                                       │
                                       ▼
                                   AgentV2
   ┌──────────────────────────────────────────────────────────┐
   │ Simple query → fast path + exact-hash / semantic cache   │
   │                                                          │
   │ Daily Build → streaming tool loop + build workflow/       │
   │               verification                               │
   │ /full or /pipeline, complex Compose → LangGraph DAG:     │
   │ goal planner → decomposer → parallel executor →           │
   │ validator → reflection → grounded synthesis               │
   │                                                          │
   │ Subagents: isolated child sessions + collaboration tools  │
   │ Expert team: Coordinator + deterministic SOP (off)        │
   │                                                          │
   │ Tools: built-ins + MCP + plugins, all via ToolOrchestrator│
   │ Safety: risk tiers, approval, hard denylist, audit,       │
   │         write whitelist, optional OS sandbox              │
   │ Memory: short-term / compressed / vector / code RAG       │
   └──────────────────────────────────────────────────────────┘
```

`appserver` isolates each session in a worker subprocess. The Web worker adds a per-run Linux user/PID/IPC/UTS namespace sandbox and refuses to run on the host if the sandbox is unavailable. The CLI's optional OS sandbox (`execution.os_sandbox.enabled`, default off) is a separate boundary; the permission tier is not a sandbox switch.

MCP servers stay stdio. Their tools go through the same `ToolOrchestrator`, approval gate, audit log, and retry policy as built-ins. Per-server tool manifests record the schema surface and warn on drift. Tool schemas can be discovered on demand with `tool_search`; the full discovery stays in the message context instead of being re-sent every turn. Plugin skills and MCP entries are listed through `plugin/list`.

---

## 🛡️ Safety and permissions

Every tool call is classified before it runs.

| Risk | Examples | Default policy |
|---|---|---|
| READ | read, grep, glob, web fetch | auto-approved |
| WRITE | file edits, ordinary shell commands | approval, subject to tier |
| DANGER | installers, `git push --force`, destructive shell | approval; hard-denied patterns never run |

The three permission tiers are:

| Tier | Reads | File edits | Shell |
|---|---|---|---|
| `confirm_all` | auto | ask | ask |
| `auto_edit` | auto | auto | ask |
| `full_auto` | auto | auto | auto, except hard-denied patterns |

Shell approval is at least `WRITE`: a READ shell command is lifted to `WRITE`, and a DANGER command keeps `DANGER` instead of being lowered. This is why `auto_approve: ["write"]` cannot run a destructive command.

Additional boundaries:

- **Hard denylist before approval.** Catastrophic patterns are rejected before the approval prompt, including recursive deletion of system roots, disk formatting, raw device writes, and shutdown/reboot commands. This is a pattern-based safety net, not a proof; keep the OS sandbox and approval gate enabled for untrusted work.
- **Write whitelist.** Writes outside the project root and the configured output directory fail closed.
- **Plan mode is read-only.** The execution layer refuses writes in Plan, even if a model asks for one.
- **Audit log.** Decisions and tool calls append to `~/.RxyCode/logs/audit.jsonl` with credentials and API tokens redacted.
- **Dry run.** `RXYCODE_DRY_RUN=1` simulates actions without disk or network side effects.
- **Web sandbox.** The hosted worker always runs a turn inside the per-run sandbox. `full` on Web only removes approval prompts inside that sandbox; it does not add host mounts or network access.
- **Device bridge.** A paired machine runs shell calls locally under its own approval inbox and is confined to the directory where `rxycode connect` was started.

### Model traffic

The program, workspace, keys, and audit log stay on your machine. When you call a cloud model, the request contains the current prompt and system instructions, recent turns still in the context window, file excerpts/diffs/tool output already returned this session, and images if you use vision. The whole repository is not uploaded automatically. `websearch` sends the query to the configured search provider; `webfetch` contacts the target URL; MCP servers see what their tools return.

---

## ⚙️ Configuration

Configuration lives in `~/.RxyCode/config.yaml`; the output directory is `~/.RxyCode/output/` by default.

| Variable | Purpose |
|---|---|
| `RXYCODE_DATA_DIR` | Override the data/config directory |
| `RXYCODE_OUTPUT_DIR` | Override generated-file output |
| `RXYCODE_API_KEY` | Key used by `rxycode config add-model` |
| `RXYCODE_DRY_RUN=1` | Simulate actions without side effects |
| `RXYCODE_MANAGED_SHELL=0` | Disable the persistent shell |
| `RXYCODE_SUBAGENTS=0` | Disable subagent dispatch |
| `RXYCODE_TUI=ink` | Use the Ink fallback instead of OpenTUI |
| `RXYCODE_DESKTOP_DIR` | Point `rxycode gui` at an installed Desktop tree |

Provider presets include DeepSeek, Moonshot/Kimi, Alibaba Qwen, Volcengine Doubao, Zhipu GLM, SiliconFlow, OpenAI, Anthropic-compatible proxies, OpenRouter, and Groq. Model identifiers and capabilities are data-driven; use `rxycode config list` or `/models` to see what is configured.

---

## 📦 Requirements

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | Core agent |
| Bun | latest | Default OpenTUI runtime; installer provisions it |
| Node.js | 20+ | Ink fallback or Desktop source |
| API key | — | Any OpenAI-compatible provider |
| Docker | current | Optional: Docker deployment and Web self-hosting |

CI covers Linux Python 3.11/3.12 and Windows. macOS is not exercised on a real machine for this release.

---

## 📋 Release history

| Version | Date | Highlights |
|---|---|---|
| [v1.4.5](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.5) | 2026-10-26 | Persistent shell, write-time diagnostics, subagent collaboration, permission tiers, Web BYOK workspace with attachments/artifacts/previews. Product metadata 1.4.5; protocol 1.1.0; sdist only |
| [v1.4.4](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.4) | 2026-10-22 | RxyCode Web lands: hosted console, durable runs, BYOK vault, device bridge, 3-worker ceiling. Product metadata 1.4.4; protocol 1.1.0 |
| [v1.4.3](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.3) | 2026-10-14 | On-demand MCP schemas, write-time lint, hard shell blacklist, 200-line output spill, tool audit metrics |
| [v1.4.2](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.2) | 2026-10-09 | Todo ledger/dock, status band, incremental compaction, output spill, default-off timeout decisions |
| [v1.4.1](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.1) | 2026-10-07 | CLI maintenance: optional OS sandbox, Windows venv Job binding, log retention, retry/circuit breaker |
| [v1.4.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.0) | 2026-09 | CLI/OpenTUI only: sessions, `/effort`, plan approval, shared retry, Shift+Enter |
| [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) | 2026-09 | Desktop workbench: three-column workspace, permission tiers; Windows/Linux packages |
| [v1.2.11](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11) | 2026-08 | 10-role, 7-stage expert team; Windows encoding; 8MB stdio throughput |
| [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) | 2026-08 | Electron Desktop, Plan mode, Goal dialog, composer menu |
| [v1.2.9](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.9) | 2026-08 | Isolated child agents: `@agent`, Task tool, child tree |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | LangGraph rewrite: plan-and-execute, tiered memory, code RAG |
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | Initial public release: toolchain and MCP |

Full changelog: [CHANGELOG.md](CHANGELOG.md). Per-version notes: [docs/release-notes/](docs/release-notes/). The v1.4.5 copy is [RELEASE_NOTES_v1.4.5.md](docs/release-notes/RELEASE_NOTES_v1.4.5.md).

---

## ⚠️ Known limitations

- **Web E2E is not fully green for v1.4.5.** The 300-second acceptance run completed its target (`ELAPSED=300.000691652298`) and produced a real 180.003s liveness checkpoint (5s observation, 3 processes, CPU/IO 0, owner-BYOK `continue`, UI visible). After that, the model asked for an extra file-check approval (`ca7505f206d446169e16ff98ba0f38ed`); the run was cancelled by its owner and ended `cancelled`, not natural `succeeded`. The extra-approval cause is **OPEN** and not named as a confirmed product bug.
- **That liveness result is one run and one model.** It is not a general guarantee for every model, provider, or long command. The extra fixed 15s liveness wait was removed with approval; the P6 15s decision clock, task/tool budgets, renewal, permissions, and kill rules are unchanged.
- **Platform coverage is uneven.** A Linux 3.10 container (Python 3.12) and Windows have real evidence. macOS was not run on a real machine for this release. Do not read the CI badges as an all-platform hardware claim.
- **The Web console is an early preview.** It runs on a small VM with a three-worker ceiling and no SLA. PDF/Office preview is not supported. Real iOS/Vivo/Safari devices were not verified; Chromium 90/98/148 and Playwright Firefox/WebKit are the tested browser engines.
- **BYOK-only is a policy change on Web.** Platform-model fallback is removed; a hosted run needs a user-owned model connection. Local CLI behavior is unchanged.
- **Release scope.** v1.4.5 publishes one sdist and no Desktop binary. There is no PyPI 1.4.5 upload. Existing Desktop packages on older releases are not 1.4.5 builds.
- **CI baseline.** Historical baselines: source `247be96e` passed CI `40166956475` (6/6 jobs); docs `63fcde7b` passed CI `40173191825` (6/6). Those runs do not prove the v1.4.5 tag; the tag needs its own CI result before release.

---

## 🤝 Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Issues and focused bug reports are welcome. For agent-facing module notes, start at [docs/agent/README.md](docs/agent/README.md).

## 📄 License

[MIT](LICENSE) © RxyCode contributors.

If RxyCode is useful, [star the repo](https://github.com/xin-yi33/RxyCode) so you can find it again. Bugs and ideas: [Issues](https://github.com/xin-yi33/RxyCode/issues).
