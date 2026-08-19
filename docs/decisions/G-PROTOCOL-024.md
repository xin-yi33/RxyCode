# G-PROTOCOL-024 · GX7-B event/agent_usage

```yaml
protocol_change:
  request_id: G-PROTOCOL-024
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_event
  method_or_event: "event/agent_usage"
  compatibility: "Additive. event/token_usage is unchanged. Frontend must not compute cost."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_usage_tracker.py::test_appserver_emits_agent_usage_on_token_usage
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Payload: `{session_id, seq, input_tokens?, output_tokens?, context_used, context_window?, used_pct?, cost?, currency?, cost_available, reason}`.
`seq` is per-session monotonic. Emit on token_usage/final, each tool_end, and 30s heartbeat.
Context window comes from B10 `summarize_model` — never hardcoded 8192.
Phase 3 summaries have no pricing fields → `cost_available=false` (PENDING_PRICING).
