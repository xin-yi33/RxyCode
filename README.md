<!-- README_SYNC: source=working-tree; updated=2026-09 -->
<div align="center">

**English** · [简体中文](./README.zh-CN.md)

# 🚀 RxyCode

**Open-source local AI coding agent. Choose your model, keep your code on your machine.**

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0)
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

### 🏠 100% Local & Privacy-First

Claude Code requires an Anthropic subscription; Codex runs entirely on external servers. RxyCode is MIT licensed and runs locally. Your code stays strictly on your machine. Bring your own keys—native support for DeepSeek, Qwen, Kimi, Doubao, GLM, SiliconFlow, OpenAI, and Anthropic proxies with zero middleware lock-in.

### 🔧 30+ Built-in Tools & MCP Extensibility

| Domain | Tools |
|---|---|
| **Filesystem** | read, write, edit, patch, glob, grep, ls, view, open |
| **Terminal** | bash (timeout limits, stream capture, dynamic risk level) |
| **Git** | status, diff, commit, log, branch inspection |
| **Web Research** | websearch (free DDGS metasearch, no API key), webfetch, file_download |
| **Multimodal** | vision (image & screenshot analysis via multimodal LLMs) |
| **Code Intelligence** | format, diagnostics, LSP publishDiagnostics (experimental) |
| **Memory** | cross-session persistent facts (add/search/list/remove) |
| **Delegation** | isolated child agents, `@agent` mentions, subagent tasks |
| **Extensibility** | MCP client (stdio servers), skill manager |
| **Automation** | workflow scripts in isolated subprocesses |

Need database connectivity or specialized APIs? Plug in any Model Context Protocol (MCP) server:

```yaml
# ~/.RxyCode/config.yaml
mcpServers:
  postgres:
    type: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-postgres"]
    env:
      DATABASE_URL: "postgresql://..."
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
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0" rxycode
```

### 2. One-Command Installer (CLI)

The installer bootstraps `uv` (if missing) and configures an isolated runtime without touching system packages:

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.ps1 | iex"
  ```
- **macOS / Linux**:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.sh | sh
  ```

Launch anytime by running `rxycode`.

### 3. Docker Container Deployment

Ideal for sandbox isolation or hosting an always-on headless API service.

**Step 1: Clone repo & prepare environment**
```bash
git clone https://github.com/xin-yi33/RxyCode.git && cd RxyCode
cp .env.example .env
# Edit .env and supply OPENAI_API_KEY and a secure RXYCODE_API_TOKEN
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
docker build -t rxycode:latest .
docker run -it --rm -v ~/.rxycode:/root/.rxycode --env-file .env rxycode:latest
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

## 🖥️ How to Use

### Terminal Workflow (OpenTUI Default)

Launch with `rxycode` and submit natural language prompts:

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

### 🖥️ Desktop Client (Desktop GUI)

Install the desktop build and run `rxycode gui`.

<p align="center">
  <img src="docs/imgs/gui-shell.png" alt="RxyCode Desktop Shell" width="700">
</p>

- **Plan Cards**: Visual step-by-step implementation breakdown with "Build", "Revise", and "Skip" actions.
- **Goal Dialog**: Persistent objective tracking to keep long-running tasks focused.
- **Composer `+` Menu**: Quick attachment of local files/folders and workspace selection.
- **Granular Permissions**: Ask Before Change / Auto Edit / Full Access.

<details>
<summary>Desktop Screenshots</summary>

<p align="center">
  <img src="docs/imgs/gui-plus-menu.png" alt="Composer Plus Menu" width="700">
</p>
<p align="center">
  <img src="docs/imgs/gui-goal-dialog.png" alt="Goal Dialog" width="700">
</p>
<p align="center">
  <img src="docs/imgs/gui-plan-card.png" alt="Plan Card" width="700">
</p>
</details>

### Headless API Service

```bash
rxycode --api   # Launches FastAPI HTTP + SSE service on port 8765
```

---

## 🏗️ Architecture

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

Distributed under the [MIT](LICENSE) License.
