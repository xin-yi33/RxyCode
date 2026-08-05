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
  standalone with `rxycode --api`
- Requests enter the agent through the headless `Session` facade
  (`core/session.py`) rather than calling `AgentV2` directly
- File size: 2,726 lines of code (2,412 non-blank). Docstring:
  "RxyCode API Server - FastAPI backend for the Ink TUI"

## Phase 2 Adapter Positioning

### Current role

api_server.py is today a **complete HTTP+SSE server**: 13 `@app.` routes
(`/chat`, `/chat/stream`, `/status`, `/command`, `/approve`,
`/question/respond`, `/models/*`, `/cancel`, `/log`), and the Ink fallback
frontend still uses it (AGENTS.md; OpenTUI migrated to `appserver` stdio in
P5). It is not yet a thin adapter: it owns request parsing, the SSE stream,
slash-command execution, model onboarding, and run lifecycle management.

### Evolution direction

Per the Phase 2 development doc (docs/plans/opus5-plan/rxycode/00-EXECUTION-PLAN.md,
§6), api_server.py evolves into a **HTTP adapter over the headless core**:

- The core becomes headless: `core/session.py` `Session` (`class Session`,
  core/session.py:94) is the facade through which any transport drives
  `AgentV2`; it has no I/O of its own.
- The wire contract is shared and typed in `protocol/` (versioned pydantic
  models: requests, notifications, server requests; see docs/modules/protocol.md).
- `appserver/` is the stdio JSON-RPC transport implementation of that protocol.
- `api_server.py` is the HTTP+SSE transport implementation of the *same*
  protocol: one contract, two transports (stdio vs HTTP+SSE).

This direction is already partially realized: `/chat/stream` routes through
`Session` — `from .core.session import Session, notification_to_sse_event`
(api_server.py:2559), an `_emit_protocol` callback that converts protocol
notifications to SSE events (2561), a `Session(...)` built with
`emit=_emit_protocol` (2566-2571), and `session.prompt(agent, ...)` (2573).
`/cancel` similarly uses `Session.interrupt` (2062-2069).

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
| `token` | `MessageDelta` | buffer key `token` (2297), `flush_stream_buffers` (2307) |
| `progress` | `ProgressUpdate` | `write_progress` (2328) |
| `reasoning` | `ReasoningSnapshot` | `_emit_thinking_snapshot` (2421), `_put` (2428) |
| `plan` | `PlanUpdate` | `write_plan` (2350), `_put` (2354) |
| `step` | `StepProgress` | `write_step` (2355), `_put` (2358) |
| `tool_call` | `ToolBegin` | `write_tool_call` (2359) |
| `tool_result` | `ToolEnd` | `write_tool_result` (2386) |
| `error` | `ErrorNotification` | `write_error` (2346/2349), queue puts (2603/2627) |
| `final` | `FinalAnswer` + `TokenUsage` | `notification_to_sse_event` (core/session.py:57) |
| `done` | `RunComplete` | queue put (2639) |
| `approval_request` / `question_request` | `ApprovalRequest` / `QuestionRequest` | core/safety/approval.py:46, core/question.py:47 |

The `approval_request`/`question_request` events are answered in-band via
`POST /approve` (859) and `POST /question/respond` (872) — the HTTP analogue
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

| Endpoint | Method | Line | Purpose |
|----------|--------|------|---------|
| /status | GET | 918 | Current status: model, mode, memory, billing, cache, token stats |
| /models | GET | 973 | Model nicknames and provider model IDs (never credentials) |
| /models/presets | GET | 1016 | Connection presets (provider + base URL only, no model IDs) |
| /models/discover | POST | 1028 | Probe a provider's model catalogue with supplied credentials; never persists |
| /models/onboard | POST | 1055 | Probe an unsaved model configuration, then persist it on success |
| /models/onboard/batch | POST | 1136 | Add multiple discovered models without per-model chat probes |
| /chat | POST | 1166 | Non-streaming chat with the same run lifecycle and terminal classification |
| /chat/stream | POST | 2447 | Send message, receive SSE stream of events |
| /cancel | POST | 2048 | Cancel the active chat or command lifecycle (via `Session.interrupt`) |
| /command | POST | 2077 | Execute slash commands (/help, /clear, etc.) |
| /approve | POST | 859 | Resolve a pending safety approval |
| /question/respond | POST | 872 | Resolve a correlated Agent question with a choice, text, or cancellation |
| /log | POST | 901 | Receive recursively redacted frontend diagnostics |

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

The runner drives the agent through `Session` (api_server.py:2559-2578):
protocol notifications are converted to SSE via `_emit_protocol` /
`notification_to_sse_event`; terminal status comes from `session.prompt`.

Only classified successful results emit `final`. Agent/build/tool failure
sentinels are emitted as `error` and counted under their real terminal status.
Tool events preserve their `message_id`; request/response events preserve their
approval or question ID so concurrent runs cannot update the wrong UI item.
Legacy guards still inline SSE JSON: the empty-message guard (2458), invalid
mode (2463-2467), and busy-stream guard (2473-2477) each emit `error` + `done`
directly.

## Core: /status

- Returns memory/billing/token data, application and provider cache metrics,
  mode/model/language, active run metadata, and aggregate terminal counts.
- Source: global `token_stats` singleton (`utils/streaming.py`), imported at
  api_server.py:920.

## Core: /command

- Accepts: {command}
- Returns: {action, message, ...}
- Handles: /help, /clear, /models, /cache, /list-chats, /thinking, /examples, etc.
- Credential-bearing `/addmodel ...` and legacy `/addmodel-step` command bodies
  are rejected. The frontend uses the typed onboarding endpoint instead.
- `/clear` resets token stats via `token_stats.reset()` (1335).

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
- `/models/presets` (1016) returns connection presets (provider + base URL
  only) so the TUI can drive the add-model flow; `/models/discover` (1028)
  lists a provider's models with the supplied credential and never persists;
  `/models/onboard/batch` (1136) persists several discovered models at once
  (with optional `skip_probe`).

## Token Stats Integration

- /status reads from the global token_stats singleton (streaming.py)
- /clear (via /command) resets token_stats via `token_stats.reset()` (1335)
- Token usage is recorded inside AgentV2's `_record_usage`
  (core/agent_v2.py:302); the singleton is what /status reports

## Commands

```powershell
rxycode --api            # standalone HTTP+SSE server (port 8765 by default)
python api_server.py     # equivalent direct entry (__main__ -> run_api_server)
```

Startup refuses non-loopback binds without `RXYCODE_ALLOW_REMOTE_API=1`; remote
mode additionally requires TLS cert/key files (see Local API Security).

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
