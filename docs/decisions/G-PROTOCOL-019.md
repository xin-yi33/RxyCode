# G-PROTOCOL-019 · GX3-B review/comment/add|resolve

```yaml
protocol_change:
  request_id: G-PROTOCOL-019
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "review/comment/add | review/comment/resolve"
  compatibility: "Additive. Existing review/comment (B8, start_line/end_line/finding_id) is unchanged and not an alias."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_review_comments.py::test_appserver_comment_add_resolve_rpc
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

`review/comment/add` request `{review_id, file, line, hunk_hash, body}`.
`review/comment/resolve` request `{comment_id}`.
Status: open → resolved; open → stale → resolved; no reopen; comments never enter git.
