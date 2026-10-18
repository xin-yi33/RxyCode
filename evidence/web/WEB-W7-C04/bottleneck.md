# WEB-W7-C04 bottleneck analysis

Instrumentation run (this collector, `web-solo` spine + OTel spans):

## w7c04ev-pass (run 3a035ddf)

- wall: 999 ms end-to-end through the durable spine
- spans: 4 under trace `488a5569d51042ceb179ca799e700ed4`
- elapsed_ms (root span): 44.8 · total_span_work_ms: 846.1 across 4 spans (nested spans are not additive — the elapsed root and the summed work are reported separately)

| layer | count | duration_ms (summed per layer) |
|---|---|---|
| server | 1 | 44.8 |
| tool | 1 | 70.4 |
| worker | 2 | 731.0 |

- ledger: 1234 tokens -> $0.00246800 (2026-10, confirmed)
- provider agent_done snapshot: 1234 tokens (aligned=True)
- cache: hits=2 misses=1
- abnormal: False (threshold $1.0)

## w7c04ev-costly (run e1826887)

- wall: 514 ms end-to-end through the durable spine
- spans: 4 under trace `64a4a5722d4f4a17856dda34ede63729`
- elapsed_ms (root span): 29.4 · total_span_work_ms: 557.5 across 4 spans (nested spans are not additive — the elapsed root and the summed work are reported separately)

| layer | count | duration_ms (summed per layer) |
|---|---|---|
| server | 1 | 29.4 |
| tool | 1 | 67.1 |
| worker | 2 | 461.1 |

- ledger: 9876543 tokens -> $19.75308600 (2026-10, confirmed)
- provider agent_done snapshot: 9876543 tokens (aligned=True)
- cache: hits=2 misses=1
- abnormal: True (threshold $1.0)

## Where the time actually goes

The instrumented runs make the distribution explicit: the durable spine's cost is dominated by the PostgreSQL round-trips — `create_run`, `claim` (lease row + FOR UPDATE), `append_event` (event + outbox in one tx), `record_terminal_usage`, and `commit_terminal`. The `worker.run` span wraps claim→commit (the leased execution); `graph.agent.*` wraps the agent lifecycle; the `tool.*` span (67.1 ms on the costly run) brackets two `run_events` journal writes plus the tool call itself — it is NOT sub-millisecond, and its duration is spent mostly on the journal appends. The stub driver's model interaction itself is sub-millisecond inside its parent.

Telemetry export costs one `append_event` (event + outbox INSERT in one tx) per span. A span's `duration_ms` is stamped BEFORE export, so export overhead never inflates durations — the measured export cost on this run: 33.4, 39.9 ms per append. `elapsed_ms` is the root span's duration (or the union of span intervals when no single root exists); `total_span_work_ms` sums nested durations and therefore over-counts wall time by design — both are reported, neither is hidden.

Browser E2E: BLOCKED — apps/web has no Playwright dependency, so no browser E2E was run for this card; the UsagePage trace block is covered by the summary contract tests instead.

## Comparison vs WEB-W7-C03 evidence (`results_web-solo.json`)

- `w7c03-c01-hello`: status=passed, tokens=2534123, amount=5.06824600 (usage_records)

The W7-C03 cells measured the same spine end-to-end with real providers; this collector uses the stub driver so the trace spans isolate spine/telemetry overhead from provider latency. Token distribution is identical in kind: per-run tokens land in the ledger from the provider `agent_done` snapshot, and abnormal runs are surfaced verbatim (see `metrics_dump.json`).
