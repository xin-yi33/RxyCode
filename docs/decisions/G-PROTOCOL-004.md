# G-PROTOCOL-004 · PhaseG-B5 Thread/Turn/Item/Child

```yaml
protocol_change:
  request_id: G-PROTOCOL-004
  producer: appserver
  consumers:
    - frontend/protocol-client
    - frontend/desktop-app
    - opentui
    - linkagent
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "session/fork|archive|unarchive|items|tree turn/start|steer|interrupt|retry sessions/list filters event persist-by-child-session"
  compatibility: "Additive session/* methods. Frozen Phase 4 session/* names are kept; thread/* is not introduced. Fork is an independent thread (forked_from) and is not a child session. Child events persist on session_id, not root_session_id."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_threads/fixtures/h5-success.json
    denied: tests/test_threads/fixtures/h5-denied.json
    timeout: tests/test_threads/fixtures/h5-timeout.json
    reconnect: tests/test_threads/fixtures/h5-reconnect.json
    cancel: tests/test_threads/fixtures/h5-cancel.json
    crash: tests/test_threads/fixtures/h5-crash.json
    replay: tests/test_threads/fixtures/h5-replay.json
    child_tree: tests/test_threads/fixtures/h5-child-tree.json
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

`capability_snapshot.thread_fork` is now true. `child_sessions/*` from Phase D is unchanged.
