# G-PROTOCOL-027 · GX9-B plan/persist|implement

```yaml
protocol_change:
  request_id: G-PROTOCOL-027
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_method
  method_or_event: "plan/persist | plan/implement"
  compatibility: "Additive. Does not mutate B5 plan state machine."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_plan_files.py::test_appserver_plan_rpc
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

`plan/persist` `{thread_id, title, goal, steps, acceptance}` writes markdown
`RXYCODE_DATA_DIR/plans/<thread_id>-<slug>.md` with 目标/步骤/验收清单.
`plan/implement` `{plan_id, confirm: true}` marks implementing and returns turn_prompt.
