# WEB-W7-C04 — OpenTelemetry/Langfuse-compatible tracing + explainable cost board

## What was built

| file | lines | role |
|---|---|---|
| `packages/rxycode-worker/src/rxycode_worker/telemetry.py` | 576 | OTel-convention span layer: W3C `traceparent`, SpanContext/Span/Tracer, sanitization, exporters |
| `packages/rxycode-server/src/rxycode_server/metrics.py` | 290 | `run_trace_summary` + `tenant_cost_metrics` — ledger↔provider↔span reconciliation |
| `apps/web/src/features/usage/UsagePage.tsx` | 212 | extended: per-run trace `<details>` (SSE replay → span stats), abnormal-cost badge, `data-trace`/`data-abnormal` in `usageMarkup` |
| `tests/web/w7/test_w7_c04_unit.py` | 641 | contract + negative (secret redaction) + `traceparent` propagation |
| `tests/web/w7/test_w7_c04_module.py` | 308 | integration: two real spine runs, ledger↔provider alignment, abnormal surfaced |
| `evidence/web/WEB-W7-C04/collect_evidence.py` | 395 | real evidence collector (trace dump, metrics dump, dashboard.png, bottleneck.md) |

## Span-store decision

Spans are journaled as `telemetry.span` rows in **`run_events`**
(`RunEventsSpanExporter` → `append_event`). Rationale: tenant-scoped rows,
durable transactional writes (event + outbox in one tx), replayable via
`events.store.replay`, and the existing `/api/v1/runs/{run_id}/events`
endpoint already enforces ownership (`RUN_NOT_FOUND` → 404 for a foreign
tenant — proven in the contract test). No new table, no Alembic migration.
`trace_id` is queryable by `run_id` via `metrics.run_trace_summary`.

## Propagation mechanism

W3C `traceparent` (`00-{32-hex trace_id}-{16-hex span_id}-{flags}`):
`inject_env` publishes `RXYCODE_TRACEPARENT` into the environment — the same
channel the worker already uses to inherit `RXYCODE_WEB_DATABASE_URL` —
`extract_env` reads it back as the remote parent. In-process parenting uses
either an explicit `SpanContext` or the `use_span` ContextVar. Malformed
headers parse to `None`, never a guess.

## OTel/Langfuse seam

`opentelemetry` is not installed (verified) and was not added. `Tracer`
takes a constructor-injected exporter — any object with `export(dict)` —
so a real OTLP/HTTP exporter or OTel SDK drops in with zero call-site
changes. `OTEL_KIND` maps our kinds onto `SERVER/CLIENT/INTERNAL/PRODUCER`.

## Trace-summary API surface

* `metrics.run_trace_summary(database_url, tenant_id=…, run_id=…)` — one
  run's trace_id, correlated spans, per-layer counts/durations, ledger row,
  provider `event/agent_done` snapshot, cache stats, cost + abnormal flag.
  Foreign tenant → `{"code": "RUN_NOT_FOUND", "spans": []}`.
* `metrics.tenant_cost_metrics(database_url, tenant_id)` — per-run
  ledger↔provider reconciliation lines, totals, `abnormal` list (verbatim,
  still counted in totals), `mismatches`.
* HTTP surface: existing `/api/v1/runs/{run_id}/events` (owner-scoped SSE
  replay) + `/api/v1/usage`. No new route — the whitelist has no router
  file, and these endpoints already enforce tenant ownership. The client
  `traceSummary` in UsagePage builds the same summary from the SSE replay.

## Secret safety

`sanitize_attrs` drops secret-shaped keys entirely (`prompt`, `password`,
`api_key`, `*key*`, `*token*`, `*secret*`, `*authorization*`, `*cookie*`,
`*_key`), recording only `<key>_len` + `<key>_sha256` for correlation.
Every stored string passes `log.log_helpers.redact_sensitive` (inlined
fallback keeps the same 5 patterns if the core package is unreachable) and
is truncated at 200 chars. The negative test stores a real `sk-…`/`password=`
stderr and asserts the raw secret never lands in the payload — only
`[REDACTED]` forms survive.

## Red → green

* `red.txt` — 4/4 import errors (`rxycode_worker.telemetry`,
  `rxycode_server.metrics` missing) before implementation.
* `green.txt` — focused 4/4; full `tests/web/w7` 29/29; regressions
  w6_c04+w2_c07+s1_s2 9/9; ruff clean; `npm run typecheck` clean;
  `git diff --check` clean on the touched file (all files LF, no trailing ws).

## Evidence artifacts

* `trace_dump.json` — real trace `cc83ac208e6946e89dfe45d29b9883ce`,
  3 correlated spans (server→worker→tool), ledger $19.75308600 aligned
  with the provider snapshot, abnormal run listed.
* `metrics_dump.json` — both runs' summaries + `tenant_cost_metrics`.
* `dashboard.png` — rendered by matplotlib from that real data (billed
  amount per run with the $1 abnormal line, per-layer span durations,
  ledger-vs-provider tokens).
* `bottleneck.md` — per-layer timing for the collected runs + comparison
  vs `WEB-W7-C03/results_web-solo.json`.
* `collect_evidence.py` — the collector; `_workdir/` keeps the tool
  journals and workdirs it used.

## Verification notes / deviations

* `tests/web/w6/test_w6_c04_module.py` fails under this Windows GBK locale
  without `PYTHONUTF8=1`: its `_render_legacy` subprocess reader decodes
  bun's UTF-8 output (`子代理`) as GBK → `UnicodeDecodeError` →
  `stdout=None` → `TypeError`. Pre-existing environmental flake in the
  test's own harness — `AgentTree.tsx` is untouched by this card and the
  manual bun render produces the expected markup. With `PYTHONUTF8=1` it
  passes.
* The same file also assumes the shared container already has the web
  schema (it never migrates). The w7 `postgres_url` fixture drops the
  schema per test, so the regression must run while the schema is migrated
  (restored via `upgrade_head` — documented in `green.txt`).
* `tests/test_cache/test_s1_s2_split.py` passed (9/9 regression batch);
  `test_stable_prefix.py` skipped — no `core/` path was touched.
* No `opentelemetry` dependency added; no new HTTP route added (see
  API-surface decision); no staged/committed files; the dirty worktree's
  unrelated changes were left alone.
* Shared container `rxy-w2c01-pg` was reused, never recreated or removed;
  no leaked processes (all runtimes are `asyncio.run`-scoped in tests).
