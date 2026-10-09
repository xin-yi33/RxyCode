# CHANGELOG v1.4.3

> 记录日期：2026-10-09。上一份 `CHANGELOG_v1.4.2.md` 保持冻结不改。
> 本文只记录 P8/FIX5 handoff 的产品补缺。产品版本为 `1.4.3`，JSON-RPC
> 仍为 `1.1.0`，Python 导入路径仍为 `RxyCode.RxyCode1_1_0`。

## 变更

- **P8 超时证据接线**：pipeline、graph watchdog、ToolOrchestrator tool
  timeout、AppServer stall recovery 四个生产入口，在送入
  `TimeoutDecisionEngine` 前读取当前 session 的权威 `protocol.todo`
  `TodoSnapshot`。
- **共享读取与投影**：复用
  `tools.todo_events.read_todo_snapshot`，并通过
  `tools.todo_events.todo_progress_for_session` 做 session/root/list/scope
  校验和确定性 progress 投影；每次决策重新读取最新 revision。
- **失败安全与兼容**：空、坏、跨 session/作用域，以及没有真实会话的匿名
  graph bucket 都不会串读别的 Todo，并安全降级为空 progress。worker 或消费方
  重建后，会从同一 session 已持久化的快照恢复最新 progress；graph 工厂显式
  提供的非 Todo progress 仍保持兼容。读取不写回台账，也不调用额外
  Todo-summary 模型。

## 边界

- 超时决策仍默认关闭；Todo 计划状态不替代工具结果、文件/测试验证、预算、
  journal 或最终验证。
- R-11（shell 内部 deadline 不受外层续期改变）仍不是本次修复内容。
- 本版本只发布 `rxycode-1.4.3.tar.gz`；不发布 wheel 或新的 Desktop 安装包。
- 验收记录见 [`P8/FIX5 handoff acceptance`](../P8-FIX5-HANDOFF-ACCEPTANCE.md)。

## 验收记录

独立 P8 专项回归 `112 passed`，不重复计入主审五层全量记录的
`13463 passed / 28 baseline skipped`。本地发布资产、云端 CI 和正式 GitHub
Release 结果不在本文提前宣称；它们仍需主审按发布流程独立复验。

U-P6-03 的取消路径测试改用 `_HangLLM.ainvoke()` 入口的 `Event` 握手，
不再用固定 sleep 猜测决策是否已启动；`pending == 1`、interrupt、取消和
收尸断言保持不变。CI run `37891014724` 曾因该测试的时序竞争在 Linux
Python 3.12 coverage job 失败；本地修正不等同于云端重跑已通过，仍需主审
按发布流程复验。
