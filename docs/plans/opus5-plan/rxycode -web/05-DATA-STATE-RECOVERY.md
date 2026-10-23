# 数据层 / Worker / Checkpoint / Side-Effect Journal · 恢复合同

> **Owner**：server + worker；**Status**：Frozen design，代码未执行；主要卡 W2-C01～C07。

## §1 PostgreSQL 权威模型

| 表 | 核心字段 | 必须建立的约束 |
|---|---|---|
| users | id, github_id | github_id unique；local user 明确隔离 |
| organizations/memberships | tenant_id, user_id, role | FK + unique 组合 |
| projects | id, tenant_id, repo_config | 不以用户传入的 tenant_id 授权 |
| sessions | id, tenant_id, project_id, title | DB 目录是真相；旧 task_store 仅兼容 |
| runs | id, tenant_id, session_id, status, revision, lease_owner, lease_epoch, lease_until, request_id, input_digest, target_id | unique(tenant_id,request_id)；单 Session 不可同时激活不兼容的 Run |
| run_events | event_id, run_id, tenant_id, seq, type, payload, at | append-only；unique(run_id,seq) |
| outbox | event_id, dispatch_status, attempts | 与 Event 在同事务落库 |
| approvals | id, tenant_id, run_id, call_id, status, revision, deadline | 决策 CAS、超时转态 |
| tool_invocations | run_id, call_id, target_id, attempt_id, journal_state, digest | unique(run_id,call_id)，unknown 不自重试 |
| devices/device_grants | id, tenant_id, credential_hash, grant_scope, revoked_at | 本机 grant 是最终权限真相 |
| artifacts | run_id, object_key, sha256, size, content_type | owner 校验 + 短效下载 |
| usage_records | run_id, model_id, price_version, tokens, currency, amount | 终态重复投递只计一次 |

实际 schema 在 SQLAlchemy 2 + Alembic 迁移卡冻结；上表**不是已落库**。所有敏感资源都具备 tenant foreign key、唯一性、状态版本号，查询不得只以 resource ID 为条件。`run_events` 序号按事务原子分配，Outbox 投递可重复而不能漏提交。

## §2 Agent 运行时的四个不同持久化真相

```text
Run Store        ：任务归属、状态、租约、重试决定
Event Store      ：供前端按序重建页面的事实
LangGraph Saver  ：推理 Graph 的节点/状态/interrupt
Tool Journal     ：外部副作用是否执行及安全重放资格
```

**绝不混淆**：Graph checkpoint 并不让外部 Git push、桌面鼠标点击和 OS 子进程“恰好执行一次”。LangGraph interrupt 恢复可能从节点开始重新执行；必须保持已有 `execution/tool_journal.py` pending/unknown 阻止重放的语义。事件回放恢复 UI，不等于恢复 Agent/进程执行现场。

## §3 Run 调度与并发

创建 Run 在 PG 事务插入 run+initial event+outbox，然后返回 202；异步 dispatcher 从可靠 outbox 分发，避免“DB 已有 Run 但队列永远未入”。 Worker 领取 Run 采用数据库事务锁/租约，增加 `lease_epoch` fencing，提交运行结果前验证 epoch。一个 Session 默认最多一个活动 Run（DB 强制），不同 Session 可并行。租约过期不意味着可以重做结果未知的写操作。

取消操作先写 cancel_requested，通知 Worker/Runner，结果获确认后才写 cancelled；在途副作用未知则进入 recovery_required，不得骗用户说全部停止。

## §4 崩溃和断线真值表

| 故障时机 | 必须得到的结果 | 负向测试 |
|---|---|---|
| SSE 关闭 | Worker 不停，重连事件补全 | SSE-01 |
| DB event commit 后 Redis publish 前 | Outbox 最终通知，客户端从 DB 补齐 | SSE-02 |
| Worker 纯读步骤宕机 | 恢复从 Checkpoint，已有结果不重复 | REC-01 |
| Worker 工具 ACK 前宕机 | 查询 Runner 已知 call_id；未知即 recovery_required | REC-02 |
| Graph 审批中断隔夜 | 持久化审批 + Resume，Worker 不长期占用 | APV-02 |
| Runner 掉线，随后重连 | 状态确认，同 call_id 无副作用重复 | RPC-02 |
| Worker 租约过期但原 Worker 仍运行 | stale epoch 禁止写事件/终态 | RUN-02 |
| 授权撤销，已有 WS 仍在线 | 新调用立刻拒绝，在途按政策处理 | SEC-REVOKE-01 |
| PTY/浏览器进程已被操作系统销毁 | 展示不可附着、提供可重新启动机制，不宣称 Checkpoint 复活了进程 | PROC-02 |

## §5 保留和数据保护

Event 与 Artifact 制定 per-tenant retention 和备份，历史游标过期明确 `CURSOR_EXPIRED` 和快照恢复路径；不得静默丢弃中间工具事件。Trace 仅存可展示摘要和脱敏工具输出。存实际模型 ID/计费版本/Token，避免用新价格“重算”旧任务结果。
