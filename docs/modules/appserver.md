# appserver/

Stdio JSON-RPC transport for the headless RxyCode core (Phase 2 P4).

## Purpose

`python -m appserver` is the canonical backend entry for OpenTUI/Desktop stdio
clients. It reads newline-delimited JSON-RPC from **stdin**, writes protocol
messages to **stdout**, and sends all logs to **stderr** only.

## Layout

| File | Role |
|------|------|
| `__init__.py` | Package marker；把当前 checkout 绑到 `RxyCode.RxyCode1_1_0`，并调用 `unify_bare_package_aliases()`（覆盖已导入的短名 `core`，不只 `setdefault`） |
| `__main__.py` | CLI entry (`python -m appserver`) |
| `server.py` | `AppServer` dispatch loop, watchdog heartbeat, session handlers |
| `agent_host.py` | Parent-side client for one killable worker subprocess per session (T1) |
| `agent_worker.py` | Isolated subprocess: bootstrap + `Session.prompt` (T1); async stdout via `write_message` (T3) |
| `watchdog.py` | Stall detection + degraded mode (T4) |
| `jsonrpc.py` | Read/write helpers; `write_message` offloads sync stdout to a thread (T3) |
| `live_env.py` | Builds the live integration-test env (`build_live_appserver_env`) from real user config for `RXYCODE_APPSERVER_LIVE=1` |
| `approval.py` | `JsonRpcApproval` broker (bidirectional `approval/request`) |
| `question.py` | `PipeQuestionBroker` (bidirectional `question/request`) |
| `runtime.py` | Per-prompt context vars for concurrent session isolation |
| `tui.py` | `ProtocolTui` maps AgentV2 TUI calls to protocol notifications |
| `runtime.py` | Per-prompt asyncio context（session/TUI 绑定）+ **委托深度追踪**（2026-09-23 P0） |

**2026-09-23（P0 answer-last）**：`MessageDelta` / `ProgressUpdate` / `ReasoningSnapshot`
新增 `intermediate` 字段。子代理执行期间（`bind_delegate_depth` 深度 ≥1）
`ProtocolTui` 的流式输出打标 `intermediate=True`；前端 streamReducer 据此把
中间输出挡在主聊流外，保证「最终答复是本轮最后一个面向用户的事件」。
契约测试：`tests/test_appserver/test_answer_last_contract.py`。
| `sessions.py` | Multi-session registry。首轮 `session/prompt` 写 `last_user_prompt` + fallback 标题；`sessions/list` 隐藏无用户对话的空窗口 |
| `schedule_service.py` | OpenTUI `/loop` 磁盘作业 + `restore_after_restart`（UPDATE-01 U66）。boot 把 `running` 标 `recovery_required`，不复活被杀 bash |
| `task_store.py` | Desktop/OpenTUI 会话目录 `tasks.json`。catalog 可带 `last_user_prompt` 供标题回填；transcript 是 `session/events`（tool_begin/end、`event/final` 的 thinking+text），不是 compact 摘要当 UI |
| `bootstrap.py` | AgentV2 initialization (or stub in tests); `workspace_root` chdir |
| `stub.py` | Deterministic agent when `RXYCODE_APPSERVER_STUB=1` |
| `emitter.py` | pydantic notification -> JSON-RPC notification |
| `subagent_routes.py` | Subagent JSON-RPC methods (`agent/invoke`, `task/start`, `subagents/list`, `subagents/capability`) |

## Request flow

```
Client stdin  -> AppServer._dispatch()
              -> AgentHost (subprocess per session, T1)
              -> agent_worker: bootstrap_agent(workspace_root) + Session.prompt()
              -> AgentV2.run()
              -> ProtocolTui.emit() -> stdout JSON-RPC notifications
Approval      -> worker _PipeApproval -> AgentHost -> client `approval/request`
Question      -> worker PipeQuestionBroker -> AgentHost -> client `question/request`
Watchdog (T4) -> periodic event/server_heartbeat; stall -> kill worker + degraded
```

Each session gets its own **agent worker subprocess**. Prompt/bootstrap timeouts call
`AgentHost.kill()` so blocked work cannot hold the main process (T1).
Background `session/new` warm uses a 180s budget and **single-flight**
bootstrap: a timed-out waiter does not start a second AgentV2 constructor.
`session/set_model` joins that same in-flight warm (also 180s) instead of
aborting at 30s, which previously left Desktop stuck on
`Starting Agent worker…`. After bootstrap the GUI receives
`Waiting for model response…` so the startup banner cannot linger over
later tool activity.

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
| `session/new` | create workspace-bound session (`workspace_root` passed to worker). OpenTUI `/session` **catalog** is `sessions/list` of these records（UPDATE-01 轨 H），不是 `memory/chat_storage` |
| `sessions/list` | list persisted sessions（additive 行字段：`display_title` / `age_label` / `date_group` / `title_is_manual`）。无用户消息的空 `session/new` 窗口不出现 |
| `session/prompt` | one user turn via worker `Session` (supports `timeout_seconds`)。首轮立刻 fallback 占位；隐藏 LLM 取名；第三轮用三轮对话再总结。命名过程不进 transcript |
| `session/interrupt` | worker `Session.interrupt` |
| `session/set_thinking_expanded` | toggle expanded thinking rendering |
| `session/warm` | bootstrap the worker **and** wait for thinking-on prefix prewarm |
| `agent/invoke` | user `@agent` mention dispatch (server.py:536-552) |
| `task/start` | explicit subagent task dispatch |
| `subagents/list` | list registered agent definitions |
| `subagents/capability` | subagent feature flags + capability report |
| `shutdown` | graceful exit (cancels heartbeat, kills workers) |
| `models/list` | configured models; `warning` includes a missing-credential note when the resolved API key is empty. The raw key is never returned |
| `plugin/install` | `local` / `registry` / `url` / `github`; optional raw `token` for GitHub PAT (not in `schema.json`). Hub clicks count as approval only under `ask_for_each_risky_action`; `read_only` still denies writes |
| `plugin/toggle` | enable or disable an installed plugin |
| `plugin/uninstall` | remove a plugin package |

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

- **Uses**: `core/session.py`, `core/safety/approval.py`, `protocol/*` (incl. `protocol/subagents.py`), `core/subagents/` (via subagent routes)
- **Consumers**: OpenTUI stdio transport (P5), Desktop shell (Phase 3)
