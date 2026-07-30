# core/governance.py - Runtime Governance

## What Is This Module?

`core/governance.py` provides the production contracts for provider/model rate
limits, role-aware model routing, and sensitive tool-action decisions. The
contracts are wired into `AgentV2`, the LangGraph model resolver, and
`ToolOrchestrator`; they are not standalone helpers that callers must remember
to invoke.

## Rate Limiting

`AsyncTokenBucketRateLimiter` maintains independent request and token buckets
for each canonical provider/model key. A grant atomically consumes one request
unit plus the caller's token reservation. The default Agent configuration is:

```yaml
governance:
  rate_limit:
    enabled: true
    requests_per_period: 120
    tokens_per_period: 2000000
    period_seconds: 60
    request_burst: 120
    token_burst: 2000000
    wait_timeout_seconds: 30
    reserved_output_tokens: 8192
```

`UsageTrackingLLM` reserves estimated input tokens plus
`reserved_output_tokens` before `ainvoke()` or `astream()` reaches the
provider. `AgentV2._raw_stream()` uses the same reservation contract. After a
grant has been acquired, each path owns one `finally` settlement, so normal
completion, provider errors, stream errors, cancellation, and breaker-open
outcomes reconcile that grant exactly once.

Reconciliation adjusts only token capacity. The consumed request unit is never
refunded. Provider-reported input/output usage is preferred; an error or
cancellation falls back to estimated input plus observed partial stream output.
Unused output reservation is refunded up to bucket capacity. Usage beyond the
reservation becomes token debt and delays later calls. A reconciliation error
is logged and cannot replace the original provider exception or suppress
cooperative cancellation. If acquisition itself never returns a grant, there
is nothing to reconcile.

`runtime_status().rate_limit` returns a content-free snapshot for the active
provider/model key. This limiter is deliberately in-process and per
`AgentV2`: a short `threading.RLock` makes one shared Agent safe across event
loops, but there is no distributed quota coordination across separate Agent
instances, processes, or hosts.

## Model Routing

`ModelRouter` supports `default`, `planner`, `executor`, and `reflection`
roles. A known but unconfigured role falls back to `default`; an unknown role
fails closed instead of silently choosing another model. Graph nodes resolve
their declared role through this router, and `runtime_status()` exposes only
the configured role names.

## Sensitive Actions

`SensitiveActionPolicy` is the first production decision in
`ToolOrchestrator`'s gate. It composes the existing risk classifier, Plan-mode
READ boundary, writable-root policy, dry-run setting, explicit command source,
and configured auto-approval levels into an immutable decision. Actual user
approval, execution, evidence, and append-only redacted audit remain owned by
the orchestrator and safety modules.

## Boundaries

- Rate-limit state is process memory, not a provider-side or distributed
  global quota.
- Model routing selects configured local wrappers; it does not discover or
  provision provider models.
- Governance decisions do not create an OS sandbox. Tool and MCP process
  isolation boundaries are documented separately in
  [safety](safety.md) and [MCP](mcp.md).
