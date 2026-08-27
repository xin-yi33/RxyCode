# G-PROTOCOL-001 · PhaseG-B2 handshake

```yaml
protocol_change:
  request_id: G-PROTOCOL-001
  producer: appserver
  consumers:
    - frontend/protocol-client
    - frontend/desktop-app
    - opentui
    - linkagent
  current_schema_version: "1.1.0"
  change_kind: new_optional_field
  method_or_event: "initialize / initialized / error.data"
  compatibility: "Additive. Existing initialize keys unchanged. 1.0.0–1.1.0 accepted. Incompatible versions now return PROTOCOL_MISMATCH instead of warning-and-continue."
  generated_types: "cd frontend/protocol-client && bun run generate"
  fixtures:
    success: tests/test_protocol/test_b2_appserver_handshake.py::test_initialize_1_0_and_1_1_succeed
    denied: tests/test_protocol/test_b2_appserver_handshake.py::test_incompatible_version_is_rejected
    timeout: "error.data.retryable true for TIMEOUT (mapped from -32004); no new timeout path"
    reconnect: "none (B12)"
  migration: none
  rollback: "revert this card commit; initialize again only warns on version mismatch"
  owner: composer-2.5
```

未删除字段，未改已有字段语义。`capabilities.{sessions,approval,models,credentials}` 仍在。
`capability_snapshot` / `model_providers` / `permission_profiles` / `initialized` 为新增。
`full_access` 与 G 文档权限名未在本卡宣称已落地（B7）。
