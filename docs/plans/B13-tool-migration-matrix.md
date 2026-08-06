# B13 · Tool Migration Matrix

**Date**: 2026-08-06
**Executor**: Composer 2.5

## 1. Tool Name Freeze

The isolated-subagent dispatch tool's ONLY model tool name is **`task`**.
The task-list tool's public name migrates to **`task_manage`**. Exactly one
tool may own the `task` name at any time.

| Mode | `task` tool | `task_manage` tool | Subagent dispatch |
|------|-------------|-------------------|-------------------|
| Legacy (subagents OFF, default) | task-list `task_tool` (from `tools/task_tool.py`) | not registered | not registered |
| New (subagents ON) | subagent dispatch `subagent_task_tool` | task-list `task_manage_tool` | active |

## 2. Migration Matrix

| Entry | File | Old name | New name | Disposition |
|-------|------|----------|----------|-------------|
| Subagent dispatch | `tools/subagent_task_tool.py` | — (new) | `task` | Created in B7; sole dispatch entry |
| Task list | `tools/task_tool.py` | `task` | `task_manage` | Module kept (task persistence + lock); `task_manage_tool` in `tools/task_manage.py` registers under new name |
| Legacy agent | `tools/agent_tool.py` | `agent` | — | Deprecated: raises when subagents enabled, directing to `task`/`@agent` |
| SubAgentV2 | `core/agent_v2.py:3414` | — | — | Deleted (0 instantiations, B1) |
| `_run_with_subagents` | `core/agent_v2.py:2681` | — | — | Dead path (raises RuntimeError); kept as marker, not used |
| `_should_use_subagents` | `core/agent_v2.py:2678` | — | `_should_parallelize` | Kept; controls TaskTree leaf parallelism (NOT subagents) |

## 3. Registration Rule (core/builtin_tool_registration.py)

`register_builtin_tools(..., subagents_enabled=...)`:

- **Legacy** (`subagents_enabled=False`): registers `task_tool` (task-list, name
  `task`); the subagent dispatch tool is NOT registered. Single-agent baseline
  is byte-for-byte unchanged.
- **New** (`subagents_enabled=True`): registers `task_manage_tool` (name
  `task_manage`) in place of the legacy task-list, and registers
  `subagent_task_tool` (name `task`). No duplicate `task` registration.

## 4. Feature Flag / Rollback

- Master flag: `SubagentFeatureFlags.subagents_enabled` (default **False**).
- Rollback: disabling the flag returns to the legacy `task` task-list tool;
  no new tool registrations happen; `agent_tool` legacy path works again.

## 5. Compatibility Errors

- Calling legacy `agent` tool with subagents enabled →
  `RuntimeError(LEGACY_SUBAGENT_DEPRECATED_MSG)` (test-protected).
- Calling the subagent dispatch `task` tool without `init_manager` →
  `RuntimeError("ChildSessionManager not initialized")`.

## 6. Built-in Agents (config/agents/)

| Agent | File | Purpose | Permission |
|-------|------|---------|------------|
| `explore` | `explore.json` | read-only code exploration | read allow; edit deny; bash `pytest *` allow; task deny |
| `general` | `general.json` | generic subtask | read allow; edit ask; bash ask; task deny |
| `reviewer` | `reviewer.md` | diff/test review | read allow; edit deny; bash ask; task deny |
| `scout` | `scout.yaml` | external doc retrieval | webfetch/websearch allow; edit deny; workspace edit deny |

All built-ins are `mode: subagent`, `workspace_scope: read_only` (general uses
`leased_write`), and load through the same `AgentDefinitionRegistry` as user
definitions — no per-format default permission divergence.
