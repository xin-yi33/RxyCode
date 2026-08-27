# G-PROTOCOL-028 · GX13-B event/agent_needs_input

```yaml
protocol_change:
  request_id: G-PROTOCOL-028
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_event
  method_or_event: "event/agent_needs_input"
  compatibility: "Additive. Does not rename B12 approval/request or question/request."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_needs_input.py::test_appserver_emits_needs_input
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

B12 probe table:
| B12 name | GX13 use | tier | dedupe |
| approval/request | wait for approval | needs_input | request_id |
| question/request | wait for question | needs_input | question_id |
| event/done, event/final, event/task_complete | reply arrived | response | session_id |
| event/message_delta | stream | ignore | — |

No complete `event/agent_*` wait-input event existed → new_event.
`approval/requested` is a placeholder and is not used.
