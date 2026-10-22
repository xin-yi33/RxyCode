# 跨端协议合同：HTTP / SSE / Runner WSS / JSON Schema

> **Owner** protocol + server；WEB-W1-C04 冻结后才能开发依赖客户端。既有 `protocol/schema.json` 是旧客户端类型生成权威，新增消息必须保持旧 `initialize` 和 `session/prompt` 兼容并输出版本化 JSON Schema + TS 类型。

## WEB-W0-C04 freeze

Session、Run、AgentEvent、ExecutionTarget、ToolInvocation、DeviceGrant 这六个名字按上面的草案使用。`initialize` 和 `session/prompt` 留在旧 JSON-RPC，不改成新的 Web 命令名。本段只是冻结草案，不是已落实。

## §1 HTTP API V1（全部经身份/租户鉴权）

| Method | Path | 作用 | 不得省略的错误 |
|---|---|---|---|
| GET | `/api/v1/me` | 当前用户与权限 | UNAUTHORIZED |
| GET/POST | `/api/v1/projects` | 目录/新项目 | FORBIDDEN/INVALID_INPUT |
| GET/POST | `/api/v1/projects/{id}/sessions` | Session 目录/创建 | PROJECT_NOT_FOUND |
| GET | `/api/v1/sessions/{id}` | Session 与 Run 摘要 | SESSION_NOT_FOUND |
| POST | `/api/v1/sessions/{id}/runs` | 创建 Run，202 接受 | RUN_ALREADY_ACTIVE/TARGET_UNAVAILABLE |
| GET | `/api/v1/runs/{id}` | 查询 Run 真相 | RUN_NOT_FOUND |
| GET | `/api/v1/runs/{id}/events?after_seq=N` | SSE replay+follow | CURSOR_EXPIRED/FORBIDDEN |
| POST | `/api/v1/runs/{id}/cancel` | 幂等取消 | INVALID_TRANSITION |
| POST | `/api/v1/runs/{id}/steer` | 后续输入/修正 | INVALID_TRANSITION |
| GET/POST | `/api/v1/runs/{id}/approvals` | 等待审批/提交决定 | APPROVAL_STALE |
| GET | `/api/v1/runs/{id}/artifacts` | 文件结果/可审下载 | ARTIFACT_FORBIDDEN |
| GET/POST | `/api/v1/devices` | 设备/配对 | DEVICE_FORBIDDEN |
| POST | `/api/v1/devices/{id}/revoke` | 吊销凭证 | DEVICE_REVOKED |
| POST | `/api/v1/devices/{id}/grants` | 请求本机授权 | LOCAL_CONFIRM_REQUIRED |
| GET | `/api/v1/usage` | 用量成本 | FORBIDDEN |
| WS | `/runner/ws` | 出站 Runner RPC | AUTH_FAILED/VERSION_UNSUPPORTED |
| WS | `/api/v1/terminals/{id}/ws` | PTY 双向流 | TARGET_UNAVAILABLE |

`POST /runs` 请求必须包含 `message,target_id,permission_profile,request_id`；`tenant_id/actor_id` 由服务端会话确定、不得信任请求体；同 `(tenant_id,request_id)` 同 payload 重试返回相同 Run，不同 payload 同 key 报 CONFLICT。响应：`{ "run_id":"run_1", "status":"queued", "events_url":"/api/v1/runs/run_1/events" }`。

## §2 状态协议

- Run：`queued → running → succeeded|failed|cancelled|waiting_approval|waiting_input|recovery_required`；waiting 回到 queued/running 或 cancelled；从 recovery_required 回到 queued 只能通过显式安全恢复决定。
- `cancel_requested` 是中间控制动作，不能未经 Runner 确认就当 cancelled。
- `runs` 必须 CAS revision + `lease_epoch` fencing；一个 Session 默认一个 active run，强制 DB 并发约束。
- `approval` 有 `approval_id,run_id,call_id,status,revision,deadline`；重复决定或过期决定返回 APPROVAL_STALE。

## §3 Event Envelope（EventStore 权威）

```json
{
  "event_id":"evt_01", "run_id":"run_01", "session_id":"ses_01",
  "seq":17, "type":"tool.started", "at":"2026-10-16T00:00:00Z",
  "schema_version":1, "trace_id":"trace_1",
  "payload":{"call_id":"call_1","tool":"shell.exec","target_id":"local:1"}
}
```

冻结 event type：`run.queued`, `run.started`, `run.status`, `assistant.delta`, `assistant.final`, `reasoning.summary`, `plan.updated`, `todo.updated`, `tool.started`, `tool.chunk`, `tool.completed`, `tool.failed`, `approval.requested`, `approval.resolved`, `question.requested`, `question.resolved`, `agent.started`, `agent.completed`, `artifact.created`, `usage.updated`, `run.completed`, `run.failed`, `run.cancelled`, `run.recovery_required`。

`seq` 对同一 Run 单调递增，由 DB 提交事务分配；`event_id` 全局唯一。SSE `id` 即 seq，UI 根据 `(run_id,seq)` 去重。Agent 子节点用 `parent_agent_id` 和 `intermediate` 明确层级；原始隐藏 reasoning、API key、环境变量和未授权路径不得原样送 UI。

## §4 SSE replay-and-follow 正确性

订阅通知通道后必须根据数据库游标回放 `seq>after_seq`，回放结束和监听之间不能出现事件缺口。收到 Redis/NOTIFY 只能视为唤醒，再从 DB 补齐全部缺失事件；丢通知仍由定时查询追赶。写事件+Outbox 必须同一事务，异步通知可至少一次，前端幂等。支持 `Last-Event-ID`/显式 `after_seq`，明确优先级与非法游标策略。超出保留期返回 `CURSOR_EXPIRED` + 可恢复快照位置，不能从最新静默开始；Run 终态也可回放。

**必须模拟的竞态**：提交 seq43 恰好发生在 DB 历史回放尾部与 Redis 订阅之间，订阅者最终收到 seq43；重复通知不增加 UI 行数；SSE 断开不取消 Run。

## §5 Runner Protocol V1（与浏览器会话 token 分离）

WSS RPC 消息 envelope：`type,message_id,device_id,run_id,call_id,lease_epoch,deadline,payload_schema_version,payload`。Hello 包含 OS、capability、版本；Server 从已认证连接绑定设备 ID，不信客户端自填 ID。调用必须携带 `grant_id`，本机 Runner 自检 session/target/expiry/capability/workspace/revocation；仅服务端声称 Full 无效。

```json
{
  "type":"tool.invoke", "message_id":"msg_21", "device_id":"dev_01",
  "run_id":"run_01", "call_id":"call_7", "lease_epoch":3,
  "deadline":"2026-10-16T01:00:00Z",
  "payload":{"tool":"shell.exec","args":{"argv":["python","-m","pytest","-q"]},"grant_id":"grant_9"}
}
```

消息族：`device.hello/ready/heartbeat/capabilities`, `grant.request/accepted/denied`, `tool.invoke/ack/chunk/result/error/status_query/status_result/cancel`, `device.revoke/goodbye`。单发送队列串行 WS write；并发任务独立处理且有背压。chunk 限大小、顺序 `chunk_seq`、输出截断。相同 `call_id` 不重复执行；断线后结果未知→状态查询→无法确认则 `recovery_required`，禁止自动 replay 有副作用工具。

## §6 测试契约

HTTP-01 跨租户拒绝；RUN-01 幂等创建；RUN-02 stale Worker 拒绝；SSE-01 replay；SSE-02 竞态无漏；SSE-03 去重；APV-01 审批 CAS；RPC-01 无 grant 拒绝；RPC-02 unknown 不能重放；RPC-03 同 call_id 去重；RPC-04 云端伪造 Full 拒绝。测试详细 `tests/TEST-MATRIX.md`。
