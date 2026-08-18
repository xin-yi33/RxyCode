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
| [rag](docs/modules/rag.md) | rag/ | Codebase vector search - chunking, embedding, cosine search, repo map |
| [tracing](docs/modules/tracing.md) | core/tracing.py | Node-level tracing - span collection, JSONL persistence, replay |
| [utils](docs/modules/utils.md) | utils/ | Shared utilities - TUI, streaming, i18n, shell helpers |
| [history](docs/modules/history.md) | history/ | History tracking - command and conversation logging |
| [mcp](docs/modules/mcp.md) | mcp/ | MCP integration - connect to external MCP servers |
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
|  multi-task -> sub-agents / compose -> Plan + Build   |
|     tools -> ToolOrchestrator / memory (memory/)      |
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
   - Multi-task -> sub-agent delegation
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

1. **Before modifying a module**: Read its README first
2. **Cross-module changes**: Check the Dependencies section in each README
3. **Frontend changes**: Run npx tsc && npx vitest run in frontend/
4. **Backend changes**: Run the layered pytest suite (entry points in docs/modules/tests.md)
5. **New features**: Add tests in tests/ and update the relevant README
6. **Save location**: Files save to ~/.rxycode/output/ (configurable via RXYCODE_OUTPUT_DIR)

## Cursor Cloud specific instructions

The Cloud Agent environment is bootstrapped by `scripts/cloud-agent-install.sh`
(wired as the environment `install` command). It sits on Cursor's default image
(Python 3.12 + Node 22) and adds: `python3-venv`, a `python`→`python3` symlink,
the backend deps + editable install, `uv`, and Bun, then builds/installs the
three frontends (Ink `frontend/`, `frontend/protocol-client`,
`frontend/opentui-app`). The script is idempotent — re-run it any time.

Environment-specific notes:

- **Install Python packages into the system site-packages** (the script uses
  `sudo pip install --break-system-packages`). A user-site (`~/.local`) install
  is NOT loaded by child interpreters, so `pytest-xdist` workers and the
  `python3 -m appserver` process the TS frontends spawn would fail to import
  `RxyCode`.
- **Run the deterministic backend suite by layer** with
  `python scripts/run_phase1_pytest.py` (mirrors CI). The legacy `regression`
  layer has known shared-state/timing sensitivity under `-n 2`; a handful of
  timing tests (e.g. `tests/test_llm_timeout_guard.py`) can flake under parallel
  load but pass when re-run in isolation.
- **`tests/system/test_api_process.py::test_real_api_subprocess_reaches_status_endpoint`**
  computes `project_root.parents[1]` and therefore requires the repo to be
  checked out at least two levels below `/`. It fails at the top-level
  `/workspace` checkout (an `IndexError`, not an app defect); the API server
  itself is fine — launch it with `rxycode --api` (needs `RXYCODE_API_TOKEN`) and
  GET `/status`.
