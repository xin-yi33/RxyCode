# Local / Self-host / Cloud 部署与运维规范

> **目标**：`rxycode`, `rxycode web`, `rxycode connect`, Cloud 真正共用内核；本机 Full 在宿主原生进程中运行。`docker-compose` 可容器化 Server/Worker/PG，但**宿主 Full Runner 不能通过 Docker 沙箱冒充**。

## §1 部署形态

| 模式 | 推荐启动 | 环境边界 |
|---|---|---|
| Local | `rxycode web --host 127.0.0.1` | Local Server/Worker + Native Runner，单用户可 SQLite/PG |
| Self-host | `docker compose up` | TLS proxy + Web+FastAPI+Worker+PG+Redis+对象存储；Full Runner 另装宿主 |
| Cloud | 受隔离云端 Sandbox pool+Queue+PG | 每租户文件/进程/网络/成本限额，多实例可扩容 |
| Hybrid | Cloud + `rxycode connect`（出站 WSS） | 设备 token、授权范围、主动急停，不打开个人公网端口 |

## §2 基础设施职责

`proxy(Caddy/Nginx)` 负责 HTTPS、headers、限流、Preview 代理；`api` 只负责鉴权/Run CRUD；`worker` 负责运行 Graph；`postgres` 负责业务/Checkpoint/EventStore；`redis` 用 Stream/通知，不是唯一事件真相；`minio/s3` 持久化 artifact；`sandbox-controller` 调用隔离运行时。正式 Compose 配置只能在 W7-C05 编写/验收，当前文档不假装可以执行 `docker compose up`。

## §3 运行规范

- Cloud OAuth Cookie：HttpOnly/Secure/SameSite + CSRF，Runner credentials 独立；BYOK API key 仅服务端加密，日志和 Trace 脱敏。
- 公开 Demo 只允许隔离云端执行，禁止挂载 `/`、宿主 Docker socket、privileged 或暴露 Host Shell；Sandbox Runtime 不可用须 fail closed。
- 每服务有 liveness/readiness，PG migration 在滚动发布前校验兼容性；变更失败停止发布，不用 drop DB 当回滚。
- 监控：`run_queued_total/run_duration/worker_lease_stale/tool_unknown/sse_reconnect/sandbox_coldstart/token_cost`，Trace 从 HTTP→Worker→Tool→Runner→Event；不输出原始私密 reasoning。
- 运维场景：DB 不可用拒绝新任务；Redis notify 丢失靠 DB catchup；Worker crash 保留 recovery_required；Runner offline 不强行继续；Sandbox crash 回收资源并给真实状态。

## §4 Windows 开发机自检与发布门

```powershell
Set-Location 'D:\agent-demo\RxyCode\RxyCode1_1_0'
git status --short
python -m pytest tests/test_protocol_schema.py -q
python -m pytest tests/system/test_installed_package.py -q
# 只有 WEB-W7-C05 落地后才运行：
# docker compose -f infra/compose/compose.yaml config
# docker compose -f infra/compose/compose.yaml up --build
```

最终 Demo 发布前要有确证 HTTPS URL（无则不可宣称可公开访问）、访客配额、流量保护、管理员应急关闭入口、DB 备份与恢复演练、审计与隐私保留政策。
