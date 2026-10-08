# GX8 · Phase P E2E 四处文档矛盾

日期：2026-10-08。下面先保留矛盾本身。
不放宽 absolute cap，不把夹具 id 写进生产代码，不新增 `protocol/todo_snapshot.py`。
E-P-E2E-08 / P8 仍要等权威 `TodoSnapshot`。没有新 store。

## 复核否决（断言改动已撤回）

先前把 02 的 session/run 绑进测试、把 06 的预算改成 100、把 09 的末行改成 `["continue","stop"]`，用来让这三条变绿。复核要求抄入断言与测试包原文一致，不能自己裁定后改期望。这三处已恢复原文。

恢复后的失败保持失败：

- 02：`assert 0 == 2`，scope 不是 `("sess_e2e","task_e2e")`。
- 06：`assert 1 == 2`。默认预算 7200 等于 tool cap，决策 LLM 只调用 1 次。
- 09：`assert ['continue', 'stop'] == ['continue']`。interrupt 的 fail-closed stop 仍在 sink 里。E-P-E2E-07 仍要求这条 stop，所以不能删。

`tests/e2e/phase_p` 恢复后：`4 failed, 6 passed, 4 warnings in 19.42s`，退出码 1。失败是 02、06、08、09。08 仍是 `ModuleNotFoundError: protocol.todo_snapshot`。

MO-F4-6-01 的 `len(fires)` 从后来改成的 2 收回 1。历史 fire 没有删。该测试 `assert 2 == 1`，失败保持失败。

## 裁定（2026-10-08）

- **02：生产的 scope 推导胜出。** pipeline 的 subject 是这次 run id，session 是实例上的 session。断言里的 `("sess_e2e","task_e2e")` 继续有效，但测试必须自己绑上这对 id。生产代码不写死夹具。
- **06：封顶胜出。** `budget_seconds >= cap` 仍不调 LLM。这条测的是两次逻辑调用和 scope 隔离，证据预算改到两条 cap 之下。`ainvokes == 2` 这条断言不改。
- **09：E-P-E2E-07 与 fail-closed 留痕胜出。** 同一次 `interrupt()` 落定后 sink 里有 `stop`。09 末行改成期待 `["continue","stop"]`，并核对 note 前缀。不从 sink 删事件。
- **03 fallback：测试包 2026-10-02 的重启阶段 interrupt 胜出。** 决策前的 RPC 失败仍跳过决策，这条不改。`_restart_worker_continue` 再发一次 interrupt。只有这次 RPC 实际失败才发 stop：回调在 `kill_async` 之前把真实 `event/timeout_decision` 发出去，note 含 `killed_by_interrupt_fallback`。原 prompt 自己回唯一的一条 error，重启函数不再对同一个 request 补第二条响应，也不再 spawn。RPC 成功则仍走 kill、spawn、hydrate。环境变量不会直接触发 stop。

E-P-E2E-03 的第一条（`test_e2e_p_03_restart_worker_continue`）不是这四处矛盾。
它失败是因为 `client.send` 只把 `session/prompt` 写进 stdin 就返回，stub 模式的
`session/new` 又不预先启动 worker（`appserver/server.py` 里 `if not self._stub`
才后台 warm）。marker 子进程要等 prompt 任务里的 `StubAgent` 起来才存在。
2026-10-08 探针：`send` 返回当下 `_marker_pids` 是空集，1 秒后是 `{36684}`。
只在 `RXYCODE_APPSERVER_STUB=1` 且 `RXYCODE_STUB_STALL_AFTER_PROMPT=1` 时，
于 `session/new` 的响应之前把这个真实 worker 拉起来。marker 仍是该 worker 的子进程。
该函数随后 1 passed（8.10s）。下面四条没有沿用这个做法。

## E-P-E2E-02 ledger scope

测试 `tests/e2e/phase_p/test_e2e_p_02_pipeline_capped_stop.py` 用
`AgentV2.__new__` 调用 `_pipeline_budget_branch`，没有设置 `_session_id`，
也没有绑定 `sess_e2e` / `task_e2e`。断言却是
`ledger.count(("sess_e2e", "task_e2e")) == 2`，注释写「`_scope_of` 默认夹具」。

生产代码的 scope 唯一推导是 `(session_id, subject_id)`。pipeline 分支的
session 来自实例上的 `_session_id`，缺省是 `"pipeline"`；subject 是
`get_current_run_id()`，没有请求上下文时是进程 run id。
开发文档 `PHASE-P-AGENTIC-TIMEOUT-LOOP.md` 写明
`pipeline_soft_budget` 的 subject 是 run/session，`last_grant` 的 scope 是
`(session_id, run_id)`。U-P4 用同一个薄方法，不要求夹具 id。

把 `sess_e2e` / `task_e2e` 写进生产代码，就是把测试夹具 id 硬编码进去。
测试包要夹具默认 id，开发文档要真实 run/session。两文矛盾，停。

## E-P-E2E-06 决策调用次数

`helpers.evidence_dict` 的 `budget_seconds` 默认是 7200。
`helpers.policy_dict` 里 `tool_timeout` 的 absolute cap 也是 7200，
`graph_task_max_time` 的 cap 是 21600。测试把这两份默认值原样交给
`engine.decide`，并断言 `ainvokes == 2` 且两次都是 `continue`。

开发文档和 `DecisionPolicy.pre_check` 都是：`budget_seconds >= cap` 时不调 LLM，
强制 `action="stop"`。tool 那次证据已经顶在 cap 上，所以只会调用 1 次。
把 `>=` 改成 `>`，或在 room 为 0 时仍去问模型，就是放宽封顶。停。

## E-P-E2E-09 与 E-P-E2E-07

E-P-E2E-07 要求 pending 决策被 `interrupt()` 之后，sink 里有一条
`fail_closed` 的 `stop`，note 以 `"[fail-closed] interrupted"` 开头。
这条现在是通过的。开发文档同一节把这个事件序钉死。

E-P-E2E-09 在同一引擎上先得到一次 `continue`，再对下一次 pending 调用
同一个 `interrupt()`，最后断言 sink 的 action 列表仍是 `["continue"]`，
注释写「interrupt 不落 continue/stop 事件」。

两次调用的是 `TimeoutDecisionEngine.interrupt()`。作废的那次决策落定时会把
fail-closed stop 写进同一个 sink。删掉这条事件，07 变红；留着，09 变红。
同一测试包里的两条断言互相否定。停。

## E-P-E2E-03 fallback 的第二条决策

开发文档把 `_restart_worker_continue` 的顺序钉成：
杀旧 host、启动新 worker、hydrate、经既有 prompt 通道重发。
interrupt RPC 抛异常是决策之前的那一形态：跳过 hook，不产生决策，
`fail_job(kill_host=False)`，不二次杀。

测试包环境表写 `RXYCODE_STUB_RESTART_INTERRUPT_PHASE_FAILS` 使
`_restart_worker_continue` 内部的 interrupt RPC 失败，并断言第二条
`event/timeout_decision` 的 action 是 `stop`，note 含
`killed_by_interrupt_fallback`。

已经通过的 restart 函数走的是文档钉死的 kill/spawn/hydrate，只有一条
continue，终态文本是 `E2E03-FINAL`。在这条成功路径上补一条 stop，
会同时违背「RPC 失败则跳过决策」和已经钉死的重启顺序。两文矛盾，停。

## 不在本次 GX8 里

E-P-E2E-08 仍因仓库没有 `protocol.todo_snapshot` 而导入失败。
P8 维持 `BLOCKED_PREREQUISITE`。没有为它补模型。
