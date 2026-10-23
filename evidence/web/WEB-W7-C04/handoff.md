# WEB-W7-C04 handoff — OpenTelemetry/Langfuse tracing + explainable cost board

Audited commit: `8e9886e6c829220b2a72936f424a5ed89b12896a`
Audit: Codex session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, model `gpt-6.1-sol`,
reasoning `high`, 6 rounds → final `VERDICT: NO_REMAINING_PROBLEMS`.

## What shipped

- `packages/rxycode-worker/src/rxycode_worker/telemetry.py` — OTel-convention
  span layer (W3C traceparent, SpanContext/Span/Tracer, recursive sanitization,
  run-scoped `parent_for_run`, exporters). `opentelemetry` SDK intentionally not
  installed; the injected exporter is the swap seam.
- `packages/rxycode-server/src/rxycode_server/metrics.py` — `run_trace_summary`
  + `tenant_cost_metrics`: ledger↔provider↔span reconciliation, multi-row
  ledger aggregation, terminal-boundary elapsed accounting.
- Production wiring (two committed rulings, nested-plan lines ~213-214):
  `runs/service.py create_run` emits the http/server span and persists
  `traceparent` in the `run.created` payload; `supervisor.claim` parents
  `worker.run` on the persisted context and closes it inside the terminal tx
  (SAVEPOINT-isolated export); `RunJournal.record` emits graph.agent/tool
  spans; `appserver/tui.py` `write_tool_call`/`write_tool_result` emit/close
  the same tool spans on the real notification path. All best-effort.
- `apps/web/src/features/usage/UsagePage.tsx` — per-run trace details with the
  same in-window elapsed math and abnormal-cost badge.
- Spans persist as `telemetry.span` rows in `run_events` (tenant-scoped,
  durable, replayable; foreign tenant → RUN_NOT_FOUND).

## Evidence

`red.txt`, `green.txt` (r1–r5 sections), `trace_dump.json`,
`metrics_dump.json`, `dashboard.png` (matplotlib, real collected data),
`bottleneck.md`, `NOTES.md`, `collect_evidence.py`, `_workdir/` journals.

## Status

- Focused tests 16 passed; full `tests/web/w7` 41 passed (single invocation,
  shared PG); ruff clean; `npm run typecheck` clean; `git diff --check` clean.
- Browser E2E: BLOCKED (no Playwright dep in apps/web) — labeled, not claimed.
- CLI/Desktop regressions unaffected: w6_c04 + w2_c07 + cache-split re-run
  green; C03 test files byte-identical at audit time.
