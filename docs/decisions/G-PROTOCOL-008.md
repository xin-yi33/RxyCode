# G-PROTOCOL-008 · PhaseG-B9 file preview and worktree

```yaml
protocol_change:
  request_id: G-PROTOCOL-008
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "file/preview|tree|open_external worktree/list|create|close|prune|handoff|handoff/rollback"
  compatibility: "Additive. Preview is read-only. file/open_external requires confirm and never launches. worktree/handoff transfers ownership to target_session. Destructive actions require B7 permission and confirm. capability file_preview/worktree=true."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_file_preview/test_b9_preview.py
    denied: tests/test_worktrees/test_b9_worktrees.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
