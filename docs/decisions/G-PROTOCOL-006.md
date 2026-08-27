# G-PROTOCOL-006 · PhaseG-B7 permission/approval

```yaml
protocol_change:
  request_id: G-PROTOCOL-006
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "permission/get|set approval/decide|revoke|audit"
  compatibility: "Additive. Five profiles advertised; full_access not selectable. evaluate binds project_id+workspace scope. allow_scoped_actions requires granted scopes. approval.auto_review is read-only and cannot consume user approvals or expand sandbox/writable roots/network. command/start optional approval_id/project_id/actor/expand_* fields."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_approval/fixtures/b7-success.json
    denied: tests/test_approval/fixtures/b7-denied.json
    timeout: tests/test_approval/fixtures/b7-timeout.json
    reconnect: tests/test_approval/fixtures/b7-reconnect.json
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
