# G-PROTOCOL-016 · PhaseG-B18 plugin market

```yaml
protocol_change:
  request_id: G-PROTOCOL-016
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "plugin/list|install|uninstall|toggle"
  compatibility: "Additive. plugin/toggle forwards to B11 capabilities/set_enabled. No appserver/handlers/. Skills/MCP register into existing CapabilityService listers; no second invoke path. session/capability methods unchanged."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_plugin.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
