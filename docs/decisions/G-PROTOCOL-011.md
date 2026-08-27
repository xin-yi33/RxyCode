# G-PROTOCOL-011 · PhaseG-B12 recovery and notifications

```yaml
protocol_change:
  request_id: G-PROTOCOL-011
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "recovery/status|replay|reclaim notifications/list|ack|cursor"
  compatibility: "Additive. Incomplete/interrupted/unknown project to recovery_required. Replay is cursor-based and never forges completed. capability recovery/notifications=true."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_recovery/test_b12_recovery.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
