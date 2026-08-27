# G-PROTOCOL-022 · GX4-B checkpoint/rewind

```yaml
protocol_change:
  request_id: G-PROTOCOL-022
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "checkpoint/rewind"
  compatibility: "Additive. B8 checkpoint/restore remains the code-restore primitive and is not aliased."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_checkpoint_rewind.py::test_appserver_snapshot_rewind_rpc
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Request `{checkpoint_id, confirm: true, session_id}`.
`confirm` must be JSON boolean true from an explicit UI action.
Orchestration: ① pre-rewind snapshot ② B8 restore ③ conversation projection cutoff ④ refill_prompt.
Response `{restore_point, restored_files, truncated_messages, refill_prompt}`.
Historical checkpoints are retained (forward nav = rewind to a later id).
