# G-PROTOCOL-017 · GX2-B approval/mode_set

```yaml
protocol_change:
  request_id: G-PROTOCOL-017
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "approval/mode_set"
  compatibility: "Additive. Request {preset: ask|auto|full} only — no {mode} field. Maps onto existing B7 profiles; does not add a third permission model. permission/set unchanged."
  generated_types: "python -m protocol.schema > protocol/schema.json; cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_permission_mode.py::test_appserver_mode_set_rpc
    denied: tests/test_permission_mode.py::test_default_ask_and_full_rejected_until_enabled
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Probe: B7 `permission/set` rejects `full_access` (`selectable: false`). No enable method existed.
`approval/full_access_enable` is G-PROTOCOL-018 (session-scoped, restart clears).
Error code for mode_set full while locked: `full_access_not_enabled`.
