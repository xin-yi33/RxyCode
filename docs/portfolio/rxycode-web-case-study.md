# 案例复盘：把 RxyCode 从单机 Agent 做成多租户 Web 工作区

分支：`feat/rxycode-web`。本文每个数字都带证据引用；缺测量的格子保留占位，不猜数。

## 一句话

在同一份 headless 核心（`Session`/`AgentV2`）之上长出：Postgres 持久化 run 队列 + fencing 租约、SSE exactly-once 事件重放、React 工作台、以及**共享 worker 里每个 run 一个内核沙箱**的部署形态——公网 Demo 永远跑不到本机 Full。

## 规模与工作量（均可核查）

- 48 张卡（W0×4, W1×5, W2×7, W3×7, W4×7, W5×6, W6×6, W7×6），每张独立 commit + `evidence/web/WEB-W*` 证据目录（证据: `evidence/web/`）。
- drain worker 单文件约 2400 行，承担认领/放置闸/沙箱 spawn/租约看门狗/投影/账本/终态（证据: `packages/rxycode-worker/src/rxycode_worker/drain.py`）。
- W7-C05 单卡经历 17 轮独立审计、累计 63 条发现全部修复（r1-r16 逐轮计数 8+7+5+5+5+3+2+3+3+3+3+3+4+4+4+1），终判 `VERDICT: NO_REMAINING_PROBLEMS`；全程同一会话 `gpt-6.1-sol` high 复审（证据: `evidence/web/WEB-W7-C05/self-audit.md`、`evidence/web/WEB-W7-C05/NOTES.md`）。
- 部署栈 9 个服务（postgres/redis/minio/reposync/migrate/api/worker/webbuild/gateway），全部端口绑定 loopback（证据: `infra/compose/compose.yaml`、`tests/web/w7/test_w7_c05_unit.py`）。

## 实测数字

- 宿主机真 provider 回合：一次 `local:`（旧直接路径）drain run 记录 input 9165 + output 1503 tokens，`assistant.final` 投影带真实 text（证据: `evidence/web/WEB-W7-C05/self-audit.md` 宿主机 smoke 段）。
- C05 聚焦测试（7 unit + 1 module，真实 compose 栈）：unit 296.64s，module 510.09s（证据: `evidence/web/WEB-W7-C05/green.txt` r3 run 段）。
- 沙箱内 turn 对死端点重试 6 次后按 60s run_timeout 诚实失败，`/proc` 零残留进程（证据: `evidence/web/WEB-W7-C05/green.txt` module 腿 + r3-fix live 段）。
- 综合 E2E 通过率 / 面试演示时长：TBD（证据缺口：apps/web 无 Playwright，浏览器腿 BLOCKED，见 `evidence/web/WEB-W7-C06/NOTES.md`）。

## 真实踩坑（非编造）

1. **Docker Desktop 挂不了 Windows bind mount** → 放弃 bind，改 `reposync` tar 灌卷 + `.rxy-sync-done` marker 排序；`up -d` 不死锁（证据: runbook + `evidence/web/WEB-W7-C05/NOTES.md`）。
2. **`docker compose exec` 输出是 UTF-8 而宿主 GBK** → `text=True` 解码炸掉 stdout；改 bytes 捕获显式 UTF-8（证据: `tests/web/w7/test_w7_c05_module.py::_compose` 注释）。
3. **bwrap 在容器里的三个真坑**：默认 seccomp 禁 `unshare`（→ worker 单列 `seccomp=unconfined`）；探测只绑 `/usr` 漏了 `/lib` 动态加载器（execvp ENOENT）；`/usr/local` 才是 slim 镜像的解释器前缀（证据: `evidence/web/WEB-W7-C05/self-audit.md` r3-fix 段）。
4. **审批面在部署栈不存在** → 不是"卡住"，是 confirm_all run 在 run_timeout 诚实 `failed`（证据: `docs/product/web-user-guide.md` FAQ）。
5. **账本可以静默丢** → usage 写失败并入 turn_error 并落 pending spool，succeeded 从此不能站在缺失行上（证据: `packages/rxycode-worker/src/rxycode_worker/drain.py` usage_error 路径 + `evidence/web/WEB-W7-C05/NOTES.md` r12-r16 审计记录）。

## 技术取舍（答辩口径）

- **为什么不给 worker docker.sock？** W5-C02 冻结：共享 worker 持 docker socket = 租户逃逸面；改为容器内 userns+bwrap。
- **为什么 turn 整个进沙箱而不是逐命令包裹？** 逐命令包不住 Python 进程内的文件 API——边界必须在进程粒度。
- **为什么拒绝 `local:*` 而不是"本地执行"？** 公网栈上 `local:` 意味着共享宿主文件系统——card 负测锁定"本机 Full 访问必须被拒"。
- **为什么限流在应用层？** stock `caddy:2` 无 limiter 插件；单副本 demo 进程内窗口足够，多副本需上移（已记录限制）。

## 两分钟演示脚本

所有命令在**仓库根目录**执行，compose 一律显式 `-f infra/compose/compose.yaml -p rxyweb`（仓库根部另有一个与本卡无关的遗留 `docker-compose.yml`）。

1. 起栈 + 播种（`up -d` 只拉起 marker 等待循环，`reposync` 不自流——tar 种子是必经步骤）：

   ```bash
   docker compose -f infra/compose/compose.yaml -p rxyweb up -d
   tar --exclude=.git --exclude=node_modules --exclude=__pycache__ \
       --exclude=dist --exclude=build -cf - . | \
     docker compose -f infra/compose/compose.yaml -p rxyweb exec -T reposync \
       sh -c 'tar -xf - -C /repo && touch /repo/.rxy-sync-done'
   ```

   栈健康后开 `https://localhost:8443`（证书警告=内部 CA，预期）。

2. **浏览器路径（需已配置 `RXYCODE_GITHUB_*` OAuth App）**：GitHub 登录 → `GET /api/v1/me` 拿到自动 provisioning 的 `tenant_id` → UI/REST 建 project+session 拿到 `session_id` → 用下面第 3 步的播种命令**把 run 种进自己的 tenant/session**（tenant 不匹配时 SSE/详情对调用方就是 404——这正是租户隔离）。

3. 播种 run（本版没有 run 创建的 HTTP 端点，`runs` 路由只有 GET/cancel/steer；`api` 容器内走 service 层）：

   ```bash
   docker compose -f infra/compose/compose.yaml -p rxyweb exec -T api python - <<'PY'
   import os
   from sqlalchemy import create_engine
   from sqlalchemy.orm import Session
   from sqlalchemy.pool import NullPool
   from rxycode_server.persistence.models import SessionRow
   from rxycode_server.runs.service import create_run

   dsn = os.environ["RXYCODE_WEB_DATABASE_URL"]
   tenant = "<来自 /api/v1/me 的 tenant_id>"       # 路径 A
   session_id = "<登录后创建 session 拿到的 id>"     # 路径 A
   # 路径 B（无 OAuth，纯后端演示）：自行插入 tenant/session 行后照旧调用。
   create_run(dsn, tenant_id=tenant, session_id=session_id,
              message="demo durable run",
              target_id=f"cloud:{tenant}:w1",
              permission_profile="auto_edit", request_id="demo-req-1")
   PY
   ```

   `cloud:` 目标段的 tenant 必须等于 run 的 `tenant_id`，否则放置闸拒收。

4. 演示恢复：kill worker → 租约到期 → 新 worker 接管（epoch+1 可见于 `runs` 行）。
5. 演示拒绝：播种 `local:*` run → `run.error`+`failed`，无 `event/agent_started`。
6. 演示账本：`usage.updated` 行 + run 事件流 SSE 重放（`GET /api/v1/runs/{id}/events`，登录态浏览器或带 cookie 的 curl）。

**无 OAuth 时**：步骤 2/6 的浏览器面标 BLOCKED——退化为纯后端演示：直接 `docker compose -f infra/compose/compose.yaml -p rxyweb exec -T postgres psql -U rxycode -d rxycode` 查 `runs`/`run_events`/`usage_records` 三表验证持久化、租约接管与账本，不伪造前端截图。

演示录屏：BLOCKED（无 Playwright 依赖；不剪辑假场景）。
