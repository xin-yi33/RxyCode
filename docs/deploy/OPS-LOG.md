# RxyCode 运维操作日志（OPS LOG）

> 用途：记录 agent 对仓库 / 本机 / VM / 线上环境的**每一次实际操作**——做了什么、在哪台机器、用什么方式、结果如何。
> 规则：之后每个动作完成后立即追加一条（倒序，最新在最前）；只写事实不写秘密（密码、key 一律不写值，只写"已配置"/"在 .env"）。
> 环境记号：🪟=Windows 宿主 / 🐧=CentOS VM(192.168.88.128, SSH ruanxinyi) / 📦=Docker 容器 / 📁=仓库 `D:\agent-demo\RxyCode\RxyCode1_1_0` / 👤=用户本人操作。

---

## 2026-10-21

### 10:55 📁 ops log 建立
- 本文档创建。此前操作按记忆补齐（见下，均为当日发生）。

### ~10:30 🪟📁 本机演示栈上线（给你看效果用）
- `rxylocal` compose 项目在本机 Docker Desktop 启动：`compose.yaml + compose.prod.yaml` + 本地 env（Temp 目录，不落仓库）。
- 服务：`http://localhost:8081`（8080 被旧 rxydemo 占用）。注册开放。镜像 `rxycode-*:3bdaa734`（与 VM 相同）。
- 验证：`/api/v1/version` → `{"commit":"3bdaa734"}`，SPA 200，api/worker/gateway/pg/redis/minio 全 healthy。
- ⚠️ 旧 `rxydemo` 栈（10-20 旧代码）仍在 8080 运行，未动。

### ~10:15 📁 提交 `29087f71`
- `infra/docker/worker.Dockerfile` 基座 `python:3.12-slim` → `python:3.12-slim-bookworm`（bwrap 0.8），+ changelog 记录。未推送。

### ~10:00 🪟→🐧📦 worker 镜像修复并部署
- 本地重建 `rxycode-worker:3bdaa734`（bookworm/bwrap 0.8）→ docker save → SFTP → VM `docker load` → `compose up -d worker` 重建容器 → `bwrap --version` = 0.8.0。
- **API 冒烟（api 容器内走 `http://gateway` 全链路）**：注册 201 / `/me` 200 / 登录 200 / forgot 200 / `POST /api/v1/tasks` 202 → run `7347a13d…` 终态 **succeeded**（~160s，442 事件，32 次工具调用，`hello.txt` 落沙箱工作区，门禁回执 exit 0）。
- 根因备忘：bwrap≥0.10 用 `open_tree`/`move_mount`（kernel≥5.2），CentOS7 的 3.10 上 ENOSYS → `userns_available()` 失败 → run 诚实拒绝（fail-closed 按设计工作）。bwrap 0.8 用经典 `mount()` 通过。

### ~09:50 🐧 内核参数 + 首次 run 失败诊断
- `user.max_user_namespaces` CentOS7 默认为 0 → `sysctl -w …=15000` + 写 `/etc/sysctl.d/99-rxycode.conf` 持久化。
- 首次冒烟 run `7c71ac6d…` → `failed`：`userns/bwrap isolation is unavailable`（即上述 bwrap 0.12 ENOSYS）。

### ~09:45 🐧 生产栈首次上线
- `/opt/rxycode/` 落位：`compose.yaml`、`compose.prod.yaml`、`Caddyfile.prod`、`.env`(600，含生成的 pg/minio/web secret 与 deepseek key，`RXYCODE_IMAGE_TAG=3bdaa734`，`RXYCODE_WEB_REGISTRATION=open`)。
- `docker compose -p rxyprod up -d`：postgres/redis/minio healthy → migrate Exited(0)（alembic 007 head）→ api/worker healthy → gateway 绑 `127.0.0.1:8080`。
- 验证：`/api/v1/version` → `3bdaa734`。

### ~09:40 🪟→🐧📦 镜像传输
- 本地 `infra/scripts/build-images.ps1` 构建三镜像 `rxycode-{api,worker,web}:3bdaa734` → `docker save` 397M → SFTP → VM `docker load` ✓。
- VM 侧四个基础镜像经代理拉取完成：postgres:16 / redis:7 / caddy:2.11 / bitnamilegacy/minio:2025.7.23。

### ~09:30 🐧 dockerd 代理配置
- `/etc/systemd/system/docker.service.d/proxy.conf`：`HTTP(S)_PROXY=http://192.168.88.1:10808`（Windows 宿主 FlClash 混合端口），`NO_PROXY` 含内网段与容器名 → `systemctl daemon-reload && restart docker` → `hello-world` 拉通。
- 直连测试：`api.deepseek.com` 裸连 401（可达），代理 401（也可达）→ 容器不配代理。

### ~09:20 🐧 VM 基线
- VM：`D:\python study\Linux\CentOS 7 64 位.vmx`，CentOS 7.6 / kernel 3.10.0-957 / 4C8G / NAT `192.168.88.128`。
- Docker 26.1.4 + Compose v2.27.1 已装；`/etc/yum.conf` 加 `proxy=http://192.168.88.1:10808`。

### ~09:10 🐧 Tailscale
- `tailscale` 1.104.2 经官方 el7 repo 安装，`tailscaled` enable+start。
- `tailscale up --hostname=rxycode` → 授权链接交给用户。
- 👤 用户在浏览器完成授权（待 subagent 核实 tailnet 名并开 Funnel）。

---

### ~11:35 📁🪟 忘记密码"运营者日志"投递（免 SMTP）
- 需求：用户不愿配 Gmail 应用密码 → 加了免凭据回退。
- 代码：`auth.py` forgot 新增 operator-log 分支（`RXYCODE_RESET_OPERATOR_LOG=1` 开）；capabilities 加 `reset_delivery` 四态；`main.py` 读 env；compose.prod 传参；`.env.prod.example` 文档化。
- 前端：ForgotPasswordPage 按 `delivery` 显示"从服务器日志获取"文案。
- 验证：`test_password_reset.py` 8 passed（含新 operator-log 用例）；本机 `rxylocal` 实测 capabilities=`operator-log`、forgot→`{"ok":true,"delivery":"operator-log"}`、api 日志里出现真实重置链接。
- 镜像 `rxycode-{api,web}:29087f71` 已构建；本机 8081 已是新版。VM 侧 `.env` 待加 `RXYCODE_RESET_OPERATOR_LOG=1`（随下次镜像推送一并下发）。

### ~11:10 🐧 公网 IP + cloudflared
- 直连出口 IP：**27.47.3.180**；代理出口：203.10.99.26（节点位置）。
- `cloudflared` 2026.10.2 已装（官方 rpm）。`cloudflared tunnel login` 已 setsid 常驻等浏览器回调（cert.pem 将落 `~/.cloudflared/`），授权链接已给用户。
- ⚠️ Tailscale 状态实为登出——早先 `tailscale up` 进程超时被杀、auth key 作废；已生成新登录链接给用户。

## 待续区（接下来的操作实时追加）

- [ ] Funnel `--bg` → origins 改 `https://rxycode.<tailnet>.ts.net` → api 重建 → 公网验证
- [ ] cloudflared 授权回来后：tunnel create → `rxycode.xyz` route → 接入 8080 → 公网验收
- [ ] SMTP / 重置链接投递方案（等用户选 Gmail 应用密码 或 日志回退）
- [ ] Funnel 域名浏览器全流程验收
