# appserver/

Stdio JSON-RPC transport for the headless RxyCode core (Phase 2 P4).

## Purpose

`python -m appserver` is the canonical backend entry for OpenTUI/Desktop stdio
clients. It reads newline-delimited JSON-RPC from **stdin**, writes protocol
messages to **stdout**, and sends all logs to **stderr** only.

## Layout

| File | Role |
|------|------|
| `__init__.py` | Package marker |
| `__main__.py` | CLI entry (`python -m appserver`) |
| `server.py` | `AppServer` dispatch loop, watchdog heartbeat, session handlers |
| `agent_host.py` | Parent-side client for one killable worker subprocess per session (T1) |
| `agent_worker.py` | Isolated subprocess: bootstrap + `Session.prompt` (T1); async stdout via `write_message` (T3) |
| `watchdog.py` | Stall detection + degraded mode (T4) |
| `jsonrpc.py` | Read/write helpers; `write_message` offloads sync stdout to a thread (T3) |
| `live_env.py` | Builds the live integration-test env (`build_live_appserver_env`) from real user config for `RXYCODE_APPSERVER_LIVE=1` |
| `approval.py` | `JsonRpcApproval` broker (bidirectional `approval/request`) |
| `runtime.py` | Per-prompt context vars for concurrent session isolation |
| `tui.py` | `ProtocolTui` maps AgentV2 TUI calls to protocol notifications |
| `sessions.py` | Multi-session registry |
| `bootstrap.py` | AgentV2 initialization (or stub in tests); `workspace_root` chdir |
| `stub.py` | Deterministic agent when `RXYCODE_APPSERVER_STUB=1` |
| `emitter.py` | pydantic notification -> JSON-RPC notification |

## Request flow

```
Client stdin  -> AppServer._dispatch()
              -> AgentHost (subprocess per session, T1)
              -> agent_worker: bootstrap_agent(workspace_root) + Session.prompt()
              -> AgentV2.run()
              -> ProtocolTui.emit() -> stdout JSON-RPC notifications
Approval      -> worker _PipeApproval -> AgentHost -> JsonRpcApproval -> client
Watchdog (T4) -> periodic event/server_heartbeat; stall -> kill worker + degraded
```

Each session gets its own **agent worker subprocess**. Prompt/bootstrap timeouts call
`AgentHost.kill()` so blocked work cannot hold the main process (T1).

## Phase 2 hard constraints (P4)

| ID | Requirement | Implementation |
|----|-------------|----------------|
| T1 | Process isolation per session | `AgentHost` spawns `agent_worker` subprocess; `kill()` on timeout/shutdown |
| T2 | Explicit timeouts | Bootstrap, prompt, approval, and worker RPC each have wall-clock limits |
| T3 | Non-blocking stdio on asyncio loops | `jsonrpc.write_message` uses `asyncio.to_thread(write_message_sync, …)`. `server.py` handlers `await write_message`. `agent_worker.py` async paths `await write_message`; sync `emit` callbacks use `_schedule_write()` → `create_task(write_message(…))` so neither loop blocks on `sys.stdout` |
| T4 | Watchdog / degrade | `watchdog.py`: heartbeat, stall detection, `-32004`, failed-job events, worker kill |

## Methods (client -> server)

| method | maps to |
|--------|---------|
| `initialize` | handshake |
| `session/new` | create workspace-bound session (`workspace_root` passed to worker) |
| `session/prompt` | one user turn via worker `Session` (supports `timeout_seconds`) |
| `session/interrupt` | worker `Session.interrupt` |
| `shutdown` | graceful exit (cancels heartbeat, kills workers) |

When the watchdog marks the server **degraded**, new `session/prompt` calls return
`-32004` until restart.

## Test hooks

| Env | Effect |
|-----|--------|
| `RXYCODE_APPSERVER_STUB=1` | Use `StubAgent` (no LLM); `trigger-approval` exercises approval; `slow:`/`hang:`/`fail:` prefixes for concurrency/timeout/failure tests |
| `RXYCODE_APPSERVER_BOOTSTRAP_DELAY` | Seconds to sleep in `bootstrap_agent` (stub integration tests for bootstrap timeout) |
| `RXYCODE_APPSERVER_HEARTBEAT_SECONDS` | Interval for `event/server_heartbeat` (default `15`) |
| `RXYCODE_APPSERVER_STALL_SECONDS` | Job stall threshold before degrade + worker kill (default `120`) |
| `RXYCODE_APPSERVER_LIVE=1` | Run live AgentV2 integration test; uses real `~/.RxyCode/config.yaml`, not pytest-isolated data dir |
| `RXYCODE_APPSERVER_LIVE_TIMEOUT` | Live prompt/run timeout in seconds (default `300`) |

`session/prompt` `timeout_seconds` covers **worker bootstrap and prompt execution** (single
wall-clock budget). On timeout the worker process is killed.

CI runs StubAgent tests only; set `RXYCODE_APPSERVER_LIVE=1` locally to exercise real AgentV2.

## Commands

```powershell
python -m appserver
python -m pytest tests/test_appserver -q
python -m ruff check appserver
```

## Dependencies

- **Uses**: `core/session.py`, `core/safety/approval.py`, `protocol/*`
- **Consumers**: OpenTUI stdio transport (P5), Desktop shell (Phase 3)
