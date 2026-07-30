# RxyCode Module Documentation Index

> This index is designed for AI agent development. Each module README explains what the module is, how it works, where the core code is, and how it connects to other modules. Agents should read the relevant module README before making changes, instead of scanning all source code.

## Quick Reference

| Module | Location | Purpose |
|--------|----------|---------|
| [core](docs/modules/core.md) | core/ | Agent brain - AgentV2, LangGraph pipeline, prompts, state |
| [config](docs/modules/config.md) | config/ | Configuration management - models, API keys, preferences |
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
frontend. **OpenTUI** (`frontend/opentui-app/`) is the default TUI; Ink
(`frontend/`) remains an optional fallback via `RXYCODE_TUI=ink`.

**Request Flow:**
1. User types in OpenTUI (default) or Ink fallback, or sends HTTP request
2. API server (api_server.py) receives the request
3. AgentV2 (core/agent_v2.py) routes the request:
   - Simple queries -> _fast_reply() with 2-level cache
   - Complex tasks -> LangGraph pipeline (core/graph.py)
   - Multi-task -> Sub-agent delegation
   - Compose mode -> Plan + Build
4. LangGraph pipeline: goal_planner -> decomposer -> executor -> validator -> synthesizer
5. Executor uses tools (tools/) via ToolOrchestrator
6. Memory system (memory/) provides context injection
7. Results flow back through SSE to the frontend

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
4. **Backend changes**: Run the Playwright test suite
5. **New features**: Add tests in tests/ and update the relevant README
6. **Save location**: Files save to ~/.rxycode/output/ (configurable via RXYCODE_OUTPUT_DIR)
