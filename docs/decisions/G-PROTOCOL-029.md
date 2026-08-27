# G-PROTOCOL-029 · GX14-B capability on agent/invoke and session/prompt

```yaml
protocol_change:
  request_id: G-PROTOCOL-029
  producer: appserver
  consumers: [frontend/protocol-client, frontend/desktop-app, opentui, linkagent]
  current_schema_version: "1.1.0"
  change_kind: new_optional_field
  method_or_event: "agent/invoke.capability | session/prompt.capability"
  compatibility: "Additive optional enum no_tools|edit_only|full. Default full (absent = full). Does not change GX2 presets or B5 mode=plan."
  generated_types: "python -m protocol.schema; bun run generate in protocol-client"
  fixtures:
    success: tests/test_invoke_capability.py::test_registry_rejects_edit_only_and_no_tools
  migration: none
  rollback: revert this card commit
  owner: composer-2.5
```

Capability is a hard tool boundary at appserver/tool_registry_capability.py.
edit_only forbids bash/delete/git (protocol error, not approval).
no_tools forbids every tool.
vs GX2: orthogonal; full_access does not bypass capability.
vs mode=plan: capability is checked first and returns capability_denied; plan-mode blocked text is not used for this gate.
Composer ModeSelector uses session/prompt; @agent uses agent/invoke — both carry the field.
