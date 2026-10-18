# WEB-W7-C02 handoff — 崩溃混沌、断线恢复、负载和资源释放

## Scope verified

| Surface | Behavior exercised |
|---|---|
| `platform_tests/web/chaos/run_recovery.py` | 7 real chaos scenarios against Postgres + Redis + real worker subprocesses; writes `chaos-report.json` |
| `tests/web/w7/test_w7_c02_unit.py` | `test_w7_c02_contract` (approval survives worker kill; exactly one execution after approve, none before), `test_w7_c02_negative` (kill after side effect → `journal_state=unknown` + `recovery_required`, exactly one write, no leaked shell), `test_w7_c02_background_survives_command_reaped_on_crash`, `test_w7_c02_suspended_newborn_reaped_on_crash`, `test_w7_c02_reaping_handle_published_last` |
| `tests/web/w7/test_w7_c02_module.py` | `test_w7_c02_integration`: real uvicorn SSE on ephemeral port, httpx stream aborted mid-run, Last-Event-ID resume; every seq exactly once, terminal state preserved, no tenant-B frames |
| `tests/web/integration/test_chaos_suite.py` | runs the chaos CLI and asserts the report shape |
| `core/sandbox/manager.py` | `reaping_job_handle()` + `reaping_is_inherited()` — process-lifetime reaping-only Job (kill-on-close, no limits, NOT a permission boundary); worker self-assigns so children inherit membership atomically at CreateProcess; handle published last after init; failures warn-once + cached |
| `utils/shell.py` / `native_backend.py` | os_sandbox-off Windows path binds children to the reaping Job; suspended+bind+resume remains only as fallback when self-assignment failed |
| `execution/tool_orchestrator.py` | full local bash goes through `shell_executor.build_argv(command)` — same argv as the normal path |

## Audit findings fixed (3 rounds)

- R1 P1: create->bind->resume kill window leaked suspended children → worker self-assignment makes Job membership inherited atomically at CreateProcess; fallback kept for self-assign failure.
- R1 P2: Redis duplicate assertion compared totals, not per-event provenance → per-event bound `1 <= count <= max(1, attempts)` using the outbox row's attempts; comments corrected to at-least-once.
- R1 P2: SSE test used iter_frames callback + TestClient → real uvicorn socket + httpx stream, abort mid-run, Last-Event-ID resume.
- R1 P2: PG outage could pass without calls failing during the pause → READY/GO-file barrier; calls asserted to fail (OperationalError / lease_rejected) inside the pause; connect_timeout=3 merged into the URL.
- R2 P1: `_reaping_handle` was published before self-assignment finished — a concurrent caller could take the suspended-bind fallback → handle is now published LAST inside `_reaping_lock`; regression test `test_w7_c02_reaping_handle_published_last`.
- R2 P2: SSE cursor advanced on a half-read `id:` line → `_sse_events()` commits frames only at blank-line terminators; cursor = last completed event id; payload seq set must equal `1..final` exactly once.
- R2 P2: `?connect_timeout=3` appended unconditionally corrupted URLs already carrying a query → `urllib.parse` merge (`&` when query exists).

## Results

- red.txt / green.txt in this directory; chaos-report.json: `{'correct': 6, 'unknown': 1, 'failed': 0, 'blocked': 0}`, `process_leak: 0`, `cross_tenant_leak: False`. `worker_kill_after_side_effect: unknown` is the designed verdict (side effect unconfirmable after ACK loss).
- Regressions re-run: w2_c03/c04/c05/c06, w4_c01/c04/c06, w6_c06, shell/sandbox set (195), cache (30 passed, 2 skipped). PG-dependent batches run sequentially — the w2 conftest docker-run/drop-schema fixtures race under parallel pytest processes (harness limitation, documented).
- Ruff clean on all changed files; `git diff --check` clean.

## Frozen rulings honored

- Redis stream is AT-LEAST-ONCE (timed-out XADD may land after unpause); exactly-once to clients is by PG seq. queue.py unchanged.
- Reaping Job is resource cleanup, not permission isolation; `attach_sandbox` still rejects with SANDBOX_FORBIDDEN.
- Checkpoint does not revive external OS state; unknown tool calls never retried; browser reconnect does not restart the worker.

## Risk acceptance / open items

- Windows kernel WRITE isolation for normal mode is a separate card (ruling f011d1cc, items B+C after W7-C02..C06); the reaping Job deliberately does NOT restrict permissions.
- The race-window test kills the worker at a fixed point; with inheritance the window is gone by construction — the test asserts the property, it cannot re-create the eliminated window.

## Audit verdict

- gpt-6.1-sol, reasoning effort high, Codex session 01a140a7-2cc1-7f61-bdab-2af627f08e80 (same session as all prior audits), audited parent commit ebe2bc768104622306fc6ad721aac8e3505ce8cb and returned VERDICT: NO_REMAINING_PROBLEMS (w7c02-audit-3.json).
- Rounds 1-2 returned PROBLEMS; each finding was fixed in commits f3cbb4e3 and ebe2bc76 on feat/rxycode-web.
- Postgres-backed suites were run by the implementer; the auditor judged them from code and assertions (read-only audit env).