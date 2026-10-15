# WEB-W1-C04 self-audit

- PromptRequest gained optional run_id and device_id. method stays session/prompt. A legacy fixture without those fields still validates.
- initialize and approval/request method names are unchanged.
- RunRecord, WebEvent, DeviceRecord, WebDiagnostic, ToolCall, and ToolChunk are exported in WebProtocol. frozen_event_methods includes AgentEvent literals, and the JSON schema enum lists them, including event/agent_started. WebDiagnostic does not change ProtocolErrorCode.
- schema_digest hashes the exported field schemas of those models, not only their names.
- rxycode_protocol.tool_rpc re-exports the protocol.requests models. There is one ToolCall definition.
- schema.json is the output of export_schema(). schema_digest covers protocol version, frozen event names, existing error codes, PromptRequest capabilities, and the four web models.
- frontend/protocol-client/src/generated/types.ts was produced by bun run generate. web_digest.ts is written from schema_digest. index.ts re-exports the generated types. tsc --noEmit passed.
- required_field_breaks_legacy returns true when a required field is missing from a legacy payload. The negative test uses a subclass that makes run_id required.
- Desktop UI was not run. The card has no UI E2E. No second agent loop. RiskLevel was not changed.
- Protocol schema tests: 7 passed. Cache tests were not required because this card does not touch core/ or tool selection.
