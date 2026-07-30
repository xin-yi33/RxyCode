# execution/ - Task Execution

## What Is This Module?
Handles the execution of individual subtasks within the LangGraph pipeline. Manages tool orchestration, LLM interactions, and execution monitoring.

## Key Files
| File | Purpose |
|------|---------|
| executor.py | Executor - runs individual subtasks with tool-calling loop |
| tool_orchestrator.py | ToolOrchestrator - manages tool execution and result formatting |
| tool_journal.py | Crash-safe pending/completed journal for WRITE/DANGER calls |
| scheduler.py | TaskScheduler - cron-like scheduled task execution |

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

## Core Code: tool_orchestrator.py (ToolOrchestrator)

**Responsibilities:**
- Maintains a registry of available tools
- Executes tool calls by name with structured arguments
- Formats tool results for LLM consumption
- Handles tool errors gracefully (timeout, crash, invalid args)

**Key Methods:**
- register(tool): Add a tool to the registry
- execute_tool(name, args, config) -> str: Execute a tool by name **through
  the safety gate** (阶段二): policy classification -> write-path whitelist
  -> dry-run -> approval -> execute -> audit. READ-level tools skip
  approval; WRITE/DANGER need approval unless the level is in
  `safety.auto_approve` or was always-allowed this session. Every decision
  is appended to `~/.rxycode/logs/audit.jsonl`. See
  [docs/modules/safety.md](safety.md).
  Path-bearing write arguments include `save_path`, so custom download
  destinations are checked against the same writable-root policy.
- get_tools() -> list: Return all registered tools for LLM binding
- select_tools(hints) -> list: Select tools by hint. On hint mismatch,
  returns only the read-only core subset (READONLY_TOOL_NAMES:
  read/view/grep/glob/ls — adapted from Claude Code's read-only whitelist
  concept) instead of every tool, so a bad hint never silently grants
  write/execute capabilities.

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
READ calls never use the journal.

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

## Core Code: scheduler.py (TaskScheduler)

**Purpose:** Runs prompts on a cron schedule.

**Key Methods:**
- add_task(cron_expr, prompt) -> Task: Add a scheduled task
- list_tasks() -> list: List all tasks
- remove_task(id) -> bool: Remove a task
- enable_task(id) / disable_task(id): Toggle task
- start(): Start the scheduler loop
- Storage: ~/.rxycode/scheduler_tasks.json
