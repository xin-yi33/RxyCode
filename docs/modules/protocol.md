# protocol/

Typed JSON-RPC wire protocol between RxyCode clients and the headless core.

## Purpose

Phase 2 introduces a versioned, pydantic-defined contract so OpenTUI, Desktop,
and `api_server.py` can share one schema instead of ad-hoc SSE field names.

## Layout

| File | Role |
|------|------|
| `__init__.py` | Package marker；产品包 `__init__.py` 把裸名 `protocol`（以及 `core` / `utils` 等）统一到 `RxyCode.RxyCode1_1_0.*`，避免两套 class |
| `version.py` | `PROTOCOL_VERSION` (currently `1.1.0`; `PROTOCOL_VERSION_MIN` `1.0.0`) |
| `requests.py` | Client -> server (`initialize`, `session/*` incl. `set_thinking_expanded` / `warm`, `shutdown`, `models/*` incl. `ModelsSetActiveRequest.effort`（2026-08-12：optional_field，全局思考强度档位）） |
| `notifications.py` | Server -> client one-way events |
| `server_requests.py` | Server -> client messages that need a reply (approval, question) |
| `types.py` | Shared literals (`RiskLevelName`, `RunStatus`, ...) |
| `schema.py` | `export_schema()` + `python -m protocol.schema` CLI |
| `schema.json` | Frozen export checked by `tests/test_protocol_schema.py` |
| `agents.py` | Phase F expert-team types (`AGENT_PROTOCOL_MODELS`): AgentSpec / TeamSpec / SopStage / Delegate* / ConsultRequest / VerdictRecord / TeamEvent / RoutingDecision / F16 `task_delegate` `progress` `tool_call` `plan` `result` `abort`. Exported into `schema.json` `$defs` and the codegen-only `AgentProtocol` union. |
| `subagents.py` | `SUBAGENT_PROTOCOL_VERSION=1`: AgentDefinition, TaskRequest, TaskResult, TriggerKind, ChildStatus, WorkspaceMode, BudgetSpec, PermissionSpec, ContextEnvelope |
| `subagents_schema.json` | Machine-validatable subagent protocol schema |

## SSE event inventory (P1 step 3)

Audit command (from `00-EXECUTION-PLAN.md` P1):

```powershell
Select-String -Path api_server.py -Pattern '"type":\s*"' |
  ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

### `api_server.py` → `api_server_stream.py` `StreamTUI` / chat queue (`type` field)

StreamTUI was split out of `api_server.py` into `api_server_stream.py`. The
`type` fields map to protocol models as follows (line refs are
`api_server_stream.py` unless noted):

| SSE `type` | Source (file:line) | Payload fields | Protocol model |
|------------|-------------------|----------------|----------------|
| `token` | `api_server_stream.py:299` (`_put`; buffer key `token`; `flush_stream_buffers` :306) | `text` | `event/message_delta` (`MessageDelta`) |
| `progress` | `api_server_stream.py:327` (`write_progress`; buffer key `progress`) | `text` | `event/progress` (`ProgressUpdate`) |
| `reasoning` | `api_server_stream.py:420` (`_emit_thinking_snapshot`) | `text`, optional `snapshot: true` | `event/reasoning_snapshot` (`ReasoningSnapshot`) |
| `plan` | `api_server_stream.py:349` (`write_plan`; `_put` :299) | `steps` | `event/plan` (`PlanUpdate`) |
| `step` | `api_server_stream.py:354` (`write_step`) | `index`, `total`, `text` | `event/step` (`StepProgress`) |
| `tool_call` | `api_server_stream.py:358` (`write_tool_call`) | `name`, `args`, `message_id`, optional `timestamp` | `event/tool_begin` (`ToolBegin`; `call_id` <- `message_id`) |
| `tool_result` | `api_server_stream.py:385` (`write_tool_result`) | `result`, `status`, optional `message_id` | `event/tool_end` (`ToolEnd`) |
| `error` | `api_server_stream.py` (`write_error`), `api_server.py` | `message`, optional `message_id`, `run_id`, `status` | `event/error` (`ErrorNotification`) |
| `final` | `core/session.py:57` via `notification_to_sse_event` | `text`, `thinking`, `run_id`, token fields, `session_schema_version` | `event/final` (`FinalAnswer`) + `event/token_usage` (`TokenUsage`) |
| `done` | `api_server_stream.py` (stream teardown) | `run_id`, `status` | `event/done` (`RunComplete`) |

### Bidirectional server requests (still SSE today)

| SSE `type` | Source | Payload fields | Protocol model |
|------------|--------|----------------|----------------|
| `approval_request` | `core/safety/approval.py:46` | `approval_id`, `tool`, `risk`, `args` | `approval/request` (`ApprovalRequest`) |
| `question_request` | `core/question.py:47` | `question_id`, `question`, `header`, `options[]`, `input_type` | `question/request` (`QuestionRequest`) |

HTTP replies today: `POST /approve` and `POST /question/respond` in `api_server.py`.

### Not yet emitted on the wire

| Protocol model | Notes |
|----------------|-------|
| `TaskStarted`, `TaskComplete` | Reserved for LangGraph task boundaries (future Session emit) |

`JobStatusUpdate` and `ServerHeartbeat` are **already emitted on the wire** by
`appserver/server.py` (`_emit_job_state()` at :112-115 emits `submitted`/
`running`/`failed`; `ServerHeartbeat` at :484).

### Subagent JSON-RPC methods (appserver)

`appserver/server.py` registers (server.py:527-552):
- `session/set_thinking_expanded`, `session/warm`
- `agent/invoke` — user `@agent` mention dispatch
- `task/start` — explicit subagent dispatch
- `subagents/list` — list registered agent definitions
- `subagents/capability` — feature flags + capability report

## Commands

```powershell
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
python -m pytest tests/test_protocol_schema.py -q
python -m ruff check protocol
```

## Schema → TypeScript 类型生成（C2）

协议 schema 通过 `json-schema-to-typescript` 自动生成 TypeScript 类型定义。

| Schema 源 | 生成目标 | 生成命令 |
|-----------|---------|---------|
| `protocol/schema.json` | `frontend/protocol-client/src/generated/types.ts` | `bun run generate`（在 `frontend/protocol-client/` 下执行） |
| `protocol/subagents_schema.json` | `frontend/protocol-client/src/generated/subagent-types.ts` | 同上（`generate` 脚本已包含两个 schema） |

**规则**：
- 手改 `generated/` 下的文件直接违反 G3/C2，CI 会自动检测不一致。
- 协议变更顺序：`protocol/*.py` → `protocol/schema.json`（`python -m protocol.schema` export）→ `bun run generate`（生成 TS 类型）→ 提交全部四个文件。
- `frontend/protocol-client/package.json` 中的 `generate` 脚本是唯一可用的类型生成入口。

## Dependencies

- **Consumers (today)**: `appserver/` (`server.py`, `subagent_routes.py`), `core/session.py` (imports `protocol.notifications`), `core/subagents/` (imports `protocol.subagents`)
- **Consumers (future)**: `frontend/protocol-client`
- **Sources today**: `api_server.py`/`api_server_stream.py` SSE, `core/safety/approval.py`, `core/question.py`, `core/subagents/` events