# RxyCode web — self-hosted compose runbook (WEB-W7-C05)

Stack file: `infra/compose/compose.yaml` + `infra/compose/Caddyfile`.
Everything below was executed against this checkout on Docker Engine 29.7.2 /
Compose v5.5.1. Commands are run from the **repo root**.

## Topology

```
browser --https(8443)--> gateway (caddy:2.11, TLS internal CA)
                          |-- /api/*  -> api:8000  (SSE + WS included)
                          '-- /*      -> /srv/www  (vite dist from `webbuild`)
api (python:3.12-slim, uvicorn on rxycode_server.main.serve(mode=cloud))
worker (python:3.12-slim, `python -m rxycode_worker.drain` — durable queue
        consumer: claim -> placement gate -> per-run userns sandbox turn ->
        terminal commit. Every executed turn runs INSIDE a bubblewrap
        user/pid/ipc/uts namespace; the worker host never runs agent code)
migrate (one-shot: rxycode_server.persistence.migrate.upgrade_head)
webbuild (one-shot: node:22-slim, npm install + npm run build -> web-dist vol)
postgres:16 | redis:7 | bitnamilegacy/minio:2025.7.23 (named volumes)
```

Honest notes:

- The durable spine is `rxycode_worker.supervisor.claim/commit_terminal`
  plus the `outbox` table, and the worker service is a real consumer:
  `rxycode_worker.drain` polls `runs` for claimable rows (`pending`, or a
  dead worker's expired lease), takes the fenced lease, reads the persisted
  message with `load_run`, and spawns the turn as a confined child process.
  Journaling, telemetry spans and the usage ledger all land on the run's own
  event log. Its healthcheck proves the drain is PID 1 *and* can reach
  Postgres.
- **Turn isolation (public rule)**: `RXYCODE_WORKER_EXECUTION=cloud-only`
  means only `cloud:{tenant}:{workspace}` targets execute — the tenant
  segment must equal the run's own `tenant_id` (a cross-tenant target is
  refused). Permission profile is an approval semantic only:
  `full`/`full_auto` maps to the existing no-approval `full_auto` mode
  INSIDE the same sandbox — it can never widen mounts, network, or the
  writable domain. Accepted targets run inside `rxycode_runner.sandbox.userns`
  (bubblewrap): `--unshare-user --unshare-pid --unshare-ipc --unshare-uts
  --unshare-net`, `--clearenv` + an explicit setenv passlist, system paths
  and the checkout read-only (optional task-private tmpfs overlays for
  package installs), the per-tenant workspace plus a task-private home
  and control dir writable, `--die-with-parent` tree reaping on
  cancel/stop. The agent's tool calls happen inside that namespace —
  sibling workspaces and the worker's own data dir are simply not mounted.
  Control-plane credentials never enter the sandbox: events, run reads,
  steer commands and durable approvals travel the parent-owned UNIX
  control socket (`rxycode_worker.ctl`), and outbound connectivity rides
  a private net namespace whose only door is the parent's filtered
  CONNECT proxy (`rxycode_worker.egress` + `netrelay`) — metadata,
  private ranges and non-80/443 egress die there for every profile.
  If bwrap/userns is missing the provider raises
  `IsolationUnavailable` and the run fails honestly; there is no host
  fallback. The worker's `security_opt: seccomp=unconfined` exists solely
  because Docker's default seccomp profile forbids the `unshare`/`mount`
  syscalls userns needs — it grants no capability, no privileged flag and
  no docker.sock. When a real cloud sandbox broker (VM/gVisor provider)
  lands, it replaces `userns` behind the same `SandboxProvider` contract —
  the gate, lease and commit flow do not change.
- The api/worker/migrate images are stock `python:3.12-slim`; the checkout is
  **not** bind-mounted — it is streamed as a tar into the shared `repo-src`
  volume through the `reposync` service (see Bring-up). That keeps the stack
  working on Docker Desktop hosts that cannot mount host paths. The worker
  copies `/repo-src` to a writable `/repo` because appserver state can write;
  a `/opt/pkg` shim makes `RxyCode.RxyCode1_1_0.*` importable. Rebuilding an
  image is *not* required — but the first cold `up` pays a few minutes of
  `pip install`/`npm install` inside the api/worker/webbuild containers.
- The deployed api boots through `rxycode_server.main.serve()`, not bare
  `create_app`: `mode=local` on a non-loopback bind is refused by
  `reject_as_public_web_gateway`, so `RXYCODE_WEB_MODE=local` cannot weaken
  the deployed stack — the same guard the negative test exercises.

## Environment

No `.env` file is shipped. Export (or pass inline) per deploy:

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `RXYCODE_POSTGRES_PASSWORD` | yes | — | `POSTGRES_PASSWORD`; also embedded in `RXYCODE_WEB_DATABASE_URL` |
| `RXYCODE_MINIO_ROOT_USER` / `_PASSWORD` | yes | — | artifact store root creds |
| `RXYCODE_WEB_SECRET` | yes | — | session/CSRF secret; ≥32 chars, ≥10 distinct |
| `RXYCODE_WEB_MODE` | no | `cloud` | gateway mode (`local` must not be exposed) |
| `RXYCODE_WEB_ORIGINS` | no | `https://localhost:8443` | CSRF Origin allowlist (comma-separated) |
| `RXYCODE_GITHUB_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | no | empty | real GitHub OAuth app for cloud login |
| `RXYCODE_S3_ENDPOINT` / `_BUCKET` | no | `http://minio:9000` / `rxycode-artifacts` | artifact store |
| `RXYCODE_PREVIEW_TOKEN` | no | empty | optional extra preview-token check at the gateway |
| `RXYCODE_WEB_RATE_LIMIT_RPM` | no | `240` | public-demo throttle: requests/min per client IP at the app layer; `0` disables |
| `RXYCODE_WEB_REGISTRATION` | no | `invite` | registration mode: `invite` requires a one-shot code (mint via `python -m rxycode_server.admin invite create`), `open` allows anyone, `closed` refuses all registration |
| `RXYCODE_QUOTA_CONCURRENCY` | no | `1` | per-user active-run ceiling |
| `RXYCODE_QUOTA_TASKS_PER_DAY` / `RXYCODE_QUOTA_TOKENS_PER_DAY` | no | `30` / `2000000` | per-user rolling-24h task count / real token usage (`usage_records` sum) |
| `RXYCODE_QUEUE_MAX` | no | `10` | global pending-run cap; extra submissions refuse with `QUOTA_EXCEEDED`/`queue` |
| `RXYCODE_WORKER_ID` / `_POLL_SECONDS` / `_LEASE_TTL` / `_MODEL` | no | hostname / `2` / `120` / active | drain worker tuning |
| `RXYCODE_WORKER_EXECUTION` | no | `cloud-only` | placement gate: `cloud-only` accepts only tenant-bound `cloud:*` targets (the shipped public mode); `sandboxed-local` is the dev opt-in that also accepts `local:*` — still confined |
| `RXYCODE_LLM_BASE_URL` / `RXYCODE_LLM_MODEL` | no | empty | the PLATFORM model endpoint (openai-compatible). Under BYOK only runs by `RXYCODE_PLATFORM_MODEL_USERS` consume it — ordinary users run on their own sealed keys. `RXYCODE_LLM_MODEL` is also the display name the API reports for the platform model (never the key) |
| `RXYCODE_API_KEY` | no | empty | credential for the platform endpoint above; optional under BYOK. Parent-side only — injected by the egress gateway, never written into config.yaml or the sandbox |
| `RXYCODE_BYOK_KEYRING_FILE` | yes (api+worker, cloud) | — | path to the BYOK keyring JSON (`{"active","keys"}` of base64 32-byte AES keys). Generate once on the host: `python -m rxycode_server.byok.keyring generate /opt/rxycode/secrets/byok-keyring.json` (creates mode 0600, refuses overwrite). Missing/unreadable → 503 `BYOK_UNAVAILABLE`, never a plaintext fallback. Both api and worker containers run as uid 0 → host file `root:root 0600` suffices |
| `RXYCODE_BYOK_ENFORCE` | no | api: on in `cloud` mode / worker: on | `0` restores legacy behavior (no model → env/platform gateway) |
| `RXYCODE_PLATFORM_MODEL_USERS` | no | empty | comma-separated immutable user ids allowed to submit `model_ref: "platform"`; re-checked by the worker at execution time. Empty = nobody can spend the platform key |
| `RXYCODE_BYOK_ALLOW_PRIVATE` | no | off | dev/test only — permits `http://` and private/loopback BYOK base URLs. Never set in prod |
| `RXYCODE_PG_PORT` / `RXYCODE_HTTP_PORT` / `RXYCODE_HTTPS_PORT` | no | `54433` / `8080` / `8443` | loopback-published ports |
| `RXYCODE_SMTP_URL` | no | empty | password-reset delivery — `smtps://user:pass@host:465` (implicit TLS) or `smtp://…:587` (STARTTLS). Without it `/forgot` stays hidden in cloud mode |
| `RXYCODE_SMTP_FROM` | no | SMTP user | sender header on reset mail |

Password reset: `/forgot` always answers 200 with the same body (no account
enumeration). The link is a single-use HMAC-digested row valid 30 minutes;
redeeming it rewrites the password and revokes every session of that user.
With no SMTP configured the flow is only reachable in `local` dev mode,
which returns the link inline in the response.

Example:

```bash
export RXYCODE_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RXYCODE_MINIO_ROOT_USER=rxy-minio
export RXYCODE_MINIO_ROOT_PASSWORD="$(openssl rand -hex 24)"
export RXYCODE_WEB_SECRET="$(openssl rand -hex 32)"
export COMPOSE_PROJECT_NAME=rxyweb
```

## Bring-up

```bash
# from repo root; pick a project name that is NOT a rxy-* dev container
docker compose -f infra/compose/compose.yaml -p rxyweb up -d

# Seed the checkout into the repo-src volume (the .rxy-sync-done marker is the
# gate every service waits on). Without this step the stack idles by design.
tar --exclude=.git --exclude=node_modules --exclude=__pycache__ \
    --exclude=dist --exclude=build -cf - . | \
  docker compose -f infra/compose/compose.yaml -p rxyweb exec -T reposync \
    sh -c 'tar -xf - -C /repo && touch /repo/.rxy-sync-done'

docker compose -f infra/compose/compose.yaml -p rxyweb ps -a
```

Ordering is by marker files on shared volumes, not blocking `depends_on`
conditions, so `up -d` returns immediately and seeding happens after:

- `reposync` exits once `.rxy-sync-done` appears in `repo-src`.
- `migrate` waits for the marker, runs `upgrade_head` against the project
  Postgres, then drops `.migrate-done` into the `boot-state` volume.
- `api` and `worker` wait on `.migrate-done` before starting their real
  processes; `gateway` waits for `index.html` in `web-dist` (dropped by
  `webbuild`). Once everything is green the gateway serves:

- `https://localhost:8443/` — built SPA (vite `dist`, not the dev server)
- `https://localhost:8443/api/v1/*` — proxied to `api:8000`
- `http://localhost:8080/` — plain HTTP, redirects to HTTPS

Healthcheck detail:

- `postgres`: `pg_isready -U rxycode -d rxycode` inside the container
- `api`: `GET /api/v1/auth/csrf` == 200 (app layer) **and** `SELECT 1`
  against `RXYCODE_WEB_DATABASE_URL` (durable layer)
- `worker`: `/proc/1/cmdline` is `rxycode_worker` **and** `SELECT 1` on the same DSN
- `gateway`: Caddy admin API on loopback `:2019` answers

## Migrations

`migrate` is a one-shot job (restart policy `no`) — it runs automatically on
`up` and is **idempotent** (`alembic upgrade head`). To re-run by hand after
pulling new revisions:

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb run --rm migrate
docker compose -f infra/compose/compose.yaml -p rxyweb exec postgres \
  psql -U rxycode -d rxycode -c 'select version_num from alembic_version'
```

Head for this card: revision `004` (`004_waiting_approval`).

## Certificates

`tls internal` signs `localhost` with Caddy's internal CA, persisted in the
`caddy-data` volume. The API itself is HTTP behind the gateway; TLS ends at
Caddy, which is also where `proxy_headers` re-asserts `https` to FastAPI.

Trust the demo cert in a browser:

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb \
  cp gateway:/data/caddy/pki/authorities/local/root.crt ./rxycode-local-root.crt
# then import rxycode-local-root.crt into the OS/browser trust store
```

`curl`/`httpx` verification without trusting that CA fails — expected: the
test suite asserts both directions (verify=False succeeds, verify=True
refuses). For a public deploy, replace `tls internal` with a real domain +
ACME or mounted cert files; the runbook steps otherwise stand.

## Preview-auth seam

`/api/v1/previews/{sandbox}/{port}/…` is owner-authenticated by the app
(`previews.proxy` + `current_record`). Setting `RXYCODE_PREVIEW_TOKEN` adds a
second gate at Caddy: preview requests must carry `X-Preview-Token: <token>`
or get `403` before reaching the API. Empty env ⇒ the gateway defers to app
auth. Rotate by changing the env and `up -d` (Caddy reloads the Caddyfile on
recreate only — force it with `docker compose ... up -d --force-recreate gateway`).

## Logs

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb logs -f api
docker compose -f infra/compose/compose.yaml -p rxyweb logs --tail=200 worker
docker compose -f infra/compose/compose.yaml -p rxyweb logs migrate webbuild
docker compose -f infra/compose/compose.yaml -p rxyweb logs gateway --since 10m
```

api/worker pip output is the bring-up story; a worker that keeps restarting
usually means a missing pip dep — read its `logs` before anything else.

## Restart / recovery (断电)

- `docker compose -p rxyweb restart postgres api` — exercised by
  `tests/web/w7/test_w7_c05_module.py`: run rows + events survive on the
  `pg-data` volume; a stale lease (`lease_until` in the past) is re-claimed
  by a fresh `worker_id`, which bumps `lease_epoch` and commits terminal.
- `docker compose -p rxyweb down` (no `-v`) keeps `pg-data`; `up -d` resumes.
- `docker compose -p rxyweb down -v` drops the volumes — the full wipe path.
- The api's bootstrap is idempotent (pip "already satisfied" → uvicorn), so a
  restarted api re-passes health without operator input.

## Upgrade (new source on a running stack)

App services execute the checkout seeded into `repo-src` — `up -d` alone does
**not** refresh it, and leftover markers would release the old waits
instantly. The upgrade sequence therefore clears both markers, reseeds,
re-migrates and rebuilds before recreating consumers:

```bash
COMPOSE="docker compose -f infra/compose/compose.yaml -p rxyweb"

# 1. Stop consumers so nothing boots against a half-swapped tree
$COMPOSE stop api worker gateway

# 2. Clear the ordering markers — a stale marker would release api/worker on
#    old code. `run --no-deps` mounts the same volumes in a throwaway
#    container (reposync/migrate are one-shot; `exec` needs a running one).
$COMPOSE run --rm --no-deps -T migrate sh -c 'rm -f /boot/.migrate-done'

# 3. Reseed repo-src as an EXACT copy of the new checkout: a plain
#    `tar -xf -` overlay would keep files the new revision deleted (stale
#    modules, stale migration revisions). Empty the volume first, then
#    stream the tar — its final entry is the `.rxy-sync-done` marker.
$COMPOSE run --rm --no-deps -T reposync sh -c 'find /repo -mindepth 1 -delete'
tar --exclude=.git --exclude=node_modules --exclude=__pycache__ \
    --exclude=dist --exclude=build -cf - . | \
  $COMPOSE run --rm --no-deps -T reposync sh -c 'tar -xf - -C /repo'
git rev-parse HEAD | $COMPOSE run --rm --no-deps -T reposync \
  sh -c 'cat > /repo/.rxy-sync-done'

# 4. Re-run migrations and rebuild the SPA against the new source (drop the
#    stale index.html first so a restarting gateway can never serve it)
$COMPOSE run --rm --no-deps -T webbuild sh -c 'rm -f /dist/index.html'
$COMPOSE run --rm --no-deps migrate
$COMPOSE run --rm --no-deps webbuild

# 5. Recreate the long-running services — api/worker wait on the fresh
#    .migrate-done, gateway on the fresh index.html
$COMPOSE up -d --force-recreate api worker gateway
```

## Rollback

Same sequence pinned to the previous checkout (`git checkout <prev-ref>` first,
then steps 1–5). If a bad schema revision shipped, downgrade after the reseed
(`run` overrides the service command, so redo the tiny pip bootstrap first):

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb run --rm --no-deps \
  --entrypoint sh migrate -c "
    pip install --quiet --no-input 'sqlalchemy>=2,<2.1' 'alembic>=1.17,<2' 'psycopg[binary]>=3.2,<4' &&
    python -c \"import os; from rxycode_server.persistence.migrate import downgrade_base; downgrade_base(os.environ['RXYCODE_WEB_DATABASE_URL'])\""
```

(`downgrade_base` drops to base — destructive; prefer `command.downgrade` to a
named revision via the same module when you only need one step back.)

## Boundaries this stack does NOT cross

- **Cloud login** needs a real GitHub OAuth app (`RXYCODE_GITHUB_*`). Without
  it the UI reaches the login page and stops — everything else still serves.
- **A cloud run that really executes** needs a real endpoint: set
  `RXYCODE_LLM_BASE_URL`/`RXYCODE_LLM_MODEL`/`RXYCODE_API_KEY` so the worker
  writes a real model entry and `Session.prompt` reaches your provider. The
  drain worker claims the durable run and drives the turn inside the per-run
  userns sandbox — no stdio client needed. Without a reachable endpoint the
  run still reaches a real terminal state (`failed`, not a fabricated
  `succeeded`), recorded by `test_w7_c05_module`. `local:*` targets are
  refused on this stack by design; `full`/`full_auto` profiles resolve to
  the no-approval `full_auto` mode inside the same sandbox (isolation is
  never an approval decision). On a development host set
  `RXYCODE_WORKER_EXECUTION=sandboxed-local` to let `local:*` drain
  (still confined — the drain never executes unconfined).
- The compose Postgres is for the web stack — the dev containers
  (`rxy-w2c01-pg` etc.) are untouched; use a distinct `-p` project name and
  the shipped loopback ports so nothing collides.

## 本地开发（W9-F3）

Windows 本机开发不用起整套 compose：

```powershell
# 终端 1：dev Postgres (rxy-web-dev-pg @ 127.0.0.1:55440) + alembic head + API
pwsh -File infra/scripts/web-dev.ps1        # API on http://127.0.0.1:8000
# 终端 2：Vite dev server（/api 代理到 8000，见 vite.config.ts 的
# VITE_API_TARGET，默认 http://127.0.0.1:8000）
npm --prefix apps/web run dev               # UI on http://127.0.0.1:5173
```

- 脚本幂等：`rxy-web-dev-pg` 存在就复用；密钥第一次生成后存
  `%USERPROFILE%\.rxycode\web-dev.secret`，重开终端不变。
- `RXYCODE_WEB_REGISTRATION=open`，/register 页面不需要邀请码即可注册。
- 开发机没有 drain worker：提交的 run 会一直停在 **排队中**，这是预期行为。
- 不要动 `rxydemo-*` 容器；dev 库与 `rxy-w9-pg`(55439)/W3 库(55432) 端口隔离。

## 生产部署（自托管 + Tailscale Funnel）

对应计划 W10-D2/D3。生产栈 = `compose.yaml` + `compose.prod.yaml` 叠加，
使用 D1 构建的 `rxycode-{api,worker,web}` 镜像；启动不再联网装依赖，
也没有 repo-src / marker 文件。对外只经 Tailscale Funnel，公网地址固定为
`https://<机器名>.<tailnet名>.ts.net`（不支持自定义域名）。

### 前置条件（运营者本人完成，AI 不能代办）

- Windows 主机已安装 Tailscale 客户端并登录；管理后台 DNS 页确认
  MagicDNS 与 HTTPS 证书已开启、Funnel 已启用；记下
  `<机器名>.<tailnet名>.ts.net`（可在后台把机器名改成好记的，如 rxycode）。
- `%USERPROFILE%\.wslconfig` 已创建且 `[wsl2] memory` ≥ 6GB（建议 8GB），
  已重启 WSL/Docker Desktop——现有 ~2G 虚拟机跑不了真实任务。
- Docker Desktop 数据盘已迁到 D 盘（Settings → Resources → Disk image
  location）；C 盘空间不足时镜像构建会失败。
- 主机关闭自动睡眠；Docker Desktop 设为开机自启（容器均
  `restart: unless-stopped`）。
- 模型 API key（`RXYCODE_API_KEY`）与 openai 兼容端点
  （`RXYCODE_LLM_BASE_URL`）已就绪。
- 镜像已构建：`pwsh -File infra/scripts/build-images.ps1`
  （`rxycode-{api,worker,web}:<git-sha>` + `:latest`）。

### 步骤

```powershell
# 1. 在仓库外创建 .env（参照 infra/compose/.env.prod.example 逐项填写；
#    必填项缺失时 compose config 直接报错）
copy infra\compose\.env.prod.example D:\rxycode-prod\.env
#    编辑 D:\rxycode-prod\.env —— RXYCODE_WEB_ORIGINS 填
#    https://<机器名>.<tailnet名>.ts.net

# 2. 启动（独立 project 名 rxyprod，与 rxydemo 互不干扰；
#    migrate 一次性任务先跑 alembic upgrade head，api/worker 等它成功）
docker compose -p rxyprod --env-file D:\rxycode-prod\.env `
  -f infra\compose\compose.yaml -f infra\compose\compose.prod.yaml up -d

# 3. 本地自检（gateway 只绑主机回环；本条必须在公网开放之前通过）
curl http://127.0.0.1:8080/api/v1/auth/csrf        # 期望 200
docker compose -p rxyprod --env-file D:\rxycode-prod\.env `
  -f infra\compose\compose.yaml -f infra\compose\compose.prod.yaml ps

# 4. 开放 Funnel（--bg 使配置在重启后保留）
tailscale funnel --bg --https=443 http://127.0.0.1:8080
tailscale funnel status                            # 确认已公开

# 5. 沙箱自检：worker 日志中确认 userns/bwrap 可用；不可用则 worker 必须
#    拒绝执行（IsolationUnavailable），不允许退回宿主执行
docker compose -p rxyprod --env-file D:\rxycode-prod\.env `
  -f infra\compose\compose.yaml -f infra\compose\compose.prod.yaml logs worker

# 6. 创建邀请码（明文只打印一次，请记录）
docker compose -p rxyprod --env-file D:\rxycode-prod\.env `
  -f infra\compose\compose.yaml -f infra\compose\compose.prod.yaml `
  run --rm api python -m rxycode_server.admin invite create --uses 5 --days 14

# 7. 每日备份（Windows 任务计划程序，示例命令见下节）
```

### 验收（E-1 / E-2 / E-3，生产栈上执行）

用**手机流量**（不要连家里 Wi-Fi、不要在手机上登录 Tailscale）打开
`https://<机器名>.<tailnet名>.ts.net`：

- **E-1 身份**：邀请码注册 → 跳 `/app` → 刷新仍登录 → `docker restart` api
  容器后刷新仍登录 → 退出 → 后退键看不到数据。
- **E-2 主任务**：首页提交一个真实任务（如"创建 hello.py 并运行"）→
  时间线顺序正常、Markdown Final 渲染、状态到"已完成"且 SSE 关闭；
  **运行超过 5 分钟时 SSE 不断流**（验证 Funnel 长连接链路）。
- **E-3 审批**：同一会话用"每步确认"再提交一个改动任务 → 审批卡出现 →
  批准 → 续接 → 能看到上一次 run 的文件。
- **待验证（D2 卡片）**：在 api 日志确认记录的客户端 IP 是手机公网 IP
  而非 Docker 网关地址。拿不到真实 IP 时所有用户共用一个限流桶，须调大
  `RXYCODE_WEB_RATE_LIMIT_RPM` 并依赖按邮箱/账户的限流与额度兜底。

### 备份与恢复

- 备份（在线执行，pg_dump 是一致性快照；建议每日，经任务计划程序）：

  ```
  schtasks /create /tn "RxyCode-Backup" /sc daily /st 03:00 /tr ^
    "\"C:\Program Files\Git\bin\bash.exe\" D:\agent-demo\RxyCode\RxyCode1_1_0\infra\scripts\backup.sh -p rxyprod --env-file D:\rxycode-prod\.env"
  ```

  产物在 `RXYCODE_BACKUP_DIR`（默认 `D:\rxycode-backups`）下
  `<project>\<时间戳>\`：`postgres.pgdump`（-Fc 格式）+ `volumes\*.tar.gz`
  （worker-data 工作区、minio-data、redis-data、caddy-*；pg-data 由 dump
  覆盖不再裸打包；repo-src/boot-state/web-dist 等 dev 卷跳过），只保留
  最近 7 份。

- 恢复（栈必须先停：`**down** 不带 -v`，脚本在栈运行时拒绝执行）：

  ```bash
  docker compose -p rxyprod --env-file 'D:\rxycode-prod\.env' \
    -f infra/compose/compose.yaml -f infra/compose/compose.prod.yaml down
  infra/scripts/restore.sh -p rxyprod --env-file 'D:\rxycode-prod\.env' \
    'D:\rxycode-backups\rxyprod\<时间戳>'
  # 脚本恢复卷 → 单独拉起 postgres 做 pg_restore --clean → 停掉 → 手动 up -d
  ```

### 暂停新任务 / 回滚 / 重启恢复

- **暂停新任务（kill switch）**：`.env` 中设 `RXYCODE_QUEUE_MAX=0` 后
  `up -d` —— 新提交一律 429 QUOTA_EXCEEDED，运行中任务不受影响。
- **回滚**：镜像按 git sha 打标签，回滚 = 改 `.env` 的
  `RXYCODE_IMAGE_TAG=<上一个 sha>` → `up -d`（必要时先
  `run --rm migrate` 处理 schema 方向）。
- **重启恢复**：容器 `restart: unless-stopped` + Docker Desktop 自启 +
  `funnel --bg` 持久化——主机重启后整个栈和 Funnel 自动恢复。
