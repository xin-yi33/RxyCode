# protocol/

Typed JSON-RPC wire protocol between RxyCode clients and the headless core.

## Purpose

Phase 2 introduces a versioned, pydantic-defined contract so OpenTUI, Desktop,
and `api_server.py` can share one schema instead of ad-hoc SSE field names.

## Layout

| File | Role |
|------|------|
| `version.py` | `PROTOCOL_VERSION` (currently `1.0.0`) |
| `requests.py` | Client -> server (`initialize`, `session/*` incl. `set_thinking_expanded` / `warm`, `shutdown`) |
| `notifications.py` | Server -> client one-way events |
| `server_requests.py` | Server -> client messages that need a reply (approval, question) |
| `types.py` | Shared literals (`RiskLevelName`, `RunStatus`, ...) |
| `schema.py` | `export_schema()` + `python -m protocol.schema` CLI |
| `schema.json` | Frozen export checked by `tests/test_protocol_schema.py` |

## SSE event inventory (P1 step 3)

Audit command (from `00-EXECUTION-PLAN.md` P1):

```powershell
Select-String -Path api_server.py -Pattern '"type":\s*"' |
  ForEach-Object { "$($_.LineNumber): $($_.Line.Trim())" }
```

### `api_server.py` `StreamTUI` / chat queue (`type` field)

| SSE `type` | Source (file:line) | Payload fields | Protocol model |
|------------|-------------------|----------------|----------------|
| `token` | `api_server.py:2277` (`flush_stream_buffers`, buffer key `token`) | `text` | `event/message_delta` (`MessageDelta`) |
| `progress` | `api_server.py:2277` (buffer key `progress`; `write_progress` :2292) | `text` | `event/progress` (`ProgressUpdate`) |
| `reasoning` | `api_server.py:2277` (buffer) + `:2392` (`_emit_thinking_snapshot`) | `text`, optional `snapshot: true` | `event/reasoning_snapshot` (`ReasoningSnapshot`) |
| `plan` | `api_server.py:2318` (`write_plan`) | `steps` | `event/plan` (`PlanUpdate`) |
| `step` | `api_server.py:2322` (`write_step`) | `index`, `total`, `text` | `event/step` (`StepProgress`) |
| `tool_call` | `api_server.py:2332` (`write_tool_call`) | `name`, `args`, `message_id`, optional `timestamp` | `event/tool_begin` (`ToolBegin`; `call_id` <- `message_id`) |
| `tool_result` | `api_server.py:2359` (`write_tool_result`) | `result`, `status`, optional `message_id` | `event/tool_end` (`ToolEnd`) |
| `error` | `api_server.py:2313`, `:2567`, `:2591` | `message`, optional `message_id`, `run_id`, `status` | `event/error` (`ErrorNotification`) |
| `final` | `core/session.py:58` via `notification_to_sse_event` | `text`, `thinking`, `run_id`, token fields, `session_schema_version` | `event/final` (`FinalAnswer`) + `event/token_usage` (`TokenUsage`) |
| `done` | `api_server.py:2603` (stream teardown) | `run_id`, `status` | `event/done` (`RunComplete`) |

Legacy empty-message guard still emits inline JSON at `api_server.py:2422` (`error` + `done`).

### Bidirectional server requests (still SSE today)

| SSE `type` | Source | Payload fields | Protocol model |
|------------|--------|----------------|----------------|
| `approval_request` | `core/safety/approval.py:46` | `approval_id`, `tool`, `risk`, `args` | `approval/request` (`ApprovalRequest`) |
| `question_request` | `core/question.py:47` | `question_id`, `question`, `header`, `options[]`, `input_type` | `question/request` (`QuestionRequest`) |

HTTP replies today: `POST /approve` and `POST /question` in `api_server.py`.

### Not yet emitted on the wire

| Protocol model | Notes |
|----------------|-------|
| `TaskStarted`, `TaskComplete` | Reserved for LangGraph task boundaries (future Session emit) |
| `JobStatusUpdate` | Reserved for background job lifecycle (P4 appserver) |

## Commands

```powershell
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
python -m pytest tests/test_protocol_schema.py -q
python -m ruff check protocol
```

## Dependencies

- **Consumers (future)**: `appserver/`, `core/session.py`, `frontend/protocol-client`
- **Sources today**: `api_server.py` SSE, `core/safety/approval.py`, `core/question.py`