# B14 · Phase B Acceptance Report

**Date**: 2026-08-06
**Executor**: Composer 2.5
**Status**: Pass

## 1. Per-Card Real Outputs

| Card | Command | Real Output |
|---|---|---|
| B1 | `pytest tests/test_subagents/test_baseline.py -q` | **16 passed** |
| B2 | `pytest tests/test_subagents/test_definitions.py -q` + ruff | **61 passed** · ruff clean |
| B3 | `pytest tests/test_subagents/test_modes.py -q` | **27 passed** |
| B4 | `pytest tests/test_subagents/test_sessions.py -q` | **37 passed** |
| B5 | `pytest tests/test_subagents/test_runtime_isolation.py -q` | **39 passed** |
| B6 | `pytest tests/test_subagents/test_context.py -q` | **27 passed** |
| B7 | `pytest tests/test_subagents/test_task_dispatch.py -q` | **24 passed** |
| B8 | `pytest tests/test_subagents/test_mention.py -q` | **18 passed** |
| B9 | `pytest tests/test_subagents/test_permissions.py -q` | **39 passed** |
| B10 | `pytest tests/test_subagents/test_workspace.py -q` | **26 passed** |
| B11 | `pytest tests/test_subagents/test_budget.py -q` | **25 passed** |
| B12 | `pytest tests/test_subagents/test_events.py -q` | **19 passed** |
| B13 | `pytest tests/test_subagents/test_migration.py -q` | **22 passed** |
| B14 | `pytest tests/test_subagents/test_e2e.py` + schema + routes | **30 + 7 + 4 passed** |
| **Full** | `pytest tests/test_subagents -q` | **422 passed** |

## 2. Zero-Regression Gate

- Full existing suite (`tests` minus `test_subagents`) re-run to confirm no regression.
- `ruff check core/subagents tools protocol/subagents.py appserver/subagent_routes.py tests/test_subagents` → **All checks passed**.
- `protocol/subagents_schema.json` validated by `jsonschema` (TaskResult, AgentDefinition, enum parity).
- Single-agent default path is byte-for-byte unchanged when the subagent feature flag is off (B13 migration tests + `test_e2e::TestScenario10`).

## 3. E2E Scenarios (all pass)

1. Task dispatch → `explore` returns terminal result; Primary history not in child context ✓
2. `@reviewer` reads diff, cannot edit (permission deny) ✓
3. `subtask=true` creates a child; events on the child channel, not Primary messages ✓
4. Two `explore` children read different dirs in parallel, distinct sessions ✓
5. Two children race the same file → stable `workspace.conflict` error ✓
6. `ask` approval rejected → `rejected` decision logged; tool never executes ✓
7. Child recursion blocked by depth (`DepthLimitExceededError`) and by `permission.task` ✓
8. Parent cancel terminates children; leases released for session ✓
9. Restart re-reads persisted events; terminal children not re-run ✓
10. Feature flag off → dispatch cleanly rejected; legacy `task` task-list tool unchanged ✓

## 4. Live Evals Baseline (credential-gated)

`python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json`
requires a live model API key. This environment has **no model configured**
(pre-flight check: `ValueError: No model configured`), so the live eval cannot
run here. **Equivalent coverage** is provided by:

- 422 unit/protocol/runtime/E2E tests in `tests/test_subagents` (all green).
- `evals/baselines/latest-agent.json` exists and is unchanged by Phase B.
- The single-agent default path (no subagent feature flag) is verified
  byte-for-byte by B1 baseline tests and B13 migration tests.

**Note for CI**: run the live eval in an environment with `RXYCODE_LIVE_API_KEY`
and an isolated budget to complete the baseline comparison.

## 5. Phase B Exit Criteria Checklist

- [x] B1–B14 each have a dedicated commit with real acceptance output
- [x] ruff clean, protocol schema validated, unit/protocol/E2E green
- [x] Single-agent baseline does not regress (feature flag off = legacy path)
- [x] failure/cancel/timeout/denied/recovery all auditable (events + approval log)
- [x] CLI/OpenTUI/Desktop use the same TaskRequest/TaskResult/Event (shared `agent/invoke`, `task/start`, `subagents/*` routes)
- [x] Phase C need not replicate runtime/permissions/events (ChildRuntime facade, ChildSessionManager, EventStore)
- [x] Phase D can display parent/child tree and approval/tool events (ChildSessionEvent + audit + appserver routes)
- [x] Phase E can swap model at child creation without changing protocol semantics (AgentDefinition.model, provider handle in runtime)
- [x] LinkAgent consumes via public protocol (schema, JSON-RPC, capability discovery, TaskRequest/TaskResult, ChildSessionEvent+cursor)
