# 工具能力域与 ToolSpec 注册矩阵

> **现有基础**：`tools/`、`execution/tool_orchestrator.py`、`core/cu/`、Playwright MCP、Chrome CDP、`mcp/`、`core/agents/`，先核对已实现工具再做增量；遵守旧 U24/U46、PP40/PP80 的 owner。

## §1 不可缺少的统一 ToolSpec

`name,version,capability,risk(READ|WRITE|DANGER),supported_targets,timeout_seconds,idempotent,supports_stream,input_schema,output_schema`。`ToolInvocation` 增加 `run_id,call_id,target_id,trace_id,grant_id,deadline_at`。**能力声明不是授权**；所有工具统一通过 ToolOrchestrator 安全门与 Journal，MCP 注解不能降风险。

## §2 真正提高用户体验的工具优先级

| 能力域 | 保留的现有入口/需先核验 | 增量设计 | 交付场景 |
|---|---|---|---|
| Code / File | `read/write/edit/patch` | multi_edit, apply_patch, undo/review | 多文件真实修改与审查 Diff |
| LSP | `docs/modules/lsp.md`, RAG | definition/references/diagnostics/rename | 语义代码定位 |
| Shell / Process | `tools/bash.py`, `utils/shell.py` | persistent process/PTY/ports | 实时 dev server 与终端 |
| Git | 现有 Git tool | branch/commit/PR/review/approve | GitHub PR 闭环 |
| Tests | ToolOrchestrator + bash | 结构化 pytest/jest/coverage 结果 | 自动回归修复 |
| Browser | U24 Playwright、U46 Chrome CDP | profile 生命周期、handoff、preview 分离 | 网页自动化和测试 |
| Desktop | `core/cu/` | window/screenshot/mouse/keyboard/clipboard | 真正 Native Full |
| Artifacts | history/preview/review | upload/download/render + owner ACL | Web 下载真实文件 |
| Approval | JSON-RPC approval/question | DB durable approvals + notification | 跨天审批继续 |
| Team | 原 F 系列 + Todos | DAG Activity / Followup / Steer UX | 多 Agent 可视化与任务控制 |
| Memory | `memory/`, `rag/` | tenant/project scoped browse/edit/delete | 项目上下文可治理 |
| Plugins | MCP/Plugin host | 可选 MCP Server facade | 不建立第二 invoke |

优先把 Edit → Test → Diff → PR 跑成真实闭环，再扩展更多 tools。模型按 target/capability 只加载当轮候选工具；`Full` 不代表把所有工具无脑进上下文。评测全量注册与动态筛选在固定任务集上的成功率/成本。

## §3 Tool 运行风险/异常要求

即使 ToolSpec 标 `idempotent=true`，仍需以实际操作和稳定 `call_id` 证明可安全 replay。对 shell/文件/浏览器输入/PR 默认 `idempotent=false`；输出过长要截断且保留截图/日志 Artifact。能力不足必须返回结构化错误（不改为“假执行成功”）；工具错误进入 Agent 轨迹，允许模型重新规划，但未经核实的副作用不得重试。
