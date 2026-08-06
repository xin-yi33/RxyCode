# B1 · Baseline Assessment Report

**Date**: 2026-08-06
**Executor**: Composer 2.5
**Status**: Complete

## 1. Legacy Symbol Inventory

### 1.1 `_run_with_subagents` (core/agent_v2.py:2681-2685)

- **Callers**: 0 active callers — raises RuntimeError unconditionally
- **Verdict**: **delete** in B13 migration (already dead code)
- **Test impact**: smoke test `live_smoke_runner.py:1242` references `_should_use_subagents` (not this)

### 1.2 `_should_use_subagents` (core/agent_v2.py:2678-2679 → core/request_routing.py:265-274)

- **Callers**:
  - `core/agent_v2.py:2747` — sets `parallel_requested` flag in compose mode
  - `core/agent_v2.py:3251` — sets `parallel_requested` flag in direct mode
  - `tests/integration/test_agent_main_chain.py:160` — monkeypatched to False in tests
  - `scripts/live_smoke_runner.py:1242` — referenced but path is disabled
- **Behavior**: Chinese/English keyword matching for "parallel/batch/simultaneously"
- **Verdict**: **keep-with-contract** — rename to `_should_parallelize` per Phase C plan; it controls TaskTree leaf parallelism, NOT subagents

### 1.3 `SubAgentV2` (core/agent_v2.py:3414-3422)

- **Callers**: 0 instance creations found (class is defined but never instantiated)
- **Behavior**: Just forwards task to parent `AgentV2.run()` — no isolation
- **Verdict**: **delete** in B13 (replaced by ChildRuntime)

### 1.4 `tools/agent_tool.py` — `run_agent` / `run_agent_async`

- **Tool name**: `agent`
- **Callers**: Referenced in `tools/README.md:81,83` for documentation
- **Behavior**: Creates a fresh `AgentV2()` and calls `.run(prompt, mode="compose")` — same process, no Child Session
- **Verdict**: **adapter** in B13 — wrap with deprecation error pointing to new `task` tool

### 1.5 `tools/task_tool.py` — `manage_tasks` / `manage_tasks_async`

- **Tool name**: `task`
- **Behavior**: Persistent task list management (create/list/get/start/block/unblock/done/abandon/rename) with file-based JSON store
- **Callers**: Registered as `task` tool in tool registry
- **Verdict**: **keep-with-contract** — rename tool to `task_manage`; the `task` name moves to the new subagent dispatch tool

### 1.6 `TaskTree` / `TaskNode` (core/state.py)

- **Callers**: Heavy usage in `core/graph.py`, `execution/scheduler.py`, `planning/`, `validation/`, `synthesis/`, `recovery/`
- **Behavior**: Hierarchical task decomposition for single-agent parallel execution
- **Verdict**: **keep-with-contract** — remains as single-agent parallelism mechanism; explicitly NOT a subagent mechanism

### 1.7 `subagent_decompose` template (core/prompts/templates.py:340)

- **Callers**: 0 production callers found (prompt template is registered but unused)
- **Verdict**: **keep-with-contract** — may be adapted for Phase C expert decomposition; no runtime boundary

### 1.8 `core/graph.py` parallel execution (asyncio.gather + TaskTree leaves)

- **Callers**: Core execution path via `AgentV2.run()`
- **Behavior**: Parallel execution of TaskTree leaf nodes within the SAME agent session
- **Verdict**: **keep-with-contract** — this IS the primary single-agent parallelism mechanism; Phase B does not replace it

### 1.9 UI utilities (utils/streaming.py, utils/i18n.py)

- `print_subagent_start`, `print_subagent_complete`
- i18n keys: `subagent_creating`, `subagent_running`, `subagent_complete`, `subagent_error`
- **Verdict**: **adapter** — redirect to Child Session event rendering in B8

## 2. Actual Call Chain (Current State)

```
User Input
  → AgentV2.run()
    → _should_use_subagents() → parallel_requested flag
    → [single-agent path] OR [compose mode]
    → graph execution with TaskTree leaves via asyncio.gather
         (shared session, shared tools, shared budget, shared memory)

Dead paths (raise or unused):
  _run_with_subagents → RuntimeError
  SubAgentV2 → forwards to parent (0 instantiations)
  tools/agent_tool → fresh AgentV2().run() (called externally only)
```

## 3. Disposition Summary

| Symbol | File | Disposition | B Card |
|--------|------|-------------|--------|
| `_run_with_subagents` | core/agent_v2.py:2681 | **delete** | B13 |
| `_should_use_subagents` | core/agent_v2.py:2678 | **keep** (rename to `_should_parallelize`) | B13 |
| `SubAgentV2` | core/agent_v2.py:3414 | **delete** | B13 |
| `run_agent` / `run_agent_async` | tools/agent_tool.py | **adapter** (deprecation warning) | B13 |
| `manage_tasks` tool `task` | tools/task_tool.py | **keep** (rename to `task_manage`) | B13 |
| `TaskTree` / `TaskNode` | core/state.py | **keep** (single-agent parallelism) | — |
| `subagent_decompose` template | core/prompts/templates.py | **keep** (Phase C adapter) | — |
| graph parallel execution | core/graph.py | **keep** (single-agent path) | — |
| `print_subagent_start/complete` | utils/streaming.py | **adapter** (Child event renderer) | B8 |
| i18n subagent strings | utils/i18n.py | **adapter** | B8 |

## 4. Files to Create (B2–B14)

```
protocol/subagents.py              # AgentDefinition, TaskRequest, TaskResult, events
protocol/subagents_schema.json     # Machine-verifiable schema
core/subagents/__init__.py
core/subagents/definitions.py      # AgentDefinition loading & static validation
core/subagents/config_loader.py    # JSON/Markdown/YAML normalization
core/subagents/sessions.py         # Primary/Child Session lifecycle
core/subagents/runtime.py          # Isolated AgentRuntime → ChildRuntime facade
core/subagents/context.py          # ContextEnvelope construction & redaction
core/subagents/permissions.py      # allow/ask/deny & task permission
core/subagents/workspace.py        # WorkspaceScope & write leases
core/subagents/budget.py           # steps/token/time/concurrency guard
core/subagents/events.py           # ChildSessionEvent & persistence
core/subagents/manager.py          # ChildSessionManager / cancellation tree
tools/subagent_task_tool.py        # Sole subagent dispatch Task Tool entry
appserver/subagent_routes.py       # JSON-RPC methods, notifications, capability
tests/test_subagents/              # 14 test modules
```

## 5. Baseline Regression Gate

- Single-agent path must pass byte-for-byte when subagent feature flag is off
- No second subagent implementation found anywhere in the codebase
- All "subagent" references are either dead code, prompts, or UI strings
- Zero production callers for `_run_with_subagents` or `SubAgentV2`
