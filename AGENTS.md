# RxyCode Module Documentation Index

> This index is designed for AI agent development. Each module README explains what the module is, how it works, where the core code is, and how it connects to other modules. Agents should read the relevant module README before making changes, instead of scanning all source code.

## Quick Reference

| Module | Location | Purpose |
|--------|----------|---------|
| [core](docs/modules/core.md) | core/ | Agent brain - AgentV2, LangGraph pipeline, prompts, state |
| core Phase-Fix files | core/turn_router.py, prefix_profile.py, prewarm.py, turn_context.py, handoff.py, catalog.py | Routing/prewarm/keep-alive decision tables and reserved seams — read core.md Phase Fix invariants before touching agent_v2 |
| [protocol](docs/modules/protocol.md) | protocol/ | Typed JSON-RPC protocol - pydantic models, JSON Schema, TS codegen |
| [appserver](docs/modules/appserver.md) | appserver/ | Stdio JSON-RPC server - headless core transport for OpenTUI/Desktop |
| [config](docs/modules/config.md) | config/ | Configuration management - models, API keys, preferences |
| [providers](docs/modules/providers.md) | core/providers/ | Provider strategy layer - capabilities, matches, resolution |
| [cache](docs/modules/cache.md) | cache/ | Two-level caching - precise hash + semantic similarity |
| [memory](docs/modules/memory.md) | memory/ | Tiered memory - short-term, long-term, user memory, chat storage |
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
| [history](docs/modules/history.md) | history/ | History tracking - command and conversation logging |
| [mcp](docs/modules/mcp.md) | mcp/ | MCP integration - connect to external MCP servers |
| [plugins](docs/modules/plugins.md) | plugins/ + appserver/plugin_service.py | Plugin store: catalog, OAuth connect (GitHub/Canva), zip/registry, computer-use adapter — never `core.graph` |
| [log](docs/modules/log.md) | log/ | Structured process logs with secret redaction |
| [game](docs/modules/game.md) | game/ | Demo terminal game; not part of the agent loop |
| [lsp](docs/modules/lsp.md) | lsp/ | LSP integration - code intelligence (experimental) |
| [scheduler](docs/modules/scheduler.md) | scheduler/ | Scheduled tasks - cron-like prompt scheduling |
| [frontend](docs/modules/frontend.md) | frontend/opentui-app/ | OpenTUI default TUI (Ink fallback under frontend/) |
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

1. **Before modifying a module**: Read `docs/modules/catalog.yaml` and the module README first
2. **Cross-module changes**: Check inbound/outbound dependencies in the catalog; follow `docs/DEVELOPMENT-ORDER.md` (plugin OAuth waits for the adapter contract)
3. **New plugins/connectors**: Register in `plugins/catalog.json` + `plugins/<name>/`. Do not edit `core/graph.py`
4. **Frontend changes**: Run npx tsc && npx vitest run in frontend/; Desktop plugin hub tests in `frontend/desktop-app`
5. **Backend changes**: Run the layered pytest suite (entry points in docs/modules/tests.md)
6. **New features**: Add tests in tests/ and update the catalog entry
7. **Save location**: Files save to ~/.rxycode/output/ (configurable via RXYCODE_OUTPUT_DIR)
