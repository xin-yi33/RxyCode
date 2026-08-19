# G-PROTOCOL-005 · PhaseG-B6 execution items

```yaml
protocol_change:
  request_id: G-PROTOCOL-005
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "command/start execution/list|stop|output event/execution"
  compatibility: "Additive. Existing event/tool_begin|tool_end unchanged. capability_snapshot.background_tasks=true; background_turns remains false (B12)."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_execution/fixtures/b6-success.json
    denied: tests/test_execution/fixtures/b6-denied.json
    timeout: tests/test_execution/fixtures/b6-timeout.json
    cancel: tests/test_execution/fixtures/b6-cancel.json
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
