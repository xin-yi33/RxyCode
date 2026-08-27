# G-PROTOCOL-026 · GX8-B thread/pin

```yaml
protocol_change:
  request_id: G-PROTOCOL-026
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "thread/pin"
  compatibility: "Additive. session/rename and session/archive are reused (path A). pin is a mutation method, not an optional-field substitute."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_thread_fork.py::test_appserver_thread_fork_and_pin_rpc
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Request `{thread_id, pinned: bool=true}`. Session summary gains additive `pinned` (default false).
