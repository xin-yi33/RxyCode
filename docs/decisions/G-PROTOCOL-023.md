# G-PROTOCOL-023 · GX4 checkpoint record optional fields

```yaml
protocol_change:
  request_id: G-PROTOCOL-023
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_optional_field
  method_or_event: "checkpoint/create|list|read.name,user_prompt,seq"
  compatibility: "Additive optional fields on existing checkpoint records. Absent on older auto checkpoints is valid (null)."
  generated_types: "none (record is an untyped object in list/read results)"
  fixtures:
    success: tests/test_checkpoint_rewind.py::test_named_snapshot_and_rewind_orchestration
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Frozen public snapshot shape: `{checkpoint_id, seq, name?, file_count, diff_hash, user_prompt, created_at}`.
`seq` is per-session monotonic. `name` and `user_prompt` are null on automatic write checkpoints.
