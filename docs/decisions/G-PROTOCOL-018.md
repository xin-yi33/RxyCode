# G-PROTOCOL-018 · GX2-PROTO approval/full_access_enable

```yaml
protocol_change:
  request_id: G-PROTOCOL-018
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "approval/full_access_enable"
  compatibility: "Additive. Session-only unlock of B7 full_access. Never persisted. Restart clears. Actor required (settings-authenticated session). permission/set still rejects full_access."
  generated_types: "python -m protocol.schema > protocol/schema.json; cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_permission_mode.py::test_appserver_mode_set_rpc
    denied: tests/test_permission_mode.py::test_restart_clears_full_and_high_risk_preset
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Request `{actor, source="settings"}`. Response `{enabled, actor, source, created_at}`.
