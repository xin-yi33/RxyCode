# RxyCode v1.4.3

日期：2026-10-09。此版本是 CLI / OpenTUI 的 P8 补缺发布；不发布新的
Electron Desktop 安装包，也不发布 wheel。

## 本次变化

- 四个生产超时决策入口——pipeline、graph watchdog、ToolOrchestrator、
  AppServer stall recovery——现在消费当前 session 的权威 `TodoSnapshot`。
- 共享读取路径为 `protocol.todo`、
  `tools.todo_events.read_todo_snapshot` 和
  `tools.todo_events.todo_progress_for_session`；progress 每次决策从最新
  revision 重新投影。
- 空/坏快照、不同 session 或 scope，以及没有真实会话的匿名 graph bucket
  都不会串读别的 Todo，并安全产生空 progress。
- worker 或消费方重建后，会从同一 session 已持久化的快照恢复最新 progress；
  显式的非 Todo graph progress 保持兼容。
- 读取和恢复 Todo 不调用额外的 Todo-summary 模型。详细边界与验收记录见
  [`P8/FIX5 handoff acceptance`](../P8-FIX5-HANDOFF-ACCEPTANCE.md)。

## 安装

本版本只发布一个资产：`rxycode-1.4.3.tar.gz`。

```powershell
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.4.3"
rxycode --version
rxycode
```

或下载 Release 的 tar.gz 后：

```bash
python -m pip install rxycode-1.4.3.tar.gz
rxycode --version
```

产品版本为 `1.4.3`；JSON-RPC 仍为 `1.1.0`；Python 导入路径仍为
`RxyCode.RxyCode1_1_0`。Desktop 资产仍需使用已有 Desktop release，不能由
CLI 包推断已发布 Desktop。

## 真实边界

- 超时决策默认关闭；关闭分支仍是有效兼容路径。
- Todo 是自报告的计划状态，不证明工具结果、文件或测试验证、预算、journal
  完成或最终答案正确性。
- R-11 仍保留：外层 timeout grant 不会延长 shell 自己的内部 deadline。
- 1.4.2 的审计、发布说明和 tag 保持冻结；本次补缺记录在 1.4.3。

## 验收口径

P8 专项为 `112 passed`，无 skip，且不重复计入主审全量
`13463 passed / 28 baseline skipped`。主审全量中的 28 项是既有基线 skip：
26 项忽略计划树、1 项显式 live、1 项重复 query；本次没有新增 skip。
本地 tar、云端 CI 与正式 Release 资产仍须按发布流程独立复验，本文不预先
宣称这些结果为绿。
