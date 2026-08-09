# Upstream Reuse Audit — Phase B (B1–B14)

**锁定上游**: [OpenCode](https://github.com/anomalyco/opencode)
**锁定 commit**: `fe82a1b6ca4f535beb973b0867017e3f639f85ed`
**许可证**: MIT
**审计日期**: 2026-08-09
**Owner**: Composer 2.5

---

## 上游来源与许可证

| 来源 | URL | 许可证 | 用途 |
|------|-----|--------|------|
| OpenCode 源码 | https://github.com/anomalyco/opencode | MIT | Agent 定义、Subagent Runtime、Permission、Child Session、事件协议 |
| OpenCode Agents 文档 | https://opencode.ai/docs/agents | — | mode/description/model/steps/hidden/@mention 语义基线 |
| OpenCode Permissions 文档 | https://opencode.ai/v2/docs/permissions | — | allow/ask/deny、glob、last-match-wins 语义基线 |

---

## B1–B14 逐卡复用审计

| 卡号 | 上游来源 | 复用模式 | 复用内容 | 未复用内容（含原因） | 适配文件 | 验证命令 |
|------|---------|---------|---------|-------------------|---------|---------|
| B1 | OpenCode `Session` / `AgentV2` | semantic-port | Primary/Subagent 定义模式、session_id 生成 | OpenCode 无隔离 workspace/audit；RxyCode 需要 ChildSessionManager + parent_session_id | `core/subagents/` | `pytest tests/test_subagents/test_baseline.py -q` |
| B2 | OpenCode `agent.yaml` / AgentDefinition | semantic-port | id/description/mode/model/steps/hidden 字段 | RxyCode 扩展 permission/task_permission/subagent_depth/workspace_scope；无 YAML 配置层 | `protocol/subagents.py` | `pytest tests/test_subagents/test_definitions.py -q` |
| B3 | OpenCode Primary/Subagent mode | semantic-port | mode 语义（primary/subagent/all） | RxyCode 增加 isolation_profile/child_only 限定 | `core/subagents/registry.py` | `pytest tests/test_subagents/test_modes.py -q` |
| B4 | OpenCode `Session` 生命周期 | semantic-port | session create/list/teardown 接口 | RxyCode 增加 parent_session_id/depth/isolation_profile/event_store | `core/subagents/sessions.py` | `pytest tests/test_subagents/test_sessions.py -q` |
| B5 | OpenCode 无直接对应 | direct-dependency | 参考 OpenCode 子进程隔离思路 | RxyCode 自研 ChildRuntime facade + workspace lease + 预算控制 | `core/subagents/runtime.py` | `pytest tests/test_subagents/test_runtime_isolation.py -q` |
| B6 | OpenCode ContextEnvelope 概念 | semantic-port | context/parent_session_id/attachments | RxyCode 增加 redactions/max_context_tokens/references 类型 | `protocol/subagents.py` | `pytest tests/test_subagents/test_context.py -q` |
| B7 | OpenCode `task/start` 路由 | semantic-port | task 调度接口、TaskRequest/TaskResult 形状 | RxyCode 增加 output_schema/BudgetSpec/WorkspaceScope/TaskPermissionSpec | `appserver/subagent_routes.py` | `pytest tests/test_subagents/test_task_dispatch.py -q` |
| B8 | OpenCode `@agent` mention | semantic-port | @mention 触发模式、agent_invoke 接口 | RxyCode 增加 alias/source/explicit_approval 字段 | `tools/agent_invoke.py` | `pytest tests/test_subagents/test_mention.py -q` |
| B9 | OpenCode Permission (allow/ask/deny) | semantic-port | 三态权限、glob 匹配、last-match-wins | RxyCode 增加 audit_reason/approval_id/expiry/per_task 隔离 | `core/subagents/permissions.py` | `pytest tests/test_subagents/test_permissions.py -q` |
| B10 | OpenCode workspace 概念 | none | 仅参考 "workspace" 命名 | RxyCode 自研 read_only/leased_write/isolated_worktree 三态隔离；OpenCode 无 workspace_scope | `core/subagents/workspace.py` | `pytest tests/test_subagents/test_workspace.py -q` |
| B11 | OpenCode steps 概念 | semantic-port | max_steps 步数限制 | RxyCode 增加 BudgetSpec(max_tokens/max_wall_time_seconds/max_concurrent_children + 汇总统计) | `protocol/subagents.py` | `pytest tests/test_subagents/test_budget.py -q` |
| B12 | OpenCode 事件协议 | semantic-port | 事件通知模式（tool_begin/tool_end/final/done） | RxyCode 增加 child_session/* 事件族 + EventStore 持久化 + cursor | `protocol/subagents.py`、`core/subagents/events.py` | `pytest tests/test_subagents/test_events.py -q` |
| B13 | OpenCode 无直接对应 | none | 参考 feature-flag 隔离思路 | RxyCode 自研 migration 测试：feature flag off → legacy path 不变 | `tests/test_subagents/test_migration.py` | `pytest tests/test_subagents/test_migration.py -q` |
| B14 | OpenCode 评测框架思路 | none | 参考 eval harness 模式 | RxyCode 自研 evals/ + YAML task 定义 + LLM-as-judge；OpenCode 无子代理专项评测 | `evals/`、`tests/test_subagents/test_e2e.py` | `pytest tests/test_subagents/test_e2e.py -q` |

---

## 不兼容证据与适配原因

| 组件 | OpenCode 路径 | 不兼容原因 | 适配方式 | 回滚方式 |
|------|-------------|-----------|---------|---------|
| ChildSessionManager | `opencode/core/session.py` | OpenCode Session 不含 parent_session_id/depth/isolation，且使用全局单例 | 自研 `ChildSessionManager`，通过 `.bootstrap` 注入 | 切 feature flag → 退回 legacy Session |
| Workspace isolation | 无对应 | OpenCode 无 workspace lease/read_only/isolated_worktree | 自研 `WorkspaceManager` + lease 机制 | 移除 lease 逻辑 → 退回 read-only |
| Budget | 无对应 | OpenCode steps 无 token/wall_time/children 聚合 | 自研 `BudgetSpec` + runtime guard | 退回单一步数限制 |
| Audit | 无对应 | OpenCode 无 EventStore 持久化、无审计记录 | 自研 `EventStore` + session replay | 关闭审计 → 退回无事件持久化 |

---

## RxyCode 扩展标记

以下字段是 RxyCode 自有扩展，不属于 OpenCode 原生语义：

| 扩展字段 | 所属模型 | 用途 |
|---------|---------|------|
| `x-rxycode-budget` | BudgetSpec | 预算聚合（tokens/wall_time/children） |
| `x-rxycode-audit` | EventStore | 审计事件持久化 |
| `x-rxycode-workspace-lease` | WorkspaceScope | 工作区租约隔离 |
| `x-rxycode-isolation-profile` | ChildSession | 隔离级别配置 |
| `x-rxycode-redaction` | ContextEnvelope | 敏感信息脱敏 |

---

## 验收

- [x] 每个 B 卡都有上游来源和复用路径
- [x] 没有未经说明的等价 Child Runtime 重写
- [x] RxyCode 扩展已明确标记
- [x] 许可证、commit、适配原因、验证命令和回滚方法齐全
- [x] Composer 2.5 已完成最终 diff、测试和接口收口

### 验收命令

```powershell
git ls-remote https://github.com/anomalyco/opencode.git HEAD
git diff --check
Test-Path docs\decisions\upstream-reuse.md
rg -n "opencode|reuse_mode|commit|license|adapter|verification" docs\decisions\upstream-reuse.md
```

---

*Last verified: 2026-08-09 · git push smoke test*
