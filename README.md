<!-- README_SYNC: source=working-tree; updated=2026-09 -->
<div align="center">

**English** · [简体中文](./README.zh-CN.md)

# 🚀 RxyCode

**Open-source local AI coding agent. The app runs on your machine; model traffic follows the endpoint you configure.**

[⭐ Star this repo](https://github.com/xin-yi33/RxyCode) if you want a local agent that plans, runs tools, and asks before risky writes.

[![Version](https://img.shields.io/badge/version-1.4.0-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.0)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml/badge.svg)](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/xin-yi33/RxyCode?style=social)](https://github.com/xin-yi33/RxyCode/stargazers)

<p>
  <img src="docs/assets/cli-demo.gif" alt="RxyCode Terminal Demo" width="800">
</p>

[⭐ Star](https://github.com/xin-yi33/RxyCode) &nbsp;·&nbsp; [⚡ Quick Start & Deployment](#-quick-start--deployment) &nbsp;·&nbsp; [🔑 Key Highlights](#-key-highlights) &nbsp;·&nbsp; [🖥️ How to Use](#️-how-to-use) &nbsp;·&nbsp; [Docs](docs/)

</div>

RxyCode is an autonomous coding agent running locally on your hardware. Bring an API key for any OpenAI-compatible model (DeepSeek, Qwen, Kimi, Claude, GPT, GLM, Doubao, or custom endpoints), and RxyCode takes over: decompose tasks, code solutions, execute commands, research the web, and mechanically verify the outcome. Terminal TUI out-of-the-box, optional Desktop GUI, and extensible with MCP and Skills.

> 💡 **Want a quick test drive?** Run instantly without installation if you have Python 3.10+:  
> `uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0" rxycode`  
> See [⚡ Quick Start & Deployment](#-quick-start--deployment) for complete install options, Desktop app, Docker, and Node.js frontend builds.

---

## 🔑 Key Highlights

### 👥 Multi-Agent Architecture & Deterministic Expert Teams

RxyCode goes far beyond a single-prompt ReAct loop.

**Isolated Subagents**: For complex workloads, RxyCode spawns isolated child agents. Each child receives its own session, scoped tools, write permissions, and token budgets. Inspect the hierarchy with `/children` or dispatch tasks directly using `@agent` syntax.

**Expert Team Mode**: Toggle `/agents on` to engage a full software organization rather than a lone agent. The built-in `software_dev` pack features 10 specialized roles across 7 stages:

```
PM → Architect → Frontend Engineer ∥ Backend Engineer → QA Tester → Mechanical Gate → Security ∥ Quality ∥ Maintainability Audit → Documentation
```

Engineering design principles:
- **Deterministic SOP State Machine**: Stage transitions are driven by code, not hallucinated LLM decisions. Unlike CrewAI's hidden prompt routing or AutoGen's runaway chat loops, RxyCode's SOP is fully auditable and predictable.
- **Concurrent Implementation & 3-Perspective Auditing**: Frontend and backend coders implement concurrently; security, quality, and maintainability reviewers audit in parallel.
- **Mechanical Verification Gate**: Code syntax, parsing, linting, and automated tests run first before invoking LLM auditors. Verdicts are cryptographically tied to the commit SHA-256.
- **Four Cost Fuses (BudgetGuard)**: Enforces hard ceilings on token spend, wall-clock time, delegation hops, and consultation turns. If any fuse trips, execution halts gracefully and yields partial deliverables.
- **Disabled by Default**: Benchmark evals show solo mode is faster and cheaper for standard tasks (team mode consumes ~3x tokens and ~2.5x time). Reserve team mode for large, modular projects.

You can also author custom teams by defining roles, SOP stages, and toolsets in a clean YAML specification validated by `validate_team`.

### 🧠 Plan → Execute → Verify Pipeline

Complex work flows through an explicit LangGraph state machine:

1. **Goal Planning**: Analyzes intent and constructs an executable `TaskTree` (up to 4 levels, 64 nodes max).
2. **DAG Scheduling**: Resolves dependency graphs to dispatch independent read/write tasks concurrently.
3. **Context-Isolated Execution**: Each subtask receives context strictly filtered through its ancestor chain, avoiding prompt clutter and token waste.
4. **Deterministic Validation**: Runs deterministic checks (syntax parsing, file diffs, test runs), then reconciles outputs against original acceptance criteria. Failures are classified (planning vs. reasoning vs. tooling) to guide intelligent replanning.
5. **Grounded Synthesis**: Every claim in the final answer must cite concrete tool evidence (file diffs or command exits). No hallucinations.

Simple queries and greetings automatically take an optimized fast path backed by two-level caching (exact hash + semantic similarity).

### 🛡️ Defense-in-Depth Safety Gate

Every tool invocation passes through a policy gate before touching your system:

| Risk Level | Operations | Policy |
|---|---|---|
| **READ** | File reading, grep, web fetching | Auto-approved |
| **WRITE** | File modifications, code editing, standard shell commands | Requires approval (configurable to auto) |
| **DANGER** | `rm -rf /`, `git push --force`, `format C:`, installers | Always blocks for explicit user confirmation |

- **Dynamic Command Escalation**: Regular shell calls default to WRITE, but commands matching high-risk signatures automatically escalate to DANGER.
- **Write Whitelist**: Enforces workspace confinement. Modifying paths outside project root or `~/.RxyCode/output/` fails closed.
- **Dry-Run Mode**: Set `RXYCODE_DRY_RUN=1` to simulate actions without disk or network side effects.
- **Audit Logging**: All actions append to `~/.RxyCode/logs/audit.jsonl` with credentials and API tokens masked.

### 🏠 Local Runtime vs Model Traffic

Claude Code requires an Anthropic subscription; Codex runs the agent loop on remote servers. RxyCode is MIT licensed: **the program, the git workspace, and encrypted API keys stay on your machine.** That is not the same as “no code ever leaves this computer.”

| Stays on this machine | Leaves this machine when you use a cloud model |
|---|---|
| Desktop / TUI / CLI process | Current prompt and system instructions |
| Files on disk until a tool reads them | Recent turns still in the context window |
| Keys in `~/.RxyCode/` (Windows DPAPI / POSIX `0600`) | File excerpts, diffs, and command output already returned by tools this session |
| Audit log `~/.RxyCode/logs/audit.jsonl` | Images, if you use vision |

The whole repository is **not** uploaded automatically. Only content the agent actually read or produced, then placed into the model messages, is sent. `websearch` sends the query to DDGS; `webfetch` contacts the target URL; MCP servers see whatever those tools return. Bring your own keys—DeepSeek, Qwen, Kimi, Doubao, GLM, SiliconFlow, OpenAI, Anthropic proxies—with no middleware lock-in.

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.0/install.ps1 | iex"
rxycode
```

MCP tools share the same safety gate, audit log, and retry backoff as built-in tools.

### 🧠 Tiered Memory Architecture & Codebase RAG

RxyCode remembers across sessions:
- **Short-Term Memory**: Sliding window of recent message exchanges.
- **Long-Term Compression**: Summarizes past reasoning and tool runs beyond threshold limits.
- **User Knowledge**: Explicit persistent facts recorded via `/memory add`.
- **Vector Experience Store**: Retrieves proven past plans and successful patterns for related queries.
- **Codebase Vector RAG**: AST-guided chunking + float32 Numpy vector store + PageRank symbol repository map. Debounced background workers incrementally index on file save.

---

## ⚡ Quick Start & Deployment

Choose the installation or deployment method that best fits your workflow:

### 1. Instant Trial (Recommended)

Requires only Python 3.10+. No global installation, instant execution:

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.0/install.sh | sh
rxycode
```

The installer bootstraps `uv` if needed, creates an isolated tool environment, and installs the pinned **`v1.4.0`** release. That is the **CLI / OpenTUI** package. It does not include the Electron Desktop app.

The installer bootstraps `uv` (if missing) and configures an isolated runtime without touching system packages:

**Downloads:** the latest release (**`v1.4.0`**) publishes **one** asset: `rxycode-1.4.0.tar.gz`. It does not ship a wheel or new Windows / macOS / Linux Desktop binaries. Desktop installers and portable zips stay on the still-open **[v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10)** release (`RxyCode.Desktop-1.2.10-win.zip`, setup.exe, dmg, AppImage). GitHub “Source code” zip/tar.gz is the full backend+frontend tree for building from source — it is not a ready-to-run Desktop install. More detail: [docs/quickstart.md](docs/quickstart.md).

Launch anytime by running `rxycode`.

### 3. Docker Container Deployment

Ideal for sandbox isolation or hosting an always-on headless API service.

**Step 1: Clone repo & prepare environment**
```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.4.0" rxycode
```

**Step 2: Start container**
- **Option A: Headless API Service (Daemon)**
  ```bash
  docker compose up -d api
  ```
  Exposes the FastAPI HTTP + SSE streaming server on port 8765.
- **Option B: Interactive Terminal TUI (Requires TTY)**
  ```bash
  docker compose run --rm tui
  ```

**Manual Single Image Build:**
```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.4.0"
rxycode
```

### 4. Node.js Frontend Development & Build

RxyCode features decoupled frontend surfaces communicating via stdio JSON-RPC:

- **Default OpenTUI (Bun + React 19)**:  
  Source at `frontend/opentui-app/`. CLI installer bundles or installs Bun automatically. To develop:
  ```bash
  cd frontend/opentui-app
  bun install
  bun run build
  ```
- **Ink Fallback TUI (Node.js 20+ + React 18)**:  
  Source at `frontend/`. If your environment prefers standard Node.js:
  ```bash
  cd frontend
  npm install
  npm run build
  # Launch with Ink engine:
  RXYCODE_TUI=ink rxycode
  ```
- **Desktop GUI (Electron 39 + Vite + React)**:  
  Source at `frontend/desktop-app/`:
  ```bash
  cd frontend/desktop-app
  npm install
  npm run dev       # Start development mode
  npm run build     # Package installers (Windows / macOS / Linux)
  ```
  > Everyday users do not need to compile the desktop client manually. Grab prebuilt installers from the [v1.3.0 Release](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0):
  > - **Windows**: Run `rxycode-desktop-1.3.0-setup.exe` or extract portable `RxyCode.Desktop-1.3.0-win.zip`.
  > - **Linux**: Run `rxycode-desktop-1.3.0.AppImage` (after `chmod +x`).
  > - Launch anytime via `rxycode gui` once installed. *(Note: macOS prebuilt binary is omitted for v1.3.0; please use the CLI or run from source).*

### 5. Python Source Installation

For developers and contributors:

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

---

## 🤖 First Launch & Model Configuration

After installation, run `rxycode` in any terminal:

1. **Setup Wizard**: If no model is configured, the `/addmodel` setup dialog opens automatically.
2. **Encrypted Storage**: Sensitive API keys are masked and encrypted using platform security (Windows DPAPI, POSIX `0600` files). Keys are never committed or printed.
3. **Preset Providers**:

| Provider | Typical Models | Integration Highlights |
|---|---|---|
| **DeepSeek** | `deepseek-v4`, `deepseek-v4-flash` | Native reasoning_content parsing & thinking effort levels |
| **Moonshot (Kimi)** | `kimi-k3`, `kimi-k2.7-code` | Prompt cache support & reasoning_effort controls |
| **Aliyun Qwen** | `qwen3.7-max`, `qwen3.8-max-preview` | Explicit prompt cache breakpoint control |
| **Volcengine Doubao** | `doubao-seed-2.1-turbo` | Volcano Ark API integration |
| **Zhipu GLM** | `glm-5.2` | GLM native streaming protocol |
| **SiliconFlow** | Open-source models | Low latency high-throughput routing |
| **OpenAI** | `gpt-4o`, `o1`, `o3` | Standard OpenAI endpoints |
| **Anthropic** | `claude-sonnet-4.5` | Thinking blocks and explicit cache controls via proxy |
| **OpenRouter / Groq** | Aggregated & fast models | Standard OpenAI format compatibility |

Configuration resides in `~/.RxyCode/config.yaml`. Manage models anytime via `rxycode config list` or `/models` inside the TUI.

---

## 🖥️ Surfaces & Experience
 
### Desktop GUI
 
v1.3.0 delivers a complete 3-column desktop workbench: session organization (pinned/project/recent), full-row running-task chrome, snapping sashes, permission presets, side chat, and plan / goal modes.
 
Here is a live recording of <code>rxycode gui</code> (RxyCode Desktop):
 
<p align="center">
  <video width="800" controls muted playsinline preload="metadata">
    <source src="docs/assets/gui-demo-v1.3.0.mp4" type="video/mp4">
    <a href="docs/assets/gui-demo-v1.3.0.mp4">RxyCode Desktop 1.3.0 Live Recording (mp4)</a>
  </video>
</p>
 
| OS | Assets from [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) |
|----|---------------------------------------------------------------------------------|
| Windows | `rxycode-desktop-1.3.0-setup.exe` (installer wizard) or `RxyCode.Desktop-1.3.0-win.zip` (portable) |
| Linux | `rxycode-desktop-1.3.0.AppImage` (`chmod +x` then run) |
| macOS | Not packaged for v1.3.0. Use terminal CLI or `npm run dev` from source |
 
<code>rxycode gui</code> only launches an installed Desktop tree (recognizes <code>~/.rxycode/desktop</code>, <code>RXYCODE_DESKTOP_DIR</code>, or <code>--desktop-dir</code>). Composer sits at the bottom; clicking `+` attaches files, opens workspaces, or toggles plan mode. Plan cards offer "Build", "Revise", and "Skip". Permissions support Ask Before Change / Auto Edit / Full Access. See [docs/GUI.md](docs/GUI.md) for full details.
 
## CLI / OpenTUI
 
The default terminal interface is **OpenTUI**. In any terminal:
 
```bash
rxycode
```
 
<p align="center">
  <video width="800" controls muted playsinline preload="metadata">
    <source src="docs/assets/cli-demo-v1.3.0.mp4" type="video/mp4">
    <a href="docs/assets/cli-demo-v1.3.0.mp4">RxyCode OpenTUI Live Recording (mp4)</a>
  </video>
</p>
 
Submit natural language prompts:
 
- `"Refactor auth service from session cookies to JWT with refresh tokens"`
- `"Audit this repository for SQL injection or unsafe path traversal vulnerabilities"`
- `"Generate a comprehensive test suite for user service using pytest"`
- `"Summarize Python 3.13 free-threaded GIL changes and output to docs/python313.md"`
 
Key Shortcuts:
 
| Key | Action |
|---|---|
| `Tab` | Toggle working mode (Build / Plan / Compose) |
| `Ctrl+P` | Open command palette |
| `Ctrl+T` | Toggle thinking / reasoning panel |
| `Esc` | Cancel running operation / dismiss dialogs |
 
<details>
<summary>Common Slash Commands</summary>
 
| Command | Action |
|---|---|
| `/build` | Plan → execute → verify (default autonomous mode) |
| `/plan` | Read-only analysis and plan generation; no file modifications |
| `/compose` | Streamlined plan + execute pipeline |
| `/addmodel` | Interactive model provider setup wizard |
| `/models` | List and switch configured models |
| `/agents on` | Enable multi-agent expert team mode |
| `/team <task>` | Assign task directly to the expert team |
| `/memory add/list/search` | Manage cross-session persistent facts |
| `/children` `/child` `/parent` | Inspect and navigate child agent tree |
| `/language` | Switch UI language (`zh` / `en`) |
| `/help` | Display comprehensive command reference |
</details>

### Headless API Service

```bash
rxycode --api   # Launches FastAPI HTTP + SSE service on port 8765
```

---

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

## Desktop GUI

v1.4.0 does **not** republish Desktop. Download the still-open [v1.2.10 GitHub Release](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10):

| OS | Asset |
|----|--------|
| Windows | `rxycode-desktop-1.2.10-setup.exe` (installer) or `RxyCode.Desktop-1.2.10-win.zip` (portable) |
| macOS | `.dmg` (unsigned) |
| Linux | `.AppImage` (`chmod +x`; if it exits immediately, `APPIMAGE_EXTRACT_AND_RUN=1 ./rxycode-desktop-1.2.10.AppImage`) |

`rxycode gui` only launches that installed app (`~/.rxycode/desktop`, `RXYCODE_DESKTOP_DIR`, or `--desktop-dir`). A CLI-only install cannot start Desktop. Composer sits at the bottom of the task pane. The `+` button opens:

| Menu item | What it does |
|-----------|----------------|
| 文件和文件夹 | Attach a local file; the path is written into the prompt |
| 在项目中使用 | Pick a workspace and start a new chat |
| 目标 | Open the Goal dialog (Escape or overlay click closes it) |
| 计划模式 | Toggle Plan mode (agent stays on the plan document) |

Plan cards offer **是，实施此计划**, a **补充说明** field, and **跳过**. Permission labels in the UI are 更改前询问 / 自动编辑 / 完全访问. Switching to 完全访问 asks for confirmation (Escape cancels). Packaged v1.2.10 Desktop shows **1.2.10** in Settings. Full GUI notes: [docs/GUI.md](docs/GUI.md).

<p align="center">
  <img src="docs/imgs/gui-shell.png" alt="RxyCode Desktop chat shell" width="800">
</p>
<p align="center">
  <img src="docs/imgs/gui-plus-menu.png" alt="Composer plus menu: attach, workspace, goal, plan" width="800">
</p>
<p align="center">
  <img src="docs/imgs/gui-goal-dialog.png" alt="Goal dialog" width="800">
</p>
<p align="center">
  <img src="docs/imgs/gui-plan-card.png" alt="Plan card with Build, Revise, and Skip" width="800">
</p>

## Architecture

```
rxycode (OpenTUI) / rxycode gui (Desktop) / rxycode --api
                     │
                     ▼ (stdio JSON-RPC / HTTP SSE)
       appserver (Worker subprocess isolation / Watchdog)
                     │
                     ▼
         Session (Headless facade, zero UI imports)
                     │
                     ▼
                 AgentV2
  ┌─────────────────────────────────────────────────────────┐
  │  Simple queries → Fast path + 2-level cache             │
  │                                                         │
  │  Complex coding → LangGraph DAG pipeline:               │
  │  [Goal Planner] → [Decomposer] → [Parallel Exec] →      │
  │  [Validator] → [Reflection] → [Synthesis]               │
  │                                                         │
  │  Multi-Agent Subsystems:                                │
  │  ├─ Isolated Child Sessions (Scoped tools & budgets)   │
  │  └─ Expert Teams (Coordinator + Deterministic SOP):     │
  │       pm → architect → coder(∥) → tester → verifier     │
  │          → 3-way audit(∥) → doc                         │
  │                                                         │
  │  Tiered Infrastructure:                                 │
  │  ├─ Memory (Short-term / Compressed / Vector store)     │
  │  ├─ Code RAG (AST chunking / Numpy store / PageRank map)│
  │  └─ 30+ Tools + Safety Gate + Side-Effect Journal       │
  └─────────────────────────────────────────────────────────┘
```

---

## 📦 Requirements

| Requirement | Recommended Version | Notes |
|---|---|---|
| **Python** | 3.10+ | Core agent backend |
| **Bun** | latest | Default OpenTUI runtime (installer configures automatically) |
| **Node.js** | 20+ | Required only for Ink fallback or Electron desktop development |
| **API Key** | — | Any OpenAI-compatible provider credentials |

---

## 📋 Release History

| Version | Release Date | Key Features |
|---|---|---|
| [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) | 2026-09 | Major Desktop workbench release: 3-column session & project workspace, plugin rail, permission tiers; Windows installer & portable zip, Linux AppImage; fixes Windows worker bootstrap deadlock |
| [v1.2.11](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11) | 2026-08 | 10-role 7-stage SOP expert teams; Windows encoding improvements; 8MB stdio JSON-RPC throughput |
| [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) | 2026-08 | Electron desktop app (`rxycode gui`), Plan mode, Goal dialog, Composer plus menu |
| [v1.2.9](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.9) | 2026-08 | Phase C isolated child agents: `@agent` dispatch, Task tool, OpenTUI subagent tree |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | LangGraph rewrite: plan-and-execute pipeline, tiered memory, codebase RAG |
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | Initial public release: basic toolchain and native MCP integration |

Full changelog: [CHANGELOG.md](CHANGELOG.md).

## 🤝 Contributing

Review [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines. Issues and pull requests are warmly welcomed!

## 📄 License

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
| [v1.4.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.4.0) | 2026-09 | Product version **1.4.0** across CLI, OpenTUI, Ink, Desktop metadata, and appserver. Protocol stays `1.1.0`. |
| [v1.2.11](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11) | 2026-08 | Expert teams (off by default); CLI reliability; GitHub Release is `rxycode-1.2.11.tar.gz` only — Desktop stays on v1.2.10 |
| [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) | 2026-08 | Desktop Plan / Goal / `+` menu; plan card Build/Revise/Skip; default CLI remains OpenTUI (`rxycode`) |
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
