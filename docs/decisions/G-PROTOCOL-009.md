# G-PROTOCOL-009 · PhaseG-B10 settings and ModelSummary

```yaml
protocol_change:
  request_id: G-PROTOCOL-009
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "settings/get|set|models|diagnose|rollback"
  compatibility: "Additive. settings capability=true. Layers are global→project→workspace→thread/turn. Secrets never returned. ModelSummary.limit_source is the Phase 3 resolver source. Unknown models keep their model_id and set is_fallback with warning. capability settings=true."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_settings/fixtures/b10-success.json
    denied: tests/test_settings/fixtures/b10-denied.json
  migration: "settings schema_version 0 (flat keys) migrates to v1 layers; newer schema is rejected"
  rollback: revert this card commit
  owner: composer-2.5
```
