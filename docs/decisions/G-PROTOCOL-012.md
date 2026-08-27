# G-PROTOCOL-012 · PhaseG-B13 package compatibility

```yaml
protocol_change:
  request_id: G-PROTOCOL-012
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_optional_field
  method_or_event: "initialize.package release/status|diagnose"
  compatibility: "Additive. initialize.package is optional. Mismatch is diagnosed, never silently remapped. Update failure keeps previous tree."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_release/test_b13_release.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
