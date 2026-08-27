# G-PROTOCOL-013 · PhaseG-B14 CLI-Hub

```yaml
protocol_change:
  request_id: G-PROTOCOL-013
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "cli/list|install|uninstall|launch|start|stop|decide|record_failure"
  compatibility: "Additive. cli:<name> is a software id parameter for cli_list/cli_run, not a tools/registry entry (N13/HN2). Isolated venv + pip install of registry/local fixture. Source tags builtin/cli-hub/self-generated. C-C registry-first decide. C-E generate-failure ladder."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_cli_bridge.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
