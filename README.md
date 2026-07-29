<div align="center">

# RxyCode

**Plan-and-Execute AI Coding Agent with Verification & Safe Tool Orchestration**

[![Version](https://img.shields.io/badge/version-1.2.2-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20+-339933.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-2477%20passed-brightgreen.svg)](#testing)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**[English](README.md)** | **[中文](README.zh-CN.md)**

</div>

<div align="center">
  <img src="docs/images/screenshot.png" alt="RxyCode TUI Screenshot" width="800">
</div>

---

RxyCode is a general-purpose AI agent built on LangGraph with a hierarchical
plan-and-execute architecture. It decomposes complex tasks into subtasks,
executes them with a safe tool orchestrator, validates results, and synthesizes
a final answer — all streamed live to an OpenTUI terminal UI (Ink fallback available).

### Why RxyCode?

- **Anti-hallucination** — A dedicated validator checks tool results against
  the original goal before reporting success
- **Plan & Execute** — Hierarchical task decomposition with dependency-aware
  parallel execution, not a linear ReAct loop
- **Safe by default** — Risk-level classification, write whitelist, approval
  dialogs, and full audit trail
- **Blazing fast** — Three-level cache (exact hash + semantic similarity +
  Provider KV), 50 ms token batching, fast-reply path for simple queries
- **Beautiful TUI** — OpenTUI/React/TypeScript frontend (default) with
  streaming output, ScrollBox chat, native textarea, and OpenCode-style panels;
  Bun is auto-installed by the one-command installer when missing; Ink remains
  as `RXYCODE_TUI=ink` fallback
- **30+ tools** — File ops, shell, web search/fetch, git, RAG, MCP, LSP, and more

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.10+ | Backend runtime |
| Bun | latest | Auto-installed by the one-command installer when missing (OpenTUI) |
| Node.js | 20+ | Optional Ink fallback (`RXYCODE_TUI=ink`) |
| OpenAI-compatible API key | — | Any provider (OpenAI, DeepSeek, etc.) |

### Option 1: One-command install (recommended)

**Windows PowerShell:**
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.2/install.ps1 | iex"
rxycode
```

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.2/install.sh | sh
rxycode
```

The installer bootstraps `uv` (if needed), creates an isolated tool
environment, and installs the pinned `v1.2.2` release. No manual clone
required. Previous release `v1.1.0` remains available via tag.

### Option 2: Run once with uv

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.2.2" rxycode
```

### Option 3: Permanent install

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.2"
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

1. Run `rxycode` — the TUI opens even without a model configured
2. If no models are configured yet, the TUI detects the empty list, shows a welcome hint, and automatically opens the `/addmodel` wizard (credential input is masked)
3. If one or more models are already configured, there is no extra hint and no auto dialog
4. Start chatting! Type your request in natural language

## Architecture

```
User Input
    │
    ▼
AgentV2 (core/agent_v2.py)
    │
    ├── Simple query  →  Fast path (single LLM call + cache check)
    ├── Multi-task    →  Sub-agents (parallel)
    ├── Compose       →  Plan + Build
    └── Complex       →  LangGraph Pipeline:
                              │
                 goal_planner → decomposer → executor → ToolOrchestrator
                                                → evidence → validator
                                                            → synthesizer
```

### Streaming Pipeline

```
Backend (Python)                          Frontend (TypeScript/OpenTUI)
─────────────────                         ──────────────────────────────
_raw_stream()                              chatApi.ts / App.tsx
  │                                          │
  ├── cache_control injection                fetch /chat/stream (SSE)
  │                                          │
  ├── OpenAI async stream                    parse SSE events:
  │   ├── reasoning_content → reasoning       ├── progress/reasoning/plan/step
  │   ├── content token → stream_token        ├── token → live assistant stream
  │   └── tool_calls delta                    ├── tool_call/tool_result
  │                                           ├── approval → ApprovalDialog
  └── StreamTUI → asyncio.Queue → SSE         └── final/done → terminal state
```

## Modes

| Mode | Command | Behavior |
|------|---------|----------|
| Build | `/build` | Full pipeline: plan → decompose → execute → validate → synthesize |
| Plan | `/plan` | Read-only analysis and planning, no file modifications |
| Compose | `/compose` | Plan + build with simplified pipeline |

## Directory Structure

| Directory | Purpose |
|-----------|---------|
| `core/` | AgentV2, LangGraph graph, state, prompts, UsageTrackingLLM |
| `planning/` | Goal refiner, task decomposer |
| `execution/` | Executor, tool orchestrator |
| `validation/` | Validator, re-planner |
| `synthesis/` | Output synthesizer |
| `frontend/opentui-app/` | **Default** OpenTUI/React TUI (Bun + React 19) |
| `frontend/` | Ink/React TUI fallback (`RXYCODE_TUI=ink`) |
| `tools/` | 30+ built-in tools (read, write, edit, bash, grep, web, git, ...) |
| `memory/` | Tiered memory (short-term, long-term, user, search) |
| `cache/` | Three-level cache (exact + semantic + Provider KV) |
| `config/` | Configuration management (`~/.rxycode/config.yaml`) |
| `rag/` | Codebase vector search (chunking, embedding, cosine) |
| `scheduler/` | Cron-like prompt scheduling |
| `recovery/` | Error recovery with retry logic |
| `mcp/` | MCP server integration |
| `lsp/` | LSP integration (experimental) |
| `safety/` | Risk levels, approval, write whitelist, audit |
| `evals/` | Evaluation harness (success rate, LLM-as-judge) |
| `tests/` | Python test suite (2319 deterministic tests) |

## Testing

### Frontend (TypeScript)
```bash
cd frontend && npm test    # 28 files / 158 tests
```

### Backend (Python)
```bash
python -m pytest tests -m "not live and not pty and not serial" -n 2 --dist loadscope -q
python -m pytest tests -m "serial and not live and not pty" -n 0 -q
# 2319 deterministic tests passed
```

## Configuration

Configuration is stored at `~/.rxycode/config.yaml`:

```yaml
cache:
  enabled: true
  prompt_prefix_cache: true   # Enable provider-side KV cache
  ttl: 3600

models:
  - name: deepseek-v4-flash
    provider: openai
    api_key: <your-key>        # Stored outside the repo, never committed
    base_url: https://api.deepseek.com
```

Use `/addmodel` in the TUI for a guided setup wizard.

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/addmodel` | Add a new model |
| `/models` | List all models |
| `/model <name>` | Switch model |
| `/build` `/plan` `/compose` | Switch work mode |
| `/clear` | Clear conversation context |
| `/memory add/list/search` | Memory management |
| `/queue add/run` | Task queue |
| `/cache` | View cache statistics |
| `/language` | Switch language |
| `/thinking` | Toggle thinking panel |

## Shortcuts

| Shortcut | Action |
|----------|--------|
| `Tab` | Switch work mode |
| `Ctrl+S` | Send message |
| `Ctrl+X` | Cancel current operation |
| `Ctrl+?` | Show help |
| `Ctrl+E` | External editor |
| `Ctrl+C` | Quit |

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | Initial release: ReAct + anti-hallucination + MCP |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | LangGraph rewrite: plan-and-execute, 24+ tools, tiered memory |
| [v1.1.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.1.0) | 2026-07 | Ink TUI, SSE streaming, Docker, CI/CD, one-command installers |
| [v1.2.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.0) | 2026-07 | Frontend rewrite: OpenTUI default TUI (Ink fallback), settings parity, safer Ctrl+C, plan hints, autoCompact |
| [v1.2.1](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.1) | 2026-07 | Package fix: ship OpenTUI sources in the installable wheel |
| [v1.2.2](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2) | 2026-07 | Auto-install Bun + OpenTUI deps so default UI works without manual Bun setup |

See [CHANGELOG.md](CHANGELOG.md) for the full change history.

## License

[MIT](LICENSE) © RxyCode contributors
