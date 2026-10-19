# RxyCode Web — 系统设计与 ADR 决策链

适用分支：`feat/rxycode-web`。本文是从 W0 到 W7 的真实决策链与最终架构，不是设想文档——每条决策标注落点与证据。

## 总览

```
浏览器 (React/Vite, apps/web)
   │ HTTPS (Caddy 内部 CA)  /api/v1/* + SSE + WS
   ▼
api 服务 (rxycode_server, FastAPI)
   │ 认证: local / GitHub OAuth; 写路径 = Origin+CSRF+session 三重校验
   │ 限流: RateLimitMiddleware（应用层固定窗口）
   ▼
PostgreSQL ── runs / run_events / outbox / usage / sessions
   ▲                     ▲ (claim: fenced lease + epoch)
   │                     │
worker (python -m rxycode_worker.drain)
   │ 1. claim（仅 pending/租约过期行）
   │ 2. 放置闸 _execution_gate：cloud-only 只接 cloud:{自身tenant}:*，
   │    拒 local/sandbox/full*
   │ 3. spawn turn 子进程 ──► bwrap 沙箱：
   │      --unshare-user --unshare-pid --unshare-ipc --unshare-uts
   │      --clearenv + setenv 白名单；只读系统根+代码树；
   │      唯一可写 = /work/runs/<tenant>/<session>；--die-with-parent
   │ 4. 沙箱内：ProtocolTui + RunContext + Session.prompt（真 AgentV2）
   │ 5. 看门狗：wait_for 限时续约 + 单调到期——证明不了租约就 cancel，
   │    lost_lease 不写终态
   │ 6. 账本 → commit_terminal / confirm_cancel
   ▼
MinIO（工件签名 URL）/ Redis（命令队列）/ web-dist（静态前端）
```

## ADR 决策链（按冻结顺序）

| # | 决策 | 理由 | 落点/证据 |
|---|---|---|---|
| W0-C04 | 单一 Agent 基线：web 不加第二套 Loop | 复用 Session.prompt 链路与回归基线 | evidence/web/WEB-W0-C04 |
| W1-C02 | `RunContext` 不可变显式上下文，`from_authenticated` 拒客户端 claims | run_id/tenant/actor 只能来自服务端持久身份 | packages/rxycode-protocol |
| W1-C03 | ExecutionPort + ToolSpec 能力域、唯一安全门 | 工具面收敛，不写第二通道 | evidence/web/WEB-W1-C03 |
| W2-C03 | durable run + fenced lease（epoch 单调） | 崩溃接管语义：旧 owner 不得再写 | tests/web/w2/test_w2_c03_module.py |
| W2-C04 | run_events + outbox + seq 重放 | 断线续传 exactly-once | evidence/web/WEB-W7-C02 |
| W5-C02 | **禁止向容器内暴露 docker.sock** | 共享 worker 不能借宿主 docker 再造逃逸面 | compose 不变量（CI 校验） |
| W7-C05 | 部署内云沙箱 = worker 容器内 per-run userns/bwrap | docker.sock 禁了就只能在容器内做内核隔离；seccomp=unconfined 仅 worker | userns.py + compose.yaml |
| W7-C05 | 放置闸 `cloud-only`：仅 `cloud:{tenant}:*`，拒 `local:*`；`full*` 解析为沙箱内免审批 `full_auto` | 权限档位只是审批语义，永远改变不了挂载/网络/写域 | drain.py `_execution_gate` |
| W7-C05 | 账本失败 → `failed`（取消中的 run 落 `recovery_required` + pending 对账） | succeeded 不得站在缺失账本行上 | drain.py usage_error / confirm_cancel 路径 |
| W7-C05 | 升级 = 清卷重灌而非 overlay | overlay 会留下旧修订与已删文件 | web-runbook.md |

## 边界与残余风险（评审已接受的）

- 沙箱现在私有网络命名空间（`--unshare-net`）：唯一出口是父进程侧过滤 CONNECT 代理（`worker.egress` + `netrelay` loopback 桥）；元数据/私网/非 80·443 端口在父进程拒绝，与权限档位无关。
- turn 子进程不再持有 DB URL：journal/命令/审批走父进程持有的 UNIX 控制 socket（`worker.ctl`），handler 绑定 tenant/run/worker/epoch，lease 已释放的 op 由服务层拒绝。
- `seccomp=unconfined` 只给 worker，没有 cap_add/privileged/sock；validator+CI 双向不变量。
- 审批应答面：非 Full 的高危调用 `approval.requested` 持久化后 run 进 `waiting_approval`（租约释放，不算无进展）；批准后 run 回 `pending`，新受限子进程按 journal 恰好重放原调用一次；拒绝/取消的 run 不再执行。
- 浏览器 E2E：BLOCKED（无 Playwright），见 evidence/web/WEB-W7-C06。

## 与单机版的关系

`Session`/`AgentV2`/工具编排是同一份；web 只是把传输换成 HTTP/SSE、把执行包进 per-run 边界。本机 CLI 的 Full（宿主权限，`core/sandbox/policy.py`）语义不变；Web 的 `full`/`full_auto` 只映射为同一沙箱内的免审批模式——隔离不是权限可以购买的商品。
