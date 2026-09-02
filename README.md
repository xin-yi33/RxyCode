<!-- README_SYNC: source=working-tree; updated=2026-09-02 -->
<div align="center">

**English** · [简体中文](./README.zh-CN.md)

# RxyCode

**A local plan-and-execute coding agent for developers — v1.3.0 makes Desktop a first-class workbench; type `rxycode` in cmd for OpenTUI. Every tool call still goes through a safety gate.**

[⭐ Star this repo](https://github.com/xin-yi33/RxyCode) if you want a local agent that plans, runs tools, and asks before risky writes — now with a GUI that is no longer a leftover 1.2.10 window.

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml/badge.svg)](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml)
[![Issues](https://img.shields.io/github/issues/xin-yi33/RxyCode)](https://github.com/xin-yi33/RxyCode/issues)
[![Stars](https://img.shields.io/github/stars/xin-yi33/RxyCode?style=social)](https://github.com/xin-yi33/RxyCode/stargazers)

</div>

## Desktop GUI — the 1.3.0 jump

1.2.10 proved Electron could spawn `python -m appserver`. **1.3.0 is the workbench:** pinned / project / recent sessions, running-task chrome, permission presets, a plugin hub, side chat, plan / goal, and a Windows installer that still lets you pick the folder and a desktop shortcut. Linux gets an AppImage. **This tag does not ship macOS.**

The clip is a live recording of <code>rxycode gui</code> (RxyCode Desktop), not a mock.

<p align="center">
  <video width="800" controls muted playsinline preload="metadata">
    <source src="docs/assets/gui-demo-v1.3.0.mp4" type="video/mp4">
    <a href="docs/assets/gui-demo-v1.3.0.mp4">RxyCode Desktop 1.3.0 live recording (mp4)</a>
  </video>
</p>

| OS | What to download from [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) |
|----|--------|
| Windows | `rxycode-desktop-1.3.0-setup.exe` (installer: default `%USERPROFILE%\.rxycode\desktop`, Browse…, desktop shortcut checked) or `RxyCode.Desktop-1.3.0-win.zip` (portable) |
| Linux | `rxycode-desktop-1.3.0.AppImage` (`chmod +x`; if it exits immediately, `APPIMAGE_EXTRACT_AND_RUN=1 ./rxycode-desktop-1.3.0.AppImage`) |
| macOS | Not packaged. Use OpenTUI, or `npm run dev` from source |

<code>rxycode gui</code> only launches an installed Desktop tree
(<code>~/.rxycode/desktop</code>, <code>RXYCODE_DESKTOP_DIR</code>, or <code>--desktop-dir</code>).
A CLI-only install cannot start Electron. Composer still sits at the bottom of the task pane. The `+` button still opens 文件和文件夹 / 在项目中使用 / 目标 / 计划模式. Plan cards still offer **是，实施此计划**, **补充说明**, and **跳过**. Permission labels are 更改前询问 / 自动编辑 / 完全访问. Settings → 关于 shows **1.3.0**. Full GUI notes: [docs/GUI.md](docs/GUI.md).

## CLI / OpenTUI

Default CLI is still **OpenTUI**. In `cmd` (or any terminal):

```bat
rxycode
```

<p align="center">
  <video width="800" controls muted playsinline preload="metadata">
    <source src="docs/assets/cli-demo-v1.3.0.mp4" type="video/mp4">
    <a href="docs/assets/cli-demo-v1.3.0.mp4">RxyCode OpenTUI live recording (mp4)</a>
  </video>
</p>

Same <code>Session</code>, same safety gate, different surface. Play the mp4 above.

RxyCode is a Python coding agent. The core is headless: `Session` (`core/session.py`) wraps `AgentV2`. Frontends: **Desktop** (`rxycode gui`), **OpenTUI** (default CLI), and **Ink** fallback. Complex work goes through LangGraph: plan → decompose → execute → validate → synthesize. Simple questions take a fast path. Isolated child agents, MCP, and 30+ tools sit behind a risk-classified safety gate.

## What 1.3.0 actually changes

| Before 1.3.0 | After 1.3.0 |
|---|---|
| Latest GitHub Release was CLI `tar.gz` only; Desktop leftover on v1.2.10 | This tag ships **Desktop + CLI**. Windows setup.exe / zip and Linux AppImage are first-class assets |
| GUI was “a chat window that could start the backend” | Three-column workbench: session taxonomy, running row, sash snap, plugin hub, side chat |
| New Desktop session on Windows could sit on Starting Agent worker until a 600s timeout | Worker bootstrap no longer deadlocks against piped stdin (`appserver/agent_worker.py`) |
| Plugin connect was PAT-shaped | GitHub / Canva use `plugin/connect/start`; tokens stay in plugin `user.json` |

The in-repo latency / cache floors are unchanged: simple first token **1s**, complex first token **3s**, Primary prefix-cache **97%** (Phase L / M). They are gates on the same AgentV2 prefix, not a GUI marketing number.

## Features and advantages

| Feature | What you get | Where |
|---|---|---|
| Desktop workbench | Sessions, projects, permissions, plugins, plan / goal on the same protocol | `frontend/desktop-app/`, `appserver/` |
| Verify before “done” | A validator checks tool results against the original goal | `validation/` |
| Plan then execute | Hierarchical decomposition, dependency-aware parallel runs, then synthesis | `planning/`, `execution/`, `synthesis/`, `core/graph.py` |
| Safety gate on every tool | READ / WRITE / DANGER, write whitelist, approval dialogs, audit log | `core/safety/` |
| OpenTUI still default CLI | Type `rxycode` in cmd; stdio JSON-RPC | `frontend/opentui-app/` |
| Isolated child agents | Own session, tools, permissions, and budget | `core/subagents/` |
| Optional expert teams | Coordinator + SOP; **off** unless `settings.agents.enabled` | `core/agents/` |
| Headless core | `Session.prompt()` has no UI of its own; TUI and GUI only subscribe to protocol events | `core/session.py` |

## Quick start

### Requirements

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | Backend runtime |
| Bun | latest | Auto-installed by the one-command installer when missing (OpenTUI) |
| Node.js | 20+ | Desktop GUI, Ink fallback (`RXYCODE_TUI=ink`) |
| OpenAI-compatible API key | — | Any provider you configure (OpenAI, DeepSeek, OpenCode Go, …) |

### Option 1: One-command install (CLI / OpenTUI)

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.ps1 | iex"
rxycode
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.sh | sh
rxycode
```

The installer bootstraps `uv` if needed, creates an isolated tool environment, and installs the pinned **`v1.3.0`** release. That is the **CLI / OpenTUI** package. It does not include the Electron Desktop app.

Set `RXYCODE_NO_MODIFY_PATH=1` to skip PATH updates. A PATH-update failure is a warning; the install still succeeds.

**Downloads:** the latest release (**`v1.3.0`**) publishes `rxycode-1.3.0.tar.gz` plus Desktop assets (`rxycode-desktop-1.3.0-setup.exe`, `RxyCode.Desktop-1.3.0-win.zip`, `rxycode-desktop-1.3.0.AppImage`). It does not ship a wheel or a macOS build. GitHub “Source code” zip/tar.gz is the full backend+frontend tree for building from source — it is not a ready-to-run Desktop install. More detail: [docs/quickstart.md](docs/quickstart.md).

### Option 2: Run once with uv

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0" rxycode
```

### Option 3: Permanent install

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0"
rxycode
```

### Option 4: From source

```bash
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode
python -m pip install -e .
rxycode
```

### Option 5: Docker

```bash
cp .env.example .env   # Set OPENAI_API_KEY and RXYCODE_API_TOKEN
docker compose up -d api       # API server (loopback only)
docker compose run --rm tui    # Interactive TUI (needs TTY)
```

### First launch

| Command | What opens |
|---------|------------|
| `rxycode` or `python -m RxyCode` | Default **OpenTUI** |
| `rxycode --version` | Package version, no runtime init |
| `rxycode gui` | Desktop **only after** you install a Desktop build (not part of the CLI/`uv` install) |
| `rxycode --api` | API server only (`api_server.py`) |
| `RXYCODE_TUI=ink rxycode` | Ink fallback TUI |

1. Run `rxycode`. The TUI opens even with no model configured.
2. If the model list is empty, OpenTUI shows a welcome hint and opens `/addmodel` (credentials are masked).
3. If at least one model is already in `~/.RxyCode/config.yaml`, there is no extra hint.
4. Type a natural-language task. Example: write a single-file `click-counter.html` in the current folder.
5. Headless (`rxycode --api`): set `RXYCODE_API_KEY` and run `rxycode config add-model <id> <provider-model-id> --base-url <url>`. The key is never accepted on the command line.

OpenTUI talks to the core over **stdio JSON-RPC**: the frontend spawns `python -m appserver`, which hosts `Session` → `AgentV2`. You see streaming tokens, tool calls, approval prompts when needed, and a final answer.

## Architecture

```
OpenTUI (frontend/opentui-app)     Desktop (frontend/desktop-app)
        │ stdio JSON-RPC                    │ stdio JSON-RPC
        └──────────────┬────────────────────┘
                       ▼
              python -m appserver
                       │
                       ▼
              Session (core/session.py)
                       │
                       ▼
              AgentV2 (core/agent_v2.py)
                 ├── simple query  →  fast path + cache
                 ├── multi-task    →  isolated child agents
                 ├── compose       →  Plan + Build
                 └── complex       →  LangGraph:
                       goal_planner → decomposer → executor
                            → ToolOrchestrator + core/safety
                            → validator → synthesizer

Ink fallback: RXYCODE_TUI=ink → api_server.py (HTTP + SSE) → same Session
```

`Session` is transport-agnostic: it emits protocol events; it does not draw UI. `appserver` maps those events to stdout JSON-RPC. `api_server.py` maps the same events to SSE for Ink.

## Modes

| Surface | How | Behavior |
|---------|-----|----------|
| Build | `/build` (TUI) or Desktop default | Plan → decompose → execute → validate → synthesize |
| Plan | `/plan` or Desktop 计划模式 | Read-only analysis and a plan document; no file edits until you Build |
| Compose | `/compose` | Plan + build with a shorter pipeline |

## Configuration

Stored at `~/.RxyCode/config.yaml`. The active model's `base_url` is the one you selected — RxyCode does not silently rewrite it to another provider.

```yaml
cache:
  enabled: true
  prompt_prefix_cache: true   # Provider-side KV cache
  ttl: 3600

# Example: OpenCode Go
models:
  opencode-go/deepseek-v4-flash:
    model_name: deepseek-v4-flash
    provider_id: opencode-go
    provider_name: OpenCode Go
    api_key_env: OPENCODE_GO_API_KEY   # or api_key_secret, stored outside the repo
    base_url: https://opencode.ai/zen/go/v1
    max_tokens: 8192
    temperature: 0.7
```

Use `/addmodel` in OpenTUI for a guided wizard. Do not put API keys in the repo, README, or screenshots.

## Safety boundary

Before a tool runs, `core/safety/` classifies it:

- **READ** — inspect only (`read`, `grep`, `glob`, `webfetch`, …)
- **WRITE** — reversible side effects (`write`, `edit`, most `bash`)
- **DANGER** — destructive or installer-like commands; bash can escalate by pattern (`rm -rf /`, `git push --force`, …)

Writes outside the whitelist are blocked. The TUI and Desktop raise an approval dialog; the audit log is `~/.RxyCode/logs/audit.jsonl` with sensitive keys redacted. Default Desktop permission is 更改前询问.

## Commands and shortcuts (OpenTUI)

| Command | Description |
|---------|-------------|
| `/help` | All commands (includes expert-team / subagent usage) |
| `/agents on` `/team <task>` | Expert team (off by default; everyday coding stays solo) |
| `/addmodel` | Add a model (masked credentials) |
| `/models` / `/model <name>` | List / switch models |
| `/build` `/plan` `/compose` | Work mode |
| `/clear` | Clear conversation context |
| `/memory add/list/search` | Memory |
| `/queue add/run` | Task queue |
| `/cache` | Cache stats |
| `/language` | UI language |
| `/thinking` | Thinking panel |
| `/children` `/child` `/parent` | Isolated child-agent tree (on by default; `RXYCODE_SUBAGENTS=0` disables) |

| Shortcut | Action |
|----------|--------|
| `Tab` | Switch work mode |
| `Ctrl+P` | Command palette |
| `Ctrl+T` | Toggle thinking |
| `Esc` | Cancel |
| `Ctrl+C` | Copy / cancel stream / clear input; twice within 2s to quit |

## Version history

| Version | Date | Highlights |
|---------|------|------------|
| [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) | 2026-09 | **Desktop workbench** (sessions / plugins / permissions / plan); Windows setup.exe + zip and Linux AppImage; worker bootstrap deadlock fix; CLI is still OpenTUI; no macOS build |
| [v1.2.12](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.12) | 2026-08 | Muse Spark + HY3 providers; Responses reasoning replay; custom `resource_path`; GitHub Release is `rxycode-1.2.12.tar.gz` only — Desktop stays on v1.2.10 |
| [v1.2.11](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11) | 2026-08 | Expert teams (off by default); CLI reliability; GitHub Release is `rxycode-1.2.11.tar.gz` only — Desktop stays on v1.2.10 |
| [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) | 2026-08 | First Desktop Plan / Goal / `+` menu; plan card Build/Revise/Skip; default CLI remains OpenTUI (`rxycode`) |
| [v1.2.9](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.9) | 2026-08 | Isolated subagents (Phase C): independent child sessions; `@agent` mention, Task tool, `subtask=true`; OpenTUI child tree |
| [v1.2.8](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.8) | 2026-08 | Model adaptation: DeepSeek v4, Doubao (ark), Anthropic Claude 5 family; exact capability isolation |
| [v1.2.7](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.7) | 2026-08 | Completed answers no longer discarded by failed read-only probes; smarter web-research queries; Doubao provider |
| [v1.2.6](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.6) | 2026-08 | webfetch decoding, MCP mis-routing, Windows shell/encoding, web search hardening |
| [v1.2.5](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.5) | 2026-08 | DeepSeek / Qwen / Claude adaptation; lazy imports; explicit request routing; stdio transport |
| [v1.2.4](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.4) | 2026-08 | Add-model polish; eval harness; typed protocol + TypeScript client |
| [v1.2.3](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.3) | 2026-07 | 10 provider presets, auto discovery, batch add |
| [v1.2.2](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2) | 2026-07 | Auto-install Bun + OpenTUI deps; empty-model `/addmodel` |
| [v1.2.1](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.1) | 2026-07 | Ship OpenTUI sources in the wheel |
| [v1.2.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.0) | 2026-07 | OpenTUI default TUI (Ink fallback) |
| [v1.1.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.1.0) | 2026-07 | Ink TUI, SSE, Docker, CI, one-command installers |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | LangGraph rewrite: plan-and-execute, tools, tiered memory |
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | Initial release: verification + MCP |

Full notes: [CHANGELOG.md](CHANGELOG.md). Per-version copy: [docs/release-notes/](docs/release-notes/). Expert teams: [docs/agent/README.md](docs/agent/README.md).

## License

[MIT](LICENSE) © RxyCode contributors

If RxyCode is useful, [star the repo](https://github.com/xin-yi33/RxyCode) so you can find it again. Bugs and ideas: [Issues](https://github.com/xin-yi33/RxyCode/issues).
