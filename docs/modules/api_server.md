# api_server.py - API Server

## What Is This Module?
FastAPI-based HTTP server that exposes the agent as a REST API. Used by the Ink TUI frontend and external integrations.

## Architecture
- FastAPI with SSE (Server-Sent Events) for streaming responses
- Binds to IPv4 loopback (`127.0.0.1`) on port 8765 by default
- Launched by main.py in a background thread (alongside Ink TUI)
- Can run standalone with: rxycode --api

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
| Endpoint | Method | Purpose |
|----------|--------|---------|
| /status | GET | Current status: model, mode, token stats, memory |
| /models | GET | Model nicknames and provider model IDs (never credentials) |
| /models/onboard | POST | Probe an unsaved model configuration, then persist it on success |
| /chat | POST | Non-streaming chat with the same run lifecycle and terminal classification |
| /chat/stream | POST | Send message, receive SSE stream of events |
| /command | POST | Execute slash commands (/help, /clear, etc.) |
| /approve | POST | Resolve a pending safety approval |
| /question/respond | POST | Resolve a correlated Agent question with a choice, text, or cancellation |
| /log | POST | Receive recursively redacted frontend diagnostics |
| /cancel | POST | Cancel the active chat or command lifecycle |

## Core: /chat/stream
- Accepts: {message, mode}
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

Only classified successful results emit `final`. Agent/build/tool failure
sentinels are emitted as `error` and counted under their real terminal status.
Tool events preserve their `message_id`; request/response events preserve their
approval or question ID so concurrent runs cannot update the wrong UI item.

## Core: /status
- Returns memory/billing/token data, application and provider cache metrics,
  mode/model/language, active run metadata, and aggregate terminal counts.

## Core: /command
- Accepts: {command}
- Returns: {action, message, ...}
- Handles: /help, /clear, /models, /cache, /list-chats, /thinking, /examples, etc.
- Credential-bearing `/addmodel ...` and legacy `/addmodel-step` command bodies
  are rejected. The frontend uses the typed onboarding endpoint instead.

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

## Token Stats Integration
- /status reads from the global token_stats singleton (streaming.py)
- /clear resets token_stats via token_stats.reset()
- Streaming responses trigger token recording via _record_usage()
