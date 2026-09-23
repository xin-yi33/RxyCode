# G-PROTOCOL-031 · plugin/catalog + plugin/connect/start|callback

```yaml
protocol_change:
  request_id: G-PROTOCOL-031
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "plugin/catalog | plugin/connect/start | plugin/connect/callback"
  compatibility: "Additive. plugin/list|install|uninstall|toggle unchanged. PAT install token remains a non-schema extra on plugin/install."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_plugin.py::test_oauth_start_connect_authorize_hosts
    callback: tests/test_plugin.py::test_oauth_callback_marks_connected_and_publishes
  migration: none
  rollback: revert this card commit
  owner: agent-core-boundaries
```

`plugin/catalog` returns the in-repo store (GitHub, Canva, computer-use) merged
with install/auth state. `plugin/connect/start` builds a browser authorize URL
on the provider OAuth host. `plugin/connect/callback` completes the code
exchange through an injected HTTP transport and writes tokens to plugin
`user.json` (never `config.yaml`).
