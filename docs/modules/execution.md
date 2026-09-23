# execution/ - Task Execution

## What Is This Module?
Handles the execution of individual subtasks within the LangGraph pipeline. Manages tool orchestration, LLM interactions, and execution monitoring.

## Key Files
| File | Purpose |
|------|---------|
| executor.py | Executor - runs individual subtasks with tool-calling loop |
| tool_orchestrator.py | ToolOrchestrator - manages tool execution and result formatting |
| tool_journal.py | Crash-safe pending/completed journal for WRITE/DANGER calls |
| evidence.py | `ToolEvidence` / `ArtifactEvidence` / `build_tool_evidence` / `deterministic_issues` - deterministic tool-boundary evidence contract |
| scheduler.py | Deterministic DAG scheduler (`get_ready_tasks`/`get_parallel_groups`/`build_dag`). **Cron scheduling lives in `scheduler/`** (see [scheduler.md](scheduler.md)) |

## Core Code: executor.py (Executor)

**Execution Loop:**
1. Build prompt from task description + context
2. Call LLM with bound tools
3. If LLM returns tool calls, execute them via ToolOrchestrator
4. Feed tool results back to LLM
5. Repeat until LLM produces a final text response
6. Return the final response

(The old `max_iterations=12` constructor argument was removed — it was a
dead parameter that `create_react_agent` never accepted. Iteration bounds
are expressed at the graph layer via LangGraph's `recursion_limit`.)

**Key Methods:**
- execute(task, task_context) -> str: Main execution loop
- Handles tool_call -> tool_result -> LLM -> tool_call cycles
- Includes progress tracking and error handling

**2026-09-23 思维链导出：** `execute_with_evidence` 走非流式 `agent.ainvoke`，
结果消息里的模型推理（DeepSeek/Qwen/Kimi `additional_kwargs.reasoning_content`、
Anthropic 风格 thinking content blocks）曾在此边界被丢弃——graph/团队轮次 TUI
无 Thought（用户报告：thought 不是没有而是无法导出）。现在
`_extract_thinking_from_messages` 提取后经 `event_tui.write_reasoning` 导出到
会话 TUI（纯观察性，失败不影响任务；探针 `executor.thinking.exported`）。
测试：`tests/test_execution/test_executor_thinking_export.py`。

## Core Code: tool_orchestrator.py (ToolOrchestrator)

**Responsibilities:**
- Maintains a registry of available tools
- Executes tool calls by name with structured arguments
- Formats tool results for LLM consumption
- Handles tool errors gracefully (timeout, crash, invalid args)

**Key Methods:**
- register(name, tool, *, risk=None): Add a tool to the registry with an optional risk override
- execute_tool(name, args, config) -> str: Execute a tool by name **through
  the safety gate** (阶段二): policy classification -> write-path whitelist
  -> dry-run -> approval -> execute -> audit. READ-level tools skip
  approval; WRITE/DANGER need approval unless the level is in
  `safety.auto_approve` or was always-allowed this session. Every decision
  is appended to `~/.RxyCode/logs/audit.jsonl`. See
  [docs/modules/safety.md](safety.md).
  Path-bearing write arguments include `save_path`, so custom download
  destinations are checked against the same writable-root policy.
  The same-run identical-call dedup (`_live_tool_dedup`) suppresses duplicate
  tool calls within one run.
- get_all() -> dict / list_names() -> list: Return all registered tools for
  LLM binding (there is no `get_tools()`)
- select_tools(hints) -> list: Select tools by hint. On hint mismatch,
  returns only the read-only core subset (READONLY_TOOL_NAMES:
  read/view/grep/glob/ls/datetime/websearch/webfetch — adapted from Claude
  Code's read-only whitelist concept) instead of every tool, so a bad hint
  never silently grants write/execute capabilities.

`ToolOrchestrator.execute_tool()` applies the optional shared tool deadline from
`execution.tool_timeout_seconds`. The default is `1800` seconds and wraps only
the real tool invocation. Fast-path and LangGraph proxy calls therefore share
timeout, cancellation, evidence, audit, and event semantics; external
`CancelledError` always propagates. The default
`task_stall_timeout_seconds=0` disables the former fixed 600-second silent-task
kill, while `task_max_time_seconds=7200` remains the independent total task
ceiling. Setting a positive deadline to `0` explicitly disables only that
deadline layer.

MCP tools are dynamic but do not bypass this entry point. `AgentV2` registers
their `StructuredTool` adapters in the orchestrator, and the executor only sees
the usual safe proxies. Because MCP annotations are untrusted and their names
are not in the built-in policy table, they default to `WRITE` risk and retain
approval, audit, timeout, evidence, cancellation, and side-effect journaling.
A positive `destructiveHint` is carried into the orchestrator as a local
minimum `DANGER` risk; `readOnlyHint` is never allowed to lower the default.

### Crash-safe side-effect journal

Every top-level request receives a unique `attempt_id`. It is persisted in the
stable checkpoint document before request execution and reused only while that
checkpoint is unfinished. After policy checks and approval, every WRITE/DANGER
call is atomically recorded as `pending` before the real invocation. A verified
successful result is cleaned, bounded, and atomically changed to `completed`.
READ calls never use the journal. The checkpoint is marked complete only when
the journal has no pending entries, even if the model answer succeeded: a
failed bash probe otherwise leaves the attempt unsealed, and completing the
checkpoint would rotate `attempt_id` on the next identical prompt so the
orphan guard blocks later writes (`journal_unavailable`).

On checkpoint resume, a completed call with the same tool, argument digest, and
occurrence ordinal returns the stored result without invoking the tool again. A
pending call means the previous external outcome is unknowable and is blocked;
it is never retried automatically. Pending calls also block later ordinals for
the same tool and arguments, so a ReAct retry cannot bypass the tombstone.
Journal files store argument hashes rather than plaintext arguments, quarantine
corrupt files, and retain unresolved attempts. Active checkpoints are likewise
never evicted by retention because they are the durable roots for journal
attempt identities.

This is an at-most-once replay guarantee, not distributed exactly-once. The
LangGraph StructuredTool proxy does not expose a stable model `tool_call_id`, so
the stable identity is tool + argument digest + identical-call ordinal. If a
replanned request materially changes the tool or arguments, it is treated as a
new logical operation.

## Core Code: scheduler.py (execution/scheduler.py)

**Purpose:** Deterministic DAG task scheduler used by the parallel executor — no
LLM, no cron. It exposes `get_ready_tasks()` / `get_parallel_groups()` /
`build_dag()` to fan out independent subtasks.

Cron-style scheduled prompts live in `scheduler/` (`scheduler/manager.py`
`ScheduledTaskManager`, `scheduler/cron.py` `CronExpression`) and are described
in [scheduler.md](scheduler.md).

## Core Code: executor.py evidence round budget

Each task's ReAct loop runs under `execution.max_tool_rounds` (default 10),
enforced by `_ToolRoundLimitMiddleware` (executor.py:50-98, 128-173). Tool
results are normalized through `build_tool_evidence()` so the validator and
final-output grounding checks share the same deterministic evidence contract.
