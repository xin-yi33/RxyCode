# G-PROTOCOL-007 · PhaseG-B8 review/checkpoint/git

```yaml
protocol_change:
  request_id: G-PROTOCOL-007
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "review/start|read|comment checkpoint/create|list|read|restore git/stage|unstage|revert review/* events"
  compatibility: "Additive. Review is read-only. git/checkpoint writes go through B7 permission. capability_snapshot.review/review_comments/checkpoint/git_hunk_actions=true."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_review/fixtures/b8-success.json
    denied: tests/test_review/fixtures/b8-denied.json
    timeout: tests/test_review/fixtures/b8-timeout.json
    reconnect: tests/test_review/fixtures/b8-reconnect.json
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```
