# G-PROTOCOL-003 · PhaseG-B4 project/workspace

```yaml
protocol_change:
  request_id: G-PROTOCOL-003
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "project/list|add|remove|set_active workspace/status|resolve event/workspace_changed"
  compatibility: "Additive methods/events. session/new still required; now canonicalizes workspace and rejects missing paths."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_projects/test_b4_projects.py
    denied: PATH_OUTSIDE_WORKSPACE / PATH_NOT_FOUND
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
