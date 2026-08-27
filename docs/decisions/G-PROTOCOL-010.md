# G-PROTOCOL-010 · PhaseG-B11 capability / skill / MCP projections

```yaml
protocol_change:
  request_id: G-PROTOCOL-010
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "capabilities/list|get|set_enabled|invoke|cancel|audit"
  compatibility: "Additive. capability_panel=true. browser remains false and cannot be enabled as a bypass. Uninstalled/unauthorized capabilities have available=false. Invoke is a cancellable Tool/Approval/Review job."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_capabilities/fixtures/b11-success.json
    denied: tests/test_capabilities/fixtures/b11-denied.json
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
