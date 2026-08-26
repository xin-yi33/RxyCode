# api_server.py - API Server (HTTP/SSE adapter)

## What Is This Module?

FastAPI-based HTTP server that exposes the agent as a REST API. Currently the
full HTTP+SSE backend for the Ink TUI frontend and external integrations; in
the Phase 2 target architecture it is the **HTTP/SSE adapter** standing next
to `appserver/` (stdio JSON-RPC) as one of two transports over the same
headless core and the same typed `protocol/` schema.

## Architecture

- FastAPI with SSE (Server-Sent Events) for streaming responses
- Binds to IPv4 loopback (`127.0.0.1`) on port 8765 by default
- Launched by main.py in a background thread (alongside the Ink TUI); can run
  standalone with `rxycode --api`. Initialization keeps the process cwd so file
  tools write into the caller's project, not the installed package tree.
- Requests enter the agent through the headless `Session` facade
  (`core/session.py`) rather than calling `AgentV2` directly
- File size: 2,029 lines. Docstring:
  "RxyCode API Server - FastAPI backend for the Ink TUI"

### Module structure (post-thinning)

The module was thinned by pure code relocation (behavior unchanged) into three
files:

| File | Lines | Responsibility |
|---|---|---|
| `api_server.py` | 2,029 | FastAPI route assembly layer (HTTP/SSE adapter): 8 `@app.` routes, request models, startup/auth; mounts `models_router` via `app.include_router` (api_server.py:71) |
| `api_server_models.py` | 355 | Model-management endpoints (`/models`, `/models/presets`, `/models/discover`, `/models/onboard`, `/models/onboard/batch`) on an `APIRouter` (`models_router`), plus their request models |
| `api_server_stream.py` | 451 | SSE transport classes: `APIProxyTUI` (11), `StreamSessionRecorder` (125), `StreamTUI` (271) |

## Phase 2 Adapter Positioning

### Current role

api_server.py is today a **complete HTTP+SSE server**: 13 routes (8 `@app.` in
api_server.py, 5 `@router.` on `models_router` in api_server_models.py) covering
`/chat`, `/chat/stream`, `/status`, `/command`, `/approve`,
`/question/respond`, `/models/*`, `/cancel`, `/log`, and the Ink fallback
frontend still uses it (AGENTS.md; OpenTUI migrated to `appserver` stdio in
P5). It is not yet a thin adapter: it owns route assembly and request parsing,
slash-command execution, and run lifecycle management, while the SSE transport
classes live in `api_server_stream.py` and the model onboarding endpoints in
`api_server_models.py`.

### Evolution direction

Per the Phase 2 execution plan (local design notes, not in this tree),
api_server.py evolves into a **HTTP adapter over the headless core**:

- The core becomes headless: `core/session.py` `Session` (`class Session`,
  core/session.py:94) is the facade through which any transport drives
  `AgentV2`; it has no I/O of its own.
- The wire contract is shared and typed in `protocol/` (versioned pydantic
  models: requests, notifications, server requests; see docs/modules/protocol.md).
- `appserver/` is the stdio JSON-RPC transport implementation of that protocol.
- `api_server.py` is the HTTP+SSE transport implementation of the *same*
  protocol: one contract, two transports (stdio vs HTTP+SSE).

This direction is already realized: **both** `/chat/stream` and `/chat` route
through `Session` — `from .core.session import Session, notification_to_sse_event`
(api_server.py:1862), an `_emit_protocol` callback that converts protocol
notifications to SSE events (1864), a `Session(...)` built with
`emit=_emit_protocol` (1869-1872), and `session.prompt(agent, ...)` (1876).
`/chat` (non-streaming) constructs the same `Session` at 816-821.
`/cancel` similarly uses `Session.interrupt` (1670). Run lifecycle is wrapped by
`_api_run_lifecycle` (api_server.py:1919).

### Backward-compatibility hard constraint

The existing HTTP interface must not break. Key Phase 2 constraint
(00-EXECUTION-PLAN.md:1813): *"api_server.py 的现有 HTTP 接口必须保持向后兼容，
OpenTUI 在 P5 之前一直用它"* — OpenTUI depended on these endpoints until P5,
and external integrations may still. Any adapter refactor must preserve the
current endpoint surface, payloads, SSE event names, and status semantics.

### Relationship with appserver/protocol

`api_server.py` and `appserver/` speak the same protocol with different
transports. `appserver/` emits typed protocol notifications to a client over
stdout JSON-RPC (via `ProtocolTui`); `api_server.py` maps the same underlying
event stream to SSE frames. The mapping is centralized in
`notification_to_sse_event` (core/session.py:57), which converts terminal
protocol notifications (`FinalAnswer`, `ErrorNotification`) into SSE events;
the legacy `StreamTUI` writers emit the remaining events directly.

| SSE event (api_server.py) | Protocol model | Legacy source |
|---|---|---|
| `token` | `MessageDelta` | buffer key `token` (api_server_stream.py:409), `flush_stream_buffers` (306) |
| `progress` | `ProgressUpdate` | `write_progress` (api_server_stream.py:327) |
| `reasoning` | `ReasoningSnapshot` | `_emit_thinking_snapshot` (420), `_put` (299) |
| `plan` | `PlanUpdate` | `write_plan` (349), `_put` (299) |
| `step` | `StepProgress` | `write_step` (354), `_put` (299) |
| `tool_call` | `ToolBegin` | `write_tool_call` (358) |
| `tool_result` | `ToolEnd` | `write_tool_result` (385) |
| `error` | `ErrorNotification` | `write_error` (345/81), runner queue puts (1888/1912) |
| `final` | `FinalAnswer` + `TokenUsage` | `notification_to_sse_event` (core/session.py:57) |
| `done` | `RunComplete` | queue put (1924) |
| `approval_request` / `question_request` | `ApprovalRequest` / `QuestionRequest` | core/safety/approval.py:46, core/question.py:47 |

The `approval_request`/`question_request` events are answered in-band via
`POST /approve` (656) and `POST /question/respond` (669) — the HTTP analogue
of the protocol's `server_requests` channel. The full SSE inventory and
protocol model reference is in docs/modules/protocol.md.

## Local API Security

- Local/embedded launches use a new high-entropy bearer token. A remote opt-in
  uses the explicitly configured strong token instead of rotating it away.
- `main.py` passes the token directly to the child Ink process through
  `RXYCODE_API_TOKEN`; it is never put in the URL or application logs.
- Every HTTP request requires `Authorization: Bearer <token>` except CORS `OPTIONS` preflight.
- Read-only endpoints such as `/status` and `/models` are authenticated because they expose runtime, usage, and model configuration metadata.
- Requests whose socket peer is not loopback are rejected unless remote access
  was explicitly enabled before the socket was opened.
- A non-loopback bind is available only as an explicit deployment opt-in:
  `RXYCODE_ALLOW_REMOTE_API=1` plus a preconfigured high-entropy
  `RXYCODE_API_TOKEN` (32+ characters). Missing, short, or example credentials
  abort startup before Uvicorn binds the port.
- Remote access also requires `RXYCODE_TLS_CERTFILE` and
  `RXYCODE_TLS_KEYFILE` (plus optional `RXYCODE_TLS_KEYFILE_PASSWORD`). Uvicorn
  serves HTTPS; plaintext remote bearer transport is refused at startup.
- Frontend logs are recursively redacted for authorization, API-key, token,
  password, and secret fields before they reach the logger.

## Endpoints

8 `@app.` routes live in api_server.py; the 5 `/models/*` routes are registered
on `models_router` in api_server_models.py and mounted via
`app.include_router` (api_server.py:71). All 13 routes are listed below.

| Endpoint | Method | Line | Purpose |
|----------|--------|------|---------|
| /status | GET | 715 | Current status: model, mode, memory, billing, cache, token stats |
| /models | GET | 115 | Model nicknames and provider model IDs (never credentials) |
| /models/presets | GET | 187 | Connection presets (provider + base URL only, no model IDs) |
| /models/discover | POST | 199 | Probe a provider's model catalogue with supplied credentials; never persists |
| /models/onboard | POST | 226 | Probe an unsaved model configuration, then persist it on success |
| /models/onboard/batch | POST | 328 | Add multiple discovered models without per-model chat probes |
| /chat | POST | 770 | Non-streaming chat through the same `Session` facade and run lifecycle |
| /chat/stream | POST | 1750 | Send message, receive SSE stream of events |
| /cancel | POST | 1670 | Cancel the active chat or command lifecycle (via `Session.interrupt`) |
| /command | POST | 1699 | Execute slash commands (/help, /clear, etc.) |
| /approve | POST | 656 | Resolve a pending safety approval |
| /question/respond | POST | 669 | Resolve a correlated Agent question with a choice, text, or cancellation |
| /log | POST | 698 | Receive recursively redacted frontend diagnostics |

*Line numbers for the `/models/*` rows refer to api_server_models.py; all other rows refer to api_server.py.*

## Core: /chat/stream

- Accepts: {message, mode, session_id?}
- Returns: SSE stream with event types:
  - progress: Thinking progress
  - reasoning: Current-turn model reasoning
  - plan / step: Plan and execution progress
  - token: Streaming text
  - tool_call: Tool started
  - tool_result: Tool completed
  - approval_request: Correlated safety decision request
  - question_request: Correlated choice/free-text question
  - final: Final response
  - error: Non-success result, with `failed`, `timed_out`, or `cancelled` status
  - done: Stream complete, carrying the terminal run status

The runner drives the agent through `Session` (api_server.py:1869-1876):
protocol notifications are converted to SSE via `_emit_protocol` /
`notification_to_sse_event`; terminal status comes from `session.prompt`.
`_api_run_lifecycle` (1919) wraps each run with the run lifecycle.

Only classified successful results emit `final`. Agent/build/tool failure
sentinels are emitted as `error` and counted under their real terminal status.
Tool events preserve their `message_id`; request/response events preserve their
approval or question ID so concurrent runs cannot update the wrong UI item.
Legacy guards still inline SSE JSON: the empty-message guard (1760), invalid
mode (1765-1770), and busy-stream guard (1776-1780) each emit `error` + `done`
directly.

## Core: /status

- Returns memory/billing/token data, application and provider cache metrics,
  mode/model/language, active run metadata, and aggregate terminal counts.
- Source: global `token_stats` singleton (`utils/streaming.py`), imported at
  api_server.py:717.

## Core: /command

- Accepts: {command}
- Returns: {action, message, ...}
- Handles: /help, /clear, /models, /cache, /list-chats, /thinking, /examples, etc.
- Credential-bearing `/addmodel ...` and legacy `/addmodel-step` command bodies
  are rejected. The frontend uses the typed onboarding endpoint instead.
- `/clear` resets token stats via `token_stats.reset()` (939).

## Core: /models/onboard

- Accepts `{provider_model_id, nickname?, api_key, base_url}`. The Pydantic
  request type stores `api_key` as `SecretStr` so representations are masked.
- `base_url` must be HTTPS before any network client is opened; credentials are
  never sent to a plaintext provider URL.
- Probes the supplied in-memory configuration before any config write. A failed
  probe leaves model configuration unchanged.
- On success, `nickname` is the local model/config ID and
  `provider_model_id` is the exact model value sent to the upstream provider.
- Successful credentials are stored through an opaque reference: Windows uses
  current-user DPAPI; other platforms use an owner-only secret file. YAML never
  stores the provider key inline, and legacy inline values are migrated.
- `/models/presets` (api_server_models.py:158) returns connection presets
  (provider + base URL only) so the TUI can drive the add-model flow;
  `/models/discover` (170) lists a provider's models with the supplied
  credential and never persists; `/models/onboard/batch` (278) persists several
  discovered models at once (with optional `skip_probe`).

## Token Stats Integration

- /status reads from the global token_stats singleton (streaming.py)
- /clear (via /command) resets token_stats via `token_stats.reset()` (939)
- Token usage is recorded inside AgentV2's `_record_usage`
  (core/agent_v2.py:302); the singleton is what /status reports

## Commands

```powershell
rxycode --api            # standalone HTTP+SSE server (port 8765 by default)
python api_server.py     # equivalent direct entry (__main__ -> run_api_server)
```

Startup refuses non-loopback binds without `RXYCODE_ALLOW_REMOTE_API=1`; remote
mode additionally requires TLS cert/key files (see Local API Security).

**斜杠命令扩展（2026-08-12）**：`/command` 新增 `/effort [档位]`——设置/查询全局思考强度档位（无参数 = 查询，返回 `effort_info`；设置成功返回 `effort_changed` 并即时写入当前 agent 的 `model_config.effort`）；`/status` 返回 `effort` 字段；`GET /models`（api_server_models.py）返回每模型的 `effort_options` 与全局 `effort`。

## Dependencies

- **Consumers**: Ink TUI fallback frontend (AGENTS.md), external integrations
- **Core integration**: `core/session.py` (`Session`, `notification_to_sse_event`),
  `core/agent_v2.py` (`AgentV2`, `_record_usage`), `core/safety/approval.py`,
  `core/question.py`, `core/tracing.py`
- **Protocol**: `protocol/` typed schema shared with `appserver/`
  (docs/modules/protocol.md)
- **Config**: `config/model_manager.py` (presets, discovery, onboarding)
- **Runtime**: FastAPI + Uvicorn, SSE, `utils/streaming.py` (token_stats),
  `utils/tui.py`, `log/monitor.py`
