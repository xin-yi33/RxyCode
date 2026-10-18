# WEB-W7-C04 self-audit / manual review

Audited commit: `8e9886e6c829220b2a72936f424a5ed89b12896a`
Final verdict: `VERDICT: NO_REMAINING_PROBLEMS` (round 6, `gpt-6.1-sol` `high`,
session `01a140a7-2cc1-7f61-bdab-2af627f08e80`).

## Audit history

| round | verdict | findings fixed |
|---|---|---|
| r1 | PROBLEMS | 6: no production callers; nested/system_prompt/ghp_ sanitize gaps; single-ledger-row read; traceparent version/flags/ambient-parent; summed-duration double-count; evidence honesty (Decimal F401, bottleneck numbers, BLOCKED label) |
| r2 | PROBLEMS | 6: process-global env traceparent → persisted in `run.created`; savepoint tx-abort; tool spans missing from real TUI path; top-level identifier sanitize; elapsed envelope vs root duration; tool error status mapping |
| r3 | PROBLEMS | 4: committed tui.py swept in uncommitted claim_* helpers (repaired via plumbing — committed blob = pre-card + 2 hooks, WIP preserved); savepoint RELEASE-on-aborted-tx → propagate out of begin_nested; cross-path tool-span dedup; parent-lookup tri-state (env fallback only for proven-legacy runs) |
| r4 | PROBLEMS | 3: terminal sweep of orphaned agent/tool spans; ContextVar agent-scoped tool parenting; terminal-boundary elapsed so idempotent retries can't mutate duration |
| r5 | PROBLEMS | 2: UsagePage mirror lacked the boundary math; boundary filtered start-only — overlapping retry now requires fully-in-window |
| r6 | **NO_REMAINING_PROBLEMS** | — |

## Scope rulings committed to the nested plan

1. r1 wiring (nested `70fe016`): minimal span emission inside
   `runs/service.py create_run`, `supervisor.py` lease entry,
   `agent_events.py RunJournal.record`.
2. r2/r3 (nested `ddc6ed4`): run-scoped traceparent via `run.created` payload,
   SAVEPOINT isolation in terminal tx, `appserver/tui.py` two hook lines only.

## Known limitations (accepted, documented)

- TUI-path tool span opened in the *spawner's* context after spawning still
  binds the last-bound agent — no appserver edits allowed beyond the two
  hooks; journaled path is agent-id-correct.
- Runs without a `worker.run` span (never claimed, e.g. direct `complete_run`)
  have no terminal boundary → legacy envelope semantics; documented.
- Browser E2E BLOCKED: no Playwright dependency in `apps/web`; UsagePage
  covered by contract assertions + typecheck — not claimed as E2E.
- `opentelemetry`/`langfuse` SDK not installed: OTel/W3C-convention layer with
  a constructor-injected exporter seam; a real OTLP exporter drops in with
  zero call-site changes.
- `w6_c04` module test has a pre-existing GBK-locale flake unrelated to this
  card (passes under `PYTHONUTF8=1` and after schema restore).
- PG-backed suites were verified on the implementation side (41 passed, single
  invocation); the read-only auditor inspected code/assertions rather than
  re-running them.
