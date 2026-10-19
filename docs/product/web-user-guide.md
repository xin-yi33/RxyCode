# RxyCode Web 用户指南（多租户云端工作区）

适用分支：`feat/rxycode-web`。协议版本 1.1.0。

本指南只描述已交付且有证据的行为；未交付的路径明确标注 `BLOCKED`/`planned`，不会写成可用功能。

## 这套部署是什么

RxyCode Web 是同一份 headless 核心（`Session`/`AgentV2`）上的多租户 Web 面：

- **API 网关**：`rxycode_server`（FastAPI），认证为本地口令或 GitHub OAuth，会话是 HttpOnly cookie；写操作必须过 Origin + CSRF 双校验。
- **运行队列**：run 是 PostgreSQL 里的持久行；worker 以 fencing token 认领（lease + epoch），崩溃后由新 worker 在租约到期时接管——同一行永不被两个 owner 写终态。
- **执行边界**：共享 worker 上每个 run 的 turn 整个跑在 per-run 沙箱里（Linux user/pid/IPC/UTS namespace + bubblewrap 最小只读根 + 仅该 run 工作区可写 + `--clearenv` 白名单环境）。沙箱不可用时 run 直接失败，**绝不回落到宿主机执行**。
- **事件面**：`run_events` + outbox 是持久事件日志；SSE 端点按 seq 重放，断线重连不丢不重。
- **费用**：每次 turn 的 token 实测写入 usage 账本（成功/失败/取消都写），账本写失败会让终态变 `failed`——不存在"成功但没记账"。

## 安装与启动（自托管）

前置：Docker Engine（含 Compose v2）、一个可写的工作目录、可选的 LLM 凭据。

1. 克隆本分支并进入 `infra/compose/`。
2. 必填环境变量（compose 会拒绝缺失值）：
   `RXYCODE_POSTGRES_PASSWORD`、`RXYCODE_MINIO_ROOT_USER`、`RXYCODE_MINIO_ROOT_PASSWORD`、`RXYCODE_WEB_SECRET`（≥32 字节）。
3. 可选：`RXYCODE_LLM_BASE_URL` + `RXYCODE_LLM_MODEL` + `RXYCODE_API_KEY`——不配则 turn 在 provider 边界诚实失败（`failed`，不是假成功）。
4. `docker compose up -d` → `reposync` 把源码 tar 灌入 `repo-src` 卷 → `migrate` 跑 Alembic 到头 → `webbuild` 产出前端 → `api`/`worker`/`gateway` 起。
5. 访问 `https://localhost:<RXYCODE_HTTPS_PORT>`——Caddy 内部 CA 签发 `localhost` 证书，浏览器首次会警告（属预期，内部 CA 不被默认信任）。

升级/回滚与边界清单见 `docs/deploy/web-runbook.md`；升级必须先清空 `repo-src` 卷再重新播种（runbook 里是精确命令）。

## Onboarding / 登录

- 打开站点 → 未登录访问任何 `/api/v1/*` 一律 `401`；写操作另外要求 Origin 在允许列表且 `rxy_csrf` cookie 与 `x-csrf-token` 头一致，否则 `403`。
- 本地模式：共享本机账户口令登录。
- 云模式：走 GitHub OAuth；未完成的授权回调被拒绝。
- **不存在匿名 run 入口**——「访客完成受限任务」在 HTTP 面就是 401/403；这不是疏忽，是冻结决策（公网 Demo 不暴露本机执行面）。

## 权限模式与目标

| 目标/模式 | 共享 worker（公网栈） | 本机 Runner |
|---|---|---|
| `cloud:{tenant}:{workspace}` + `auto_edit`/`confirm_all` | 在 per-run 沙箱内执行 | — |
| `local:*` | **拒绝**（`run.error` → `failed`，不 spawn） | 本地执行（沙箱开） |
| `full`/`full_auto` | **拒绝**（Full = 无沙箱宿主权限，公网 worker 没有） | 用户确认后解除沙箱限制、免审批 |
| 沙箱不可用（无 bwrap/userns） | run `failed` + `IsolationUnavailable` | — |

跨租户绑定（`cloud:别人的tenant:x`）同样被拒——tenant 段必须等于 run 自己的 `tenant_id`。

## 错误与排错

| 现象 | 真实原因 |
|---|---|
| `401 UNAUTHORIZED` | 无会话 cookie 或会话过期（TTL 滚动） |
| `403 FORBIDDEN` | Origin 不在允许列表，或 CSRF cookie/header 不匹配 |
| `429 RATE_LIMITED` | 触发应用层限流（`RXYCODE_WEB_RATE_LIMIT_RPM`，默认 240/分） |
| run `failed` + "run timed out" | turn 超过 `RXYCODE_WORKER_RUN_TIMEOUT`（默认 900s）被 SIGKILL——`--die-with-parent` 保证整棵进程树回收 |
| run `failed` + "not local/cloud" | target 不被当前 `RXYCODE_WORKER_EXECUTION` 允许 |
| run `failed` + "userns/bwrap unavailable" | worker 容器缺 `seccomp=unconfined` 或 bwrap——检查 compose worker 段 |
| `worker.lease` 后无进展 | worker 崩溃；租约到期后由存活 worker 接管（epoch+1） |

## FAQ

**Q: 为什么公网 Demo 不能跑本机 Full？** A: Full = 解除沙箱的宿主权限，只对运行者自己的机器有意义；共享 worker 永远没有它，请求被诚实拒绝而不是降级执行。

**Q: 审批（confirm_all）的 run 在部署栈里会怎样？** A: 审批请求会发出（`approval.requested`/`question.requested` 投影落库），但当前栈没有应答面——turn 在 run_timeout 处诚实 `failed`。

**Q: 工作区文件持久吗？** A: `worker-data` 卷内（`/work/runs/<tenant>/<session>`），容器重启保留，`down -v` 清空。

**Q: 浏览器端 E2E 演示在哪？** A: `BLOCKED`——apps/web 无 Playwright 依赖，本卡不伪造该腿；模块测试覆盖的是服务端真实拒绝面。

## 已知限制（诚实清单）

- 限流是进程内固定窗口，只对单副本部署准确。
- 沙箱内 turn 持有 `RXYCODE_WEB_DATABASE_URL`（journal/命令通道需要）；理论上 run 代码能直接写 run_events——已记录为残余风险，out-of-process journal broker 是后续工作。
- 沙箱不隔离网络命名空间（turn 需要到 Postgres 和 LLM 端点）；egress 策略是 `sandbox.egress` 预留缝。
