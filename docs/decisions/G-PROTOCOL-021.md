# G-PROTOCOL-021 · GX4-B checkpoint/snapshot/create

```yaml
protocol_change:
  request_id: G-PROTOCOL-021
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "checkpoint/snapshot/create"
  compatibility: "Additive. B8 checkpoint/create (auto write reason) is unchanged. Named snapshots are a distinct user-initiated method."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_checkpoint_rewind.py::test_appserver_snapshot_rewind_rpc
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Probe: B8 has `checkpoint/create` `{session_id, reason?, turn_id?}` — no `name`.
Named snapshot is semantically separate from automatic write checkpoints.
Request `{name, session_id}` plus optional `user_prompt`.
Response reuses B8 checkpoint public record with additive `name`/`user_prompt`/`seq`.
