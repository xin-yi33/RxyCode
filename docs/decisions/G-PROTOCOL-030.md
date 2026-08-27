# G-PROTOCOL-030 · GX16-B thread/side_chat/create|close

```yaml
protocol_change:
  request_id: G-PROTOCOL-030
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "thread/side_chat/create | thread/side_chat/close"
  compatibility: "Additive. Parent thread messages are projected, not copied."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_side_chat.py::test_appserver_side_chat_rpc_and_promote_confirm
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

create `{thread_id}` → `{side_thread_id, context_tokens, context_copied:false, budget_tag:side}`.
close `{side_thread_id, promote?, confirm_promote?}`. Promote requires confirm. Default does not write back.
Parent archive/trash closes side chats.
