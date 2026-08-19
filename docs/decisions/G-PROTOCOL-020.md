# G-PROTOCOL-020 · GX3-PROTO review/start scope enums

```yaml
protocol_change:
  request_id: G-PROTOCOL-020
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_optional_field
  method_or_event: "review/start.scope"
  compatibility: "Additive enum values. Existing working_tree/base_branch/commit/files unchanged. branch aliases to base_branch. commit reused."
  generated_types: "none (scope remains a string field)"
  fixtures:
    success: tests/test_review_comments.py::test_new_scopes_unstaged_staged_last_turn
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

GX3 five-tier vs B8 probe:
- `commit` → reuse B8 `commit`
- `branch` → alias B8 `base_branch`
- `unstaged` → new (`git diff` unstaged)
- `staged` → new (`git diff --cached`)
- `last_turn` → new; empty diff when no turn file list (`empty_reason=no_turn_diff`)
