# G-PROTOCOL-025 · GX8-B thread/fork

```yaml
protocol_change:
  request_id: G-PROTOCOL-025
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "thread/fork"
  compatibility: "Additive. session/fork (whole-thread copy) is unchanged and not an alias."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_thread_fork.py::test_appserver_thread_fork_and_pin_rpc
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Request `{thread_id, message_id, edited_text?}`.
Fork point must be a user message. Copies messages through the cutoff; does not copy tools, approval policy, or child sessions. Parent unchanged.
