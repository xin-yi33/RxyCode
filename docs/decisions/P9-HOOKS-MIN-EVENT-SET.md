# P9 · hooks 最小事件集契约

日期：2026-10-08。本文件是 `core/lifecycle_contract.py` 里
`HOOK_EVENT_CONTRACT` 的人类可读版本。Phase A 先落本文件，Phase B 再落元组。
本卡不改 `core/hooks.py`（`HookPhase` 仍是 before/after/error，默认超时 5s，
超时记 `TIMED_OUT` 并继续后面的 hook）。不新增可阻断的 PreToolUse，
不新增 `LifecycleEvent`，不新增 `core/lifecycle/events.py`。

hook 只观测。返回值不覆盖、不阻断决策。`HookRegistry.emit` 不按 subject 过滤：
同一 phase 上已注册的回调都会跑。因此本卡不把 AgentV2 的共享 registry
塞进决策引擎，避免 `rag_code_change_refresh` 这类既有 after-hook 在每次
超时决策上再跑一遍。调用方要观测时，把专用 registry 传给
`TimeoutDecisionEngine(..., hooks=)` 或 `from_config(..., hooks=)`。

## 八个契约对

顺序即契约。与 `HOOK_EVENT_CONTRACT` 逐项相同。

| # | phase | subject | 别名 | 载荷 | 发射点 |
|---|---|---|---|---|---|
| 1 | before | tool | PreToolUse | 见下表「tool」 | 本卡未按该 subject 新发射。现状最近发射是 `tool_call`，见下 |
| 2 | after | tool | PostToolUse | 见下表「tool」 | 同上 |
| 3 | before | compact | PreCompact | 见下表「compact」 | 本卡未发射。仓库没有 subject=`compact` 的 `HookRegistry.emit` |
| 4 | after | compact | PostCompact | 见下表「compact」 | 同上 |
| 5 | after | stop | Stop | 见下表「stop」 | 本卡未发射。仓库没有 subject=`stop` 的 `HookRegistry.emit` |
| 6 | after | session_start | SessionStart | 见下表「session」 | 本卡未发射。仓库没有 subject=`session_start` 的 `HookRegistry.emit` |
| 7 | after | session_end | SessionEnd | 见下表「session」 | 本卡未发射。仓库没有 subject=`session_end` 的 `HookRegistry.emit` |
| 8 | before | timeout_decision | PreTimeoutDecision | `{"evidence": evidence.model_dump()}` | `core/timeout_decision.py:383` 调用 `_emit_hook("before", evidence)`；`_emit_hook` 在 `:476-483`，`hooks.emit` 在 `:479-482`。发生在 `_await_model`（`:391`）之前 |

`("after", "timeout_decision")` 不在这 8 对里。决策落定后仍会
`await _emit_hook("after", evidence)`（`core/timeout_decision.py` 的各 return
之前，成功路径在 `:423`）。载荷同样是 `{"evidence": evidence.model_dump()}`。
这是观测，不是第 9 个契约名。`hooks is None` 时 `_emit_hook` 直接返回，
决策行为不变。

## 载荷

观察用。缺字段不得让 hook 抛错去阻断后续 hook 或决策；超时与异常由
`HookRegistry.emit` 记成 `timed_out` / `failed` 后继续。

| subject | 载荷 |
|---|---|
| tool | `tool`（工具名）、`call_id`、`mode`（before）；after 再加 `status`。现状实际 subject 是 `tool_call` |
| compact | `session_id`、`run_id`、`reason`。本卡没有发射点 |
| stop | `session_id`、`run_id`、`status`。本卡没有发射点 |
| session_start / session_end | `session_id`。本卡没有发射点 |
| timeout_decision | `evidence`：`TimeoutEvidence.model_dump()` 的全部字段（`trigger_point`、`session_id`、`run_id`、`subject_id`、`task_hint`、`elapsed_seconds`、`budget_seconds`、`extension_index`、`progress`、`last_error`） |

## 现状最近发射（subject 与契约名不同，本卡不改）

改 subject 会让「只按 phase 注册」的既有 hook 含义变化，也可能和仍在用的
旧 subject 双发。本卡只登记契约名。

| 现状调用 | 文件:行 | 实际 subject |
|---|---|---|
| `hooks.emit(phase, "tool_call", payload)` | `execution/tool_orchestrator.py:355`；before `:1072`，error `:1223` 与 `:1251`，after `:1281` | `tool_call` |
| `hooks.emit(phase, subject, payload)` | `core/graph.py:291`；节点 before `:405` subject `graph_node`；任务 before `:779` / after `:800` subject `task` | 调用方传入 |
| `hooks.emit(phase, "agent_run", payload)` | `core/agent_v2.py:7853`；before `:7929`，after `:8108` | `agent_run` |
| `hooks.emit(phase, "timeout_decision", {"evidence": evidence.model_dump()})` | `core/timeout_decision.py:479` | `timeout_decision` |

## 超时

`HookRegistry` 默认 5 秒。单个 hook 超时记 `HookStatus.TIMED_OUT`（值
`timed_out`），不取消决策，不跳过同一 phase 里排在后面的 hook。
本卡不改这段语义。
