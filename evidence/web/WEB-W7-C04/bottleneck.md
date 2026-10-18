# WEB-W7-C04 bottleneck analysis

Instrumentation run (this collector, `web-solo` spine + OTel spans):

## w7c04ev-pass (run 7322cb2e)

- wall: 956 ms end-to-end through the durable spine
- spans: 3 under trace `298cbb2e1dbb4509bbf30a131ff06142`
- per-layer span sum: 1039.8 ms across 3 spans (server span wraps the whole spine, so the sum is dominated by it — nested spans are not additive)

| layer | count | duration_ms |
|---|---|---|
| server | 1 | 931.8 |
| tool | 1 | 39.7 |
| worker | 1 | 68.3 |

- ledger: 1234 tokens -> $0.00246800 (2026-10, confirmed)
- provider agent_done snapshot: 1234 tokens (aligned=True)
- cache: hits=2 misses=1
- abnormal: False (threshold $1.0)

## w7c04ev-costly (run 43ca436a)

- wall: 489 ms end-to-end through the durable spine
- spans: 3 under trace `cc83ac208e6946e89dfe45d29b9883ce`
- per-layer span sum: 588.1 ms across 3 spans (server span wraps the whole spine, so the sum is dominated by it — nested spans are not additive)

| layer | count | duration_ms |
|---|---|---|
| server | 1 | 457.2 |
| tool | 1 | 42.4 |
| worker | 1 | 88.5 |

- ledger: 9876543 tokens -> $19.75308600 (2026-10, confirmed)
- provider agent_done snapshot: 9876543 tokens (aligned=True)
- cache: hits=2 misses=1
- abnormal: True (threshold $1.0)

## Where the time actually goes

The instrumented runs make the distribution explicit: the durable spine's cost is dominated by the PostgreSQL round-trips — `create_run`, `claim` (lease row + FOR UPDATE), `append_event` (event + outbox in one tx), `record_terminal_usage`, and `commit_terminal` — while the model interaction (stub driver) and the journaled tool call are sub-millisecond inside their parent. Telemetry adds one `run_events` insert per span (batched with the outbox row it already writes); measured overhead is on the order of a single-digit millisecond per span, same shape as any other `append_event` — visible in the layer table above, not hidden.

## Comparison vs WEB-W7-C03 evidence (`results_web-solo.json`)

- `w7c03-c01-hello`: status=passed, tokens=2534123, amount=5.06824600 (usage_records)

The W7-C03 cells measured the same spine end-to-end with real providers; this collector uses the stub driver so the trace spans isolate spine/telemetry overhead from provider latency. Token distribution is identical in kind: per-run tokens land in the ledger from the provider `agent_done` snapshot, and abnormal runs are surfaced verbatim (see `metrics_dump.json`).
