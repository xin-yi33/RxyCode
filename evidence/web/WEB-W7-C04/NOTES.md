# WEB-W7-C04 — OpenTelemetry/Langfuse-compatible tracing + explainable cost board

## What was built

| file | lines | role |
|---|---|---|
| `packages/rxycode-worker/src/rxycode_worker/telemetry.py` | 637 | OTel-convention span layer: W3C `traceparent`, SpanContext/Span/Tracer, recursive sanitization, exporters |
| `packages/rxycode-server/src/rxycode_server/metrics.py` | 343 | `run_trace_summary` + `tenant_cost_metrics` — ledger↔provider↔span reconciliation, per-run multi-row aggregation |
| `packages/rxycode-server/src/rxycode_server/runs/service.py` | 329 | `create_run` emits the http/server span + injects `RXYCODE_TRACEPARENT` (best-effort) |
| `packages/rxycode-worker/src/rxycode_worker/supervisor.py` | 423 | `claim` opens the `worker.run` span honoring the injected parent; `commit_terminal`/`confirm_cancel` close it |
| `packages/rxycode-worker/src/rxycode_worker/agent_events.py` | 487 | `RunJournal.record` emits `graph.agent.*` lifecycle + `tool.*` spans alongside journaled events |
| `apps/web/src/features/usage/UsagePage.tsx` | 238 | per-run trace `<details>` with `elapsed_ms`/`total_span_work_ms`, abnormal-cost badge |
| `tests/web/w7/test_w7_c04_unit.py` | 701 | contract (production-emitted spans) + negative (secret redaction) + `traceparent` propagation + W3C edge cases |
| `tests/web/w7/test_w7_c04_module.py` | 450 | integration: two real spine runs, ledger↔provider alignment, abnormal surfaced; multi-ledger run aggregation |
| `evidence/web/WEB-W7-C04/collect_evidence.py` | 428 | real evidence collector (trace dump, metrics dump, dashboard.png, bottleneck.md) |

## Production wiring (audit-r1)

Every span is emitted by existing production functions — the tests and the
collector only drive the spine:

* `create_run` opens one `http POST /api/v1/runs` span (kind `server`)
  before the durable write, binds `run_id`, stamps `http.status_code=202`,
  and publishes its context via `inject_env` — the same
  `RXYCODE_TRACEPARENT` env channel the worker already inherits
  `RXYCODE_WEB_DATABASE_URL` from. Idempotent-hit paths close the span on
  the same trace; failures never export.
* `supervisor.claim` opens one `worker.run` span (kind `worker`) whose
  remote parent is `extract_env()` — the server's injected context — and
  re-publishes its own context so journaled children nest under it.
  `commit_terminal` / `confirm_cancel` close it with the terminal status.
* `RunJournal.record` emits `graph.agent.<id>` spans for
  `event/agent_started`→`event/agent_done|failed|cancelled` and `tool.<name>`
  spans for `event/tool_begin`→`event/tool_end` (mid-call deltas merge into
  the open span; a one-shot tool event still yields a point-in-time span),
  all carrying the sanitized `tool_call_id`.

All three seams are strictly best-effort: open/emit/close are wrapped so a
telemetry failure logs a warning and the business flow proceeds untraced.

## Span-store decision

Spans are journaled as `telemetry.span` rows in **`run_events`**
(`RunEventsSpanExporter` → `append_event`). Rationale: tenant-scoped rows,
durable transactional writes (event + outbox in one tx), replayable via
`events.store.replay`, and the existing `/api/v1/runs/{run_id}/events`
endpoint already enforces ownership (`RUN_NOT_FOUND` → 404 for a foreign
tenant — proven in the contract test). No new table, no Alembic migration.
`trace_id` is queryable by `run_id` via `metrics.run_trace_summary`.

## Propagation mechanism

W3C `traceparent` (`{version}-{32-hex trace_id}-{16-hex span_id}-{flags}`):
`inject_env` publishes `RXYCODE_TRACEPARENT` into the environment — the same
channel the worker already uses to inherit `RXYCODE_WEB_DATABASE_URL` —
`extract_env` reads it back as the remote parent. In-process parenting uses
either an explicit `SpanContext` or the `use_span` ContextVar. W3C edge
cases are enforced and tested: version `ff` rejected (other versions
accepted), flags must be exactly two hex chars, `sampled` is bit `0x01`
(`02` is NOT sampled), and a malformed explicit parent inside an active
`use_span` falls back to the ambient context instead of forking a new trace.

## Honest duration accounting (audit-r1)

`run_trace_summary` (and the UsagePage `traceSummary` mirror) report two
distinct numbers: `elapsed_ms` — the run's wall clock, i.e. the single root
span's duration or `max(end_epoch) − min(start_epoch)` when spans do not
share one root — and `total_span_work_ms`, the sum of all span durations.
Nested spans are never double-counted as elapsed time; the per-layer
breakdown (`layers`) is preserved alongside.

## Ledger aggregation (audit-r1)

`UsageRecord` permits multiple rows per run (unique key is
`(run_id, model_id, price_version)`). `run_trace_summary` and
`tenant_cost_metrics` therefore aggregate **every** usage row per run —
summed tokens, summed amount, `row_count`, distinct model/price-version
lists — reconcile the summed tokens against the provider `agent_done`
snapshot (`aligned`/`token_delta`/`mismatches`), and apply the $1
`abnormal` threshold to the per-run SUM (two $0.60 rows → $1.20 →
abnormal), never row-by-row. `test_w7_c04_multi_ledger` proves it.

## OTel/Langfuse seam

`opentelemetry` is not installed (verified) and was not added. `Tracer`
takes a constructor-injected exporter — any object with `export(dict)` —
so a real OTLP/HTTP exporter or OTel SDK drops in with zero call-site
changes. `OTEL_KIND` maps our kinds onto `SERVER/CLIENT/INTERNAL/PRODUCER`.

## Trace-summary API surface

* `metrics.run_trace_summary(database_url, tenant_id=…, run_id=…)` — one
  run's trace_id, correlated spans, per-layer counts/durations,
  `elapsed_ms`/`total_span_work_ms`, aggregated ledger, provider
  `event/agent_done` snapshot, cache stats, cost + abnormal flag.
  Foreign tenant → `{"code": "RUN_NOT_FOUND", "spans": []}`.
* `metrics.tenant_cost_metrics(database_url, tenant_id)` — per-run
  ledger↔provider reconciliation lines (summed over all rows), totals,
  `abnormal` list (verbatim, still counted in totals), `mismatches`.
* HTTP surface: existing `/api/v1/runs/{run_id}/events` (owner-scoped SSE
  replay) + `/api/v1/usage`. No new route — the whitelist has no router
  file, and these endpoints already enforce tenant ownership. The client
  `traceSummary` in UsagePage builds the same summary from the SSE replay.

## Secret safety

`sanitize_attrs` drops secret-shaped keys entirely (`prompt`,
`system_prompt`, `messages`, `instructions`, `completion`, `password`,
`api_key`, `*key*`, `*token*`, `*secret*`, `*authorization*`, `*cookie*`,
`*_key`), recording only `<key>_len` + `<key>_sha256` for correlation.
Sanitization recurses — mappings nested in dicts AND inside lists are
sanitized, never stringified raw — and is idempotent (its own
`*_len`/`*_sha256` metadata survives a second pass). Every stored string
passes `log.log_helpers.redact_sensitive` (inlined fallback keeps the same
patterns if the core package is unreachable) plus the telemetry-local
credential shapes (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`, `github_pat_`,
`xox[bapors]-`, `AKIA…`, `Bearer <token>`), truncated at 200 chars. The
negative test stores a real `sk-…`/`password=`/`ghp_` stderr plus a nested
`{"events": [{"password": …, "prompt": …}]}` attr and asserts no raw
secret ever lands in the payload bytes — only `[REDACTED]`/`*_len`/`*_sha256`
forms survive. `log/log_helpers.py` is untouched.

## Red → green

* `red.txt` — 4/4 import errors (`rxycode_worker.telemetry`,
  `rxycode_server.metrics` missing) before implementation; audit-r1
  section: 5/6 failures of the new assertions against the pre-fix source.
* `green.txt` — focused 4/4 (audit-r1: 6/6); full `tests/web/w7` 29/29
  (audit-r1: 31/31); regressions w6_c04+w2_c07+s1_s2 9/9; ruff clean;
  `npm run typecheck` clean; `git diff --check` clean (all files LF, no
  trailing ws).

## Browser E2E

**Browser E2E: BLOCKED** — `apps/web` has no Playwright dependency, so no
browser E2E exists for this card. The UsagePage trace block (elapsed/total
work fields, per-layer breakdown, abnormal badge) is covered by the
`run_trace_summary` contract assertions and the `traceSummary`
client mirror instead.

## Evidence artifacts

* `trace_dump.json` — real trace `64a4a5722d4f4a17856dda34ede63729`,
  4 correlated spans (http server → worker.run → graph.agent → tool),
  `elapsed_ms` 29.4 vs `total_span_work_ms` 557.5, ledger $19.75308600
  aligned with the provider snapshot, abnormal run listed, real
  `export_probe_ms` measurements (33.4/39.9 ms per `append_event`).
* `metrics_dump.json` — both runs' summaries + `tenant_cost_metrics` +
  per-run wall timings.
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
