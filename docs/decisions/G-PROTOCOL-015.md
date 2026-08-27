# G-PROTOCOL-015 · PhaseG-B17 trash

```yaml
protocol_change:
  request_id: G-PROTOCOL-015
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "thread/delete|restore|purge|list_deleted"
  compatibility: "Additive. ThreadMetadata optional deleted_at/restored_at/list_category/associated_files. thread/purge requires confirm_purge is JSON true. session/trash|restore|purge remain and session/purge does not require confirm."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_trash.py
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
