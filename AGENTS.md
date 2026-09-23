# RxyCode Module Documentation Index

> This index is designed for AI agent development. Each module README explains what the module is, how it works, where the core code is, and how it connects to other modules. Agents should read the relevant module README before making changes, instead of scanning all source code.
>
> Live build order: [`docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md`](docs/plans/opus5-plan/rxycode/architecture/DEV-ORDER.md). Architecture seams: [`docs/plans/opus5-plan/rxycode/architecture/MODULE-BOUNDARIES.md`](docs/plans/opus5-plan/rxycode/architecture/MODULE-BOUNDARIES.md). Do not treat `docs/RxyCode_PLAN.md` or Phase G cards as the live build order. Research first (PC0); do not reinvent wheels. The rest of `docs/plans/` stays gitignored; only `.../rxycode/architecture/` is tracked.
>
> **Plan docs:** `docs/plans/` (including `00-EXECUTION-PLAN.md` and `PHASE-A`…`PHASE-O`) is **gitignored**. It exists on disk but is invisible to git and to most agent file search. Tracked Phase G copies live under [`docs/phase-g/`](docs/phase-g/). Plugin/MCP wire contracts are [`docs/decisions/G-PROTOCOL-010`](docs/decisions/G-PROTOCOL-010.md) / [`016`](docs/decisions/G-PROTOCOL-016.md), not PHASE-K prose.

## Quick Reference

| Module | Location | Purpose |
|--------|----------|---------|
| [core](docs/modules/core.md) | core/ | Agent brain - AgentV2, LangGraph pipeline, prompts, state |
| core Phase-Fix files | core/turn_router.py, prefix_profile.py, prewarm.py, turn_context.py, handoff.py, catalog.py | Routing/prewarm/keep-alive decision tables and reserved seams — read core.md Phase Fix invariants before touching agent_v2 |
| [protocol](docs/modules/protocol.md) | protocol/ | Typed JSON-RPC protocol - pydantic models, JSON Schema, TS codegen |
| [appserver](docs/modules/appserver.md) | appserver/ | Stdio JSON-RPC server - headless core transport for OpenTUI/Desktop。OpenTUI `/session` 列表权威是 `sessions/list`（UPDATE-01 轨 H），不是 `chat_storage` |
| [config](docs/modules/config.md) | config/ | Configuration management - models, API keys, preferences |
| [providers](docs/modules/providers.md) | core/providers/ | Provider strategy layer - capabilities, matches, resolution |
| [cache](docs/modules/cache.md) | cache/ | Two-level **application** answer cache (precise hash + semantic similarity), distinct from provider prefix cache. Live AgentPrefix + deictic follow-ups (`?`) must not hit the answer cache — see UPDATE-01 track G / `docs/modules/core.md` Phase Fix prefix invariants |
| [memory](docs/modules/memory.md) | memory/ | Tiered memory - short-term, long-term, user memory, chat storage. `get_relevant_context("?")` returning empty is intentional anti-pollution; deictic follow-ups must use `_continue_agent_prefix` (UPDATE-01 U40), not this miss as sole context. Named `/save-chat` JSON is **not** the OpenTUI `/session` catalog (that is appserver `sessions/list`, UPDATE-01 轨 H) |
| [tools](docs/modules/tools.md) | tools/ | Tool system - 30+ tools for file ops, shell, web, git, etc. |
| [execution](docs/modules/execution.md) | execution/ | Task execution - executor, tool orchestrator, scheduler |
| [planning](docs/modules/planning.md) | planning/ | Task decomposition - hierarchical subtask planning |
| [synthesis](docs/modules/synthesis.md) | synthesis/ | Result synthesis - merge subtask results into final answer |
| [validation](docs/modules/validation.md) | validation/ | Result validation - check results against requirements |
| [recovery](docs/modules/recovery.md) | recovery/ | Error recovery - retry logic and error tracking |
| [safety](docs/modules/safety.md) | core/safety/ | Safety gate - risk levels, approval (TUI/SSE), write whitelist, audit |
| [evals](docs/modules/evals.md) | evals/ | Evaluation harness - task success rate, LLM-as-judge, baselines |
| [agents](docs/modules/agents.md) | core/agents/ | Expert team: Coordinator, SOP, verifier, budget, router |
| [rag](docs/modules/rag.md) | rag/ | Codebase vector search - chunking, embedding, cosine search, repo map |
| [tracing](docs/modules/tracing.md) | core/tracing.py | Node-level tracing - span collection, JSONL persistence, replay |
| [utils](docs/modules/utils.md) | utils/ | Shared utilities - TUI, streaming, i18n, shell helpers |
| [history](docs/modules/history.md) | history/ | File-change diff tracker for edit/write (not command or conversation logs) |
| [governance](docs/modules/governance.md) | core/governance.py | Rate limits, role-aware model routing, sensitive-action policy |
| [model-limits](docs/modules/model-limits.md) | config/ | Phase 3 output-limit parsing (config appendix, not a top-level package) |
| [mcp](docs/modules/mcp.md) | mcp/ | MCP integration - stdio servers only; tools still go through ToolOrchestrator |
| computer-use | core/cu/ | PP40 OCU MCP adapter (default-off). OS window tools (`list_apps` / `get_app_state` / `click` …). Not inside agent_v2. **Not** the Playwright/Chrome card. Task-bounded web-window use is **U46**, not a silent Search/Fetch fallback. |
| browser-use | Playwright MCP | UPDATE-01 **U24** 工具表 + **U46** 默认开（惰性进本轮 tools）：`browser_navigate` / `browser_snapshot` / `browser_click`。用户 Chrome：**U46** `chrome_attach`（CDP 9222，默认开）。可 bundled MCP 或用户插件，进 `plugin/list`。Not `webfetch`. Search/Fetch/Browse routing is **U33–U36**；升级梯子 **U46**（CU 可点网页但须任务信号）。调研 = 多次一条 query 的 `websearch`，25s 是单次墙。 |
| plugin host | appserver/plugin_service.py | B18 `plugin/*` wraps skills/MCP into capabilities — no second invoke path; see docs/plans/opus5-plan/rxycode/architecture |
| [lsp](docs/modules/lsp.md) | lsp/ | LSP integration - code intelligence (experimental) |
| [scheduler](docs/modules/scheduler.md) | scheduler/ | Scheduled tasks - cron-like prompt scheduling |
| [frontend](docs/modules/frontend.md) | frontend/opentui-app/ | OpenTUI default TUI (Ink fallback under frontend/; Desktop under frontend/desktop-app/)。`/session` 列表：日期分组 + 右侧相对时间 + `ctrl+r/d/f`（UPDATE-01 U50）；数据源 `sessions/list`。`/effort`：Select effort + Default 首行 + composer 模型旁芯片（UPDATE-01 U52–U56）；命令不是 `/variant`。已发送用户气泡右键 **Message Actions**（Revert/Copy/Fork，UPDATE-01 U57–U62；运行中 overlay 仍开，Revert 先 `session/interrupt`）；Fork 走 `thread/fork` 不是 `session/fork`。隔夜同一窗口 = 同一 `session_id` + memory hydrate（UPDATE-01 U64）；`/loop` 时钟走 `ScheduleService.restore_after_restart`（U66），不是把被杀 bash 复活 |
| [tests](docs/modules/tests.md) | tests/ | Test suite - Playwright API tests, vitest unit tests |
| [api_server](docs/modules/api_server.md) | api_server.py | API server - FastAPI with SSE streaming |
| [main](docs/modules/main.md) | main.py | CLI entry point - argument parsing, TUI/API launch |

## Architecture Overview

RxyCode is an AI coding assistant with a Python backend and TypeScript terminal
frontends. The core is headless: `Session` (`core/session.py`) is the
transport-agnostic facade over `AgentV2`. **OpenTUI**
(`frontend/opentui-app/`) is the default TUI and drives the core over stdio
JSON-RPC via `appserver/` (`python -m appserver`); **Ink** (`frontend/`,
`RXYCODE_TUI=ink`) is the optional fallback, served by `api_server.py`
(HTTP/SSE adapter).

```
+---------------------+           +---------------------+
|OpenTUI / Desktop(P3)|           |   Ink (fallback)    |
|frontend/opentui-app |           | frontend/ (TUI=ink) |
+---------------------+           +---------------------+
           |                                 |
           |  stdio JSON-RPC                 | HTTP + SSE
           v                                 v
Transport
+---------------------+           +---------------------+
|     appserver/      |           |    api_server.py    |
| python -m appserver |           |  HTTP/SSE adapter   |
|watchdog + agent_host|           |   same protocol/    |
|   -> agent_worker   |           |      contract       |
+---------------------+           +---------------------+
           |                                 |
           v                                 v
+-------------------------------------------------------+
|      Session (core/session.py) - headless facade      |
|    over AgentV2; no I/O; emit() -> protocol events    |
+-------------------------------------------------------+
                            |
                            v
+-------------------------------------------------------+
|              AgentV2 (core/agent_v2.py)               |
|     simple query -> _fast_reply() + 2-level cache     |
| complex task -> LangGraph: goal_planner -> decomposer |
|        -> executor -> validator -> synthesizer        |
|  multi-task -> TaskTree parallel leaves / compose     |
|     tools -> ToolOrchestrator / memory (memory/)      |
|  optional expert team (docs/modules/agents.md, off)   |
|     Coordinator + SopMachine + BudgetGuard            |
+-------------------------------------------------------+
                            |
                            v  results -> protocol notifications
+-------------------------------------------------------+
|       appserver: ProtocolTui -> stdout JSON-RPC       |
|           api_server: _emit_protocol -> SSE           |
+-------------------------------------------------------+
```

**Request Flow:**
1. User types in OpenTUI (default), Desktop, or the Ink fallback
2. OpenTUI/Desktop -> `appserver` (`python -m appserver`): typed JSON-RPC over
   stdio (`protocol/` pydantic models; TS types into `frontend/protocol-client`)
3. `appserver` spawns a worker subprocess per session (`agent_host`/
   `agent_worker`) -> `Session.prompt()` in `core/session.py`
4. Session drives AgentV2 (`core/agent_v2.py`):
   - Simple queries -> `_fast_reply()` with 2-level cache
   - Complex tasks -> LangGraph (core/graph.py): goal_planner -> decomposer ->
     executor -> validator -> synthesizer
   - Multi-task -> graph `parallel_requested` (same AgentV2, TaskTree leaves)
   - Compose mode -> Plan + Build
5. Executor uses tools (tools/) via ToolOrchestrator; memory (memory/) injects
   context; safety gates (core/safety/) raise approval/question requests
6. Results stream back as protocol notifications: appserver -> `ProtocolTui`
   -> stdout JSON-RPC; api_server -> `_emit_protocol` -> SSE
   (`notification_to_sse_event`)
7. Ink fallback: `api_server.py` (HTTP/SSE adapter) -> same Session -> same protocol mapping

**Key Design Patterns:**
- UsageTrackingLLM: Wraps all LLM calls to auto-record token usage
- OpenTUI ScrollBox + sticky scroll: flicker-resistant chat (Ink Static reserved for fallback)
- Two-level cache: exact hash + semantic similarity
- Tiered memory: short-term window + long-term compressed
- Watchdog timeout: Monitors execution and cancels on inactivity
- PromptSpec versioning: Versioned prompt templates for cache-key stability
- Task-level context isolation: Dependency-chain filtered context per task
- Parallel execution: asyncio.gather + Semaphore for concurrent task execution

## For AI Agents Working on This Codebase

**Expert crew (auto):** Follow `.agents/skills/using-agent-crew/SKILL.md`. Create or optimize a coding agent. Roles: `spec-author`, `agent-core-boundaries`, `agent-runtime`, `local-agent-process-isolation`, `agent-surface`, `agent-quality` (Eval/Quality — modular tests + overall **evals**, not a Test Engineer title). Implementers run their tests; quality owns the eval-suite gate. Index: `.agents/skills/agent-crew/README.md`.

| Tool | Skills live in | Force invoke |
|------|----------------|--------------|
| Cursor | `.cursor/skills/` | `/using-agent-crew` |
| Codex | `.agents/skills/` | `$using-agent-crew` |
| Grok Build | project `.grok/skills/` + `.agents/skills/` (cwd must be this repo), or user `~/.grok/skills/` for every project. Also `.grok/commands/` | `/using-agent-crew` (type `/` then `using`; new session after install) |
| OpenCode | `.agents/skills/` + `.opencode/commands/using-agent-crew.md` | `/using-agent-crew` |
| Claude Code | `.claude/skills/` + `CLAUDE.md` imports this file | `/using-agent-crew` |

1. **Before modifying a module**: Read its README first
2. **Cross-module changes**: Check the Dependencies section in each README
3. **Frontend changes**: Run npx tsc && npx vitest run in frontend/
4. **Backend changes**: Run the layered pytest suite (entry points in docs/modules/tests.md)
5. **New features**: Add tests in tests/ and update the relevant README
6. **Save location**: Files save to ~/.rxycode/output/ (configurable via RXYCODE_OUTPUT_DIR)
