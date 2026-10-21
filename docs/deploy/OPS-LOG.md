# RxyCode 运维操作日志（OPS LOG）

> 用途：记录 agent 对仓库 / 本机 / VM / 线上环境的**每一次实际操作**——做了什么、在哪台机器、用什么方式、结果如何。
> 规则：之后每个动作完成后立即追加一条（倒序，最新在最前）；只写事实不写秘密（密码、key 一律不写值，只写"已配置"/"在 .env"）。
> 环境记号：🪟=Windows 宿主 / 🐧=CentOS VM(192.168.88.128, SSH ruanxinyi) / 📦=Docker 容器 / 📁=仓库 `D:\agent-demo\RxyCode\RxyCode1_1_0` / 👤=用户本人操作。

---

## 2026-10-21

### ~13:25 🐧 Gmail SMTP 打通：MAIL 专用组 + smtp-relay 重指 mihomo
- 逐节点扫测（`node_smtp_sweep.py`，56 节点）：绝大多数机场节点封 465/587；**仅 `香港高速02`/`03`（BGP/CMCU）放行 Gmail SMTP**。
- `/etc/mihomo/config.yaml` 新增 `MAIL` select 组（`filter: 香港高速0[23]`）+ 规则 `DOMAIN-SUFFIX,smtp.gmail.com,MAIL` 置于 GEOIP 之前——只让 Gmail 流量固定走 HK02，其余流量仍 AUTO。
- `smtp-relay` 重建：上游从 FlClash(`192.168.88.1:10808`) 改为 mihomo(`192.168.88.128:7890`)；mihomo 日志确认 `smtp.gmail.com:465 → MAIL[香港高速02]`。
- 实测链路 api→relay→mihomo→HK02→Gmail：`TLS_OK` + `220 smtp.gmail.com ESMTP ... gsmtp` 连续 3/3。
- `.env` 恢复 `RXYCODE_SMTP_URL/_FROM`（Gmail 应用密码）+ `RESET_OPERATOR_LOG=1` 兜底；forgot API 返回 200，SMTP 投递已发出（待用户查收件箱/垃圾箱确认）。

### ~13:10 🐧 VM 自带加速器：mihomo v1.19.32 + metacubexd 面板
- 安装 `mihomo-linux-amd64-compatible-v1.19.32`（GOAMD64=v1 兼容老 CPU）→ `/usr/local/bin/mihomo`；面板 metacubexd → `/etc/mihomo/ui`（mihomo SAFE_PATHS 只放行 workdir `/etc/mihomo` 之下，`/opt/mihomo/ui` 被拒，已挪）。
- `/etc/mihomo/config.yaml`：mixed-port `7890`（allow-lan）、external-controller `0.0.0.0:9090` + secret、dns `:1053`、当前 `MATCH,DIRECT`（等订阅）。
- `/opt/mihomo/apply-sub.sh <订阅URL>`：写入 proxy-providers + PROXY/AUTO 分组（GEOIP,CN 直连，其余走代理）并重启 mihomo。
- systemd `mihomo.service` enabled+active；面板 `http://192.168.88.128:9090/ui`（Windows 侧实测 200）。
- 待用户给订阅 URL → apply-sub 接节点 → 之后 VM 可直接用 `127.0.0.1:7890` 或局域网 `192.168.88.128:7890` 出代理。

### ~13:15 🐧👤 订阅接入 + geodata 修复 + dockerd 代理本地化
- 👤 用户提供订阅（liangxin.xyz，base64 vless 分享链格式，mihomo 原生解析）→ `apply-sub.sh` 写入 provider+分组；**57 节点加载**，PROXY→AUTO(url-test)，经 `127.0.0.1:7890` 实测 `generate_204 → 204 / 0.33s`。
- 两个坑及修法：① provider 缓存路径同样受 SAFE_PATHS 限制 → 挪 `/etc/mihomo/providers/`；② `GEOIP,CN` 规则触发 MMDB 在线下载卡死 → 经 FlClash 预置 `geoip.dat`/`geosite.dat` + `geodata-mode: true`。
- dockerd 代理从 Windows FlClash(`192.168.88.1:10808`) 改指本机 mihomo(`127.0.0.1:7890`)（`/etc/systemd/system/docker.service.d/proxy.conf`）→ `systemctl restart docker`（约 8s 闪断，全容器自愈）→ `docker pull` 经本地代理实测通过。**VM 从此不依赖 Windows 在线**。

### ~13:10 🪟👤→🐧 Cloudflare Tunnel 上线，https://rxycode.xyz 全链路验收通过
- 👤 用户完成 cloudflared 授权（dash 里选 rxycode.xyz，cert.pem 浏览器下载到 Windows Downloads）。
- 🪟→🐧 `cert.pem` → `/root/.cloudflared/cert.pem`(600)。
- `cloudflared tunnel create rxycode` → id `4e3b5220-219b-4322-a2cd-da06381fa640`，creds json 在 `/root/.cloudflared/`。
- DNS 路由：`cloudflared tunnel route dns` 对 `rxycode.xyz` 与 `www.rxycode.xyz`（第二次成功；第一次撞上 IPv6 回退问题 → 写 `/etc/gai.conf` `precedence ::ffff:0:0/96 100` 偏好 IPv4）。
- VM DNS 修复：VMware NAT DNS `192.168.88.2` 对 argotunnel 域名间歇超时 → `nmcli con mod ens33 ipv4.dns '8.8.8.8 223.5.5.5' ipv4.ignore-auto-dns yes` + `nmcli con up ens33`。
- `/etc/cloudflared/config.yml`：ingress `rxycode.xyz`/`www.rxycode.xyz` → `http://127.0.0.1:8080`（gateway），`protocol: http2`（QUIC 实测也通，固定 http2 求稳），404 catch-all。
- `cloudflared service install` → systemd 托管，预检四项全过后 `active`。
- `.env`：`RXYCODE_WEB_ORIGINS=https://rxycode.xyz,https://www.rxycode.xyz`（原占位 ts.net）；删除 `RXYCODE_SMTP_URL/_FROM`（Gmail 死路，凭据已清出 env 文件）；`RESET_OPERATOR_LOG=1` 保留。
- 更新 VM 上 `compose.prod.yaml` 为仓库最新（补 `RXYCODE_RESET_OPERATOR_LOG` 透传），`compose up -d api` 重建。
- **公网验收（Windows→https://rxycode.xyz 真实链路，`public_smoke.py`）**：注册 201 / `/me` 200 / 登录 200 / forgot 200 `delivery=operator-log` / 任务提交 202 → run `8152ffd9…` **succeeded**（~85s）/ SSE 事件回放 419 行全事件类型——**Cloudflare Tunnel 带 SSE 正常**，早前"CF 不能 SSE"的担忧证伪。
- Tailscale 方案废弃（Cloudflare + 自有域名更优）；`smtp-relay` 容器保留但当前指向 gmail 死路，选定可达邮箱后改 target+alias 即可启用。

### ~11:40 🐧📦 SMTP 投递链路：Gmail 不可达，中继已备好待选邮箱
- 新镜像 `29087f71`（api+web）+ SMTP 凭据 + `RXYCODE_RESET_OPERATOR_LOG=1` 已落 `/opt/rxycode/.env` 并 `compose up -d` 重建：api/worker/gateway 全 healthy。
- forgot-password API 实测返回 200，但 SMTP 发送失败：`smtplib.connect` 超时。
- 探测结论（VM 上跑 `connect_probe*.py`，容器内 python:3.12-slim-bookworm）：
  - VM→`smtp.gmail.com:465/587` 直连 TCP 全部超时（465 无明文 banner 属正常，但 connect 即挂）；`smtp.qq.com:465`/`smtp.163.com:465` 直连也超时——VM 直连出口对邮件端口整体不通。
  - 经 FlClash CONNECT（`192.168.88.1:10808`，全部回 200 established）：**gmail 465/587 TLS 被对端掐断**（节点出口到不了 Google mail）；✅ 完整握手+banner 验证可用：`smtp.qq.com:465`、`smtp.exmail.qq.com:465`、`smtp.163.com:465`、`smtp.126.com:465`、`smtp.office365.com:587`、`smtpdm.aliyun.com:465`；❌ resend:465 / sendgrid:587 / smtp-mail.outlook.com:587。
- 已建中继容器 `smtp-relay`（`alpine/socat`，`--network rxyprod_default --network-alias smtp.gmail.com`，CONNECT 转发）——方案有效但当前指向 gmail 死路；用户选定可达邮箱后改一行 target + alias 即可。
- 凭据安全：Gmail 应用密码只写入 VM `.env`(600) 与本地 Temp env，未进 git/日志/聊天输出。
- 待用户：选一个可达邮箱（QQ/163/126/exmail/office365）并提供其 SMTP 授权码；或保持 operator-log 模式。

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

### ~14:30 🐧 验证码重置上线 + Gmail 链路实测结论
- **镜像 `bda9a055`**（api+web+worker）已上 VM `rxyprod` 与本机 `rxylocal`：忘记密码改 6 位验证码（SMTP 投递），`send_mail` 加一次重试。
- **SMTP 失败降级修正**：日志产物从"6 位验证码"改为"30 分钟链接"（operator-log UI 只认链接，验证码无处可填）。两次实测 forgot 均走通降级。
- **Gmail SMTP 实测结论**：全量扫测 56 节点（运行时把 MAIL filter 展宽 `.*` 逐个切换探测，扫完还原）——仅「香港高速02/03|BGP|CMCU」放行 gmail:465，且**分钟级抖动**（扫时 TLS+banner、发信时 SSLEOF 往返波动）；587/STARTTLS 同样被掐。结论：**此订阅无法可靠投递 Gmail**。
- **可达的对照**：同链路下 `smtp.qq.com:465`、`smtp.163.com:465`、`smtp.exmail.qq.com:465` 全部 TLS+banner 通过（GEOIP CN 规则直连国内落地，不过墙）。要真发邮件建议换 QQ/163（需用户提供授权码）。
- ⚠️ 操作事故记录：`docker compose up` 忘带 `-p rxyprod` → 默认项目名 `rxycode` 起了一套空栈撞 8080 端口。已 `down` 清理（其卷仍在，未删数据）。生产命令一律 `-p rxyprod`。
- 生产现状：`https://rxycode.xyz` 跑 `bda9a055`，capabilities `reset_delivery=smtp`；忘记密码在有验证码邮件通时发邮件、不通时 200 降级到日志链接，永不断路。

### ~16:00 💻 验证码体系 + ALTCHA 人机校验落地（本机）
- **后端**（`rxycode-server`）：新增 `altcha.py`（自研 ALTCHA wire 实现——HMAC 签名挑战 + SHA-256 PoW + 一次性焚毁 + 20min 过期，零三方依赖）；`EmailCode` 模型 + alembic `008_email_codes`（password_resets 泛化三用途 register/login/reset）；端点 `GET /auth/altcha`、`POST /auth/register/code`、`POST /auth/login/code`；register/login/forgot/两发码端点全部强制 captcha。capabilities 增 `code_delivery` + `captcha:"altcha"`。
- **前端**（`apps/web`）：`altcha@3.4.1` npm 包；新组件 `AltchaWidget.tsx`（auto=onload 静默解题，提交后 remount 刷新挑战）；RegisterPage 加验证码发送/输入；LoginPage 加「密码/验证码」分段切换；ForgotPasswordPage 加 captcha；手机版细节（min-w-0、p-6 sm:p-8）。
- **测试**：w9 helpers 全接真 PoW 求解；新增 `test_email_codes.py` 4 条。**w9 全量 69 passed**、`tsc --noEmit` 干净。
- 待办：commit → git bundle 同步 VM → 重建三镜像 → 推 VM → rxyprod 升级 → 公网冒烟（注册要验证码+ALTCHA，登录可密码可验证码）。

### ~16:40 🐧 b42b937f 上线 + VM 源码 git 化 + 本机 Docker 事故
- **VM 源码 git 化**：`git bundle`（v2，兼容 VM 的 git 1.8）→ SFTP → `git clone /tmp/rxycode.bundle /opt/rxycode/src`（2925 tracked 文件，gitignore 内容未上去），HEAD=`b42b937f`，分支 feat/rxycode-web。
- **本机 Docker Desktop 瘫痪**：构建 web 镜像中途 Linux VM 挂起——`DockerDesktopVM PausedCritical`：**E: 盘 0 字节可用**（VHDX 在 E:\DockerDesktopData 29.8GB，盘被游戏塞满）。重启无效，VM 处于 IO 饿死暂停。**需要用户在 E: 盘腾空间**（至少几 GB）或把 DockerDesktopData 迁到 D:（24GB 空闲，略小于现用量，得先瘦身）。
- **部署改道：直接在 VM 上 docker build**（`/opt/rxycode/src` 已 git 化正好用上）——`--pull=false` + 先 `docker pull` 基座（buildkit 解析不走 daemon 代理，`docker pull` 走）。web/api 正常构建；worker 的 pip 步骤卡死 → 改用 overlay 方式：`FROM rxycode-worker:bda9a055` + COPY 变更的 rxycode-server 源码（requirements 未变，依赖层等价）。
- **VM 磁盘清理**：删掉 4 代旧 rxycode 镜像 + dangling + build cache，/dev/sda3 从 493MB 空闲回到 4.1GB。
- **公网冒烟**：`GET /auth/altcha` + 本地 PoW 求解×3 全部通过；`POST /auth/register/code` 200——首试走 operator-log（HK02 又抖），重试 `delivery:"smtp"` 真实投递成功。已向 xinyiruan293@gmail.com 发注册码，等用户回填完成 register→login 全链。
- 生产现状：`rxyprod` 全栈 `b42b937f`，capabilities 含 `code_delivery:"smtp"`、`captcha:"altcha"`。

### ~17:10 📧 验证码登录端到端验证通过（生产）
- 发现 `xinyiruan293@gmail.com` 已于 04:23 UTC 注册成功——`register/code` 对已存在邮箱按设计只回 200 不发信（防账号探测），改发 **登录码**。
- `POST /auth/login/code` → delivery=smtp 真实投递（`_deliver_code` 仅 `send_mail` 成功才返回 smtp，无 outbox 告警），用户收到邮件回填 6 位码。
- 端到端：`GET /auth/altcha` → 本地解 PoW（n=5810）→ `POST /auth/login {email,code}` → **200** + session cookie → `GET /me` → **200**（owner 角色、默认项目齐全）。
- 结论：验证码发码（SMTP）→ ALTCHA 门 → code 登录 → session，公网全链路实测通过。至此 v1.4.4 的认证功能（注册验证码/双模式登录/忘记密码/人机校验）全部有生产证据。

### ~21:00 🔐 BYOK 后端落地（PRD-WEB-ENTRY-UI-BYOK-PERFORMANCE）+ VM 前置条件
- **新代码（未提交）**：`rxycode_server/byok/`（AES-256-GCM 信封 + AAD 绑定 tenant/owner/conn/version + keyring 文件 mtime 缓存 + `netguard.vet_base_url` SSRF 防护）；alembic `009_byok`（`model_connections`/`user_models`/`users.default_model_ref`/`runs` 7 个快照列）；`api/models.py` 12 端点全 tenant+owner 隔离、密钥永不回显；`runs` 接受 `model_ref`，提交前解析快照（拒绝→403/404/409/503，不留孤儿 session）；`drain.py` `_resolve_run_gateway` 按快照在**认领时**重查白名单+凭据版本（轮换→CREDENTIAL_CHANGED、删除→MODEL_UNAVAILABLE），密钥只在父进程解密、经 loopback egress 注入上游（connect 时再 vet，防 DNS rebinding TOCTOU）；幂等 digest 绑定 model_ref。
- **compose.prod.yaml**：`RXYCODE_BYOK_ENFORCE=1`、keyring 只读挂进 api+worker、平台 key 变可选（仅 `RXYCODE_PLATFORM_MODEL_USERS` 白名单可花）。
- **VM 前置（已就位）**：`/opt/rxycode/secrets/byok-keyring.json` 0600 root:root（k1 活动 key）；`.env` 追加 `RXYCODE_PLATFORM_MODEL_USERS=3d0a1018fa93413f94ebe167cf4e4fa7`（用户本人账号保留平台额度，其余账号 enforce 后须自带 key——符合 PRD 设计）。
- **测试缺口**：本机 Docker Desktop 彻底死透（Electron 前端反复崩，backend 随之退出；E: 已腾出 14GB 仍无法恢复）→ pg 测试改在 VM 跑：`rxy-w9-pg` 容器 + api 镜像挂 /opt/rxycode/src 为 /repo + docker sock 透传，脚本 `vm_w9_tests.sh` 备好。
- **PRD 性能验收线**：worker.lease→agent_started 暖态 ≤3s（基线 13.068s）；暖态"你好"→首段可见 ≤8s；SSE→绘制 <250ms。

### ~22:00 ✅ w9/w7/w8 套件在 VM 真 Postgres 上跑通（本机 Docker 已死，迁 VM 跑测）
- **方法**：`/tmp/vm_w9_tests.sh`——VM 上起 `rxy-w9-pg`（127.0.0.1:55439）+ api 镜像挂 `/opt/rxycode/src` 为 `/repo`（测的是新代码非烘焙层）+ 容器内装 docker 静态 CLI 和 pytest。
- **w9 全量**：**105 passed**（migration 009 升级、BYOK 加密/隔离/快照/worker gateway 全绿；修了 2 个测试自身缺陷：`client.delete(json=)` httpx 不支持、重复 model_id 断言被 dict 折叠）。仅剩 `test_e2e.py` 10 条 playwright 用例因容器无浏览器 ERROR（环境性，留浏览器验收环节）。
- **w7+w8**：223 passed / 13 failed+error——A/B 对照旧提交 `b42b937f` **同子集同样失败**（ctl_roundtrip 事件循环内同步 recv 先天死锁、容器无 git 二进制、docker-in-container 限制），**BYOK/计时改动零回归**。

### ~21:40 🚀 W10 全量上线 e0124b8（BYOK+访客入口+模型选择器）+ 两个事故
- **前端落地提交** `68023e9`（27 文件，2771 行）：`/app` 访客壳（AuthGate 改私有子路由）、useAuth 三态、LoginPrompt 模态+pendingIntent 横幅（绝不自动重发）、Composer model_ref+幂等范围重置 requestId、ModelPicker 分组/搜索/键盘导航、设置页 BYOK 分区（连接 CRUD+发现面板+默认模型+access 横幅）、run 卡片模型快照回显、Esc 分层、登出清草稿。
- **构建/部署**：api.Dockerfile 完整重建 + worker overlay（FROM 68023e9 + COPY /repo）+ web.Dockerfile；构建期代理 `--build-arg http(s)_proxy=http://192.168.88.128:7890`（容器内 127.0.0.1≠宿主）；`npm ci` 一次 npm 自身崩溃重试即过。迁移 `009_byok` 应用，alembic_version=009_byok，两表+7 快照列在库。
- **事故1（真 bug，E2E 抓到）**：首个 run `ValueError: base_url must use https://` —— `config/model_endpoint.py` 的 loopback 豁免**只在本地未提交工作区**，VM 上是旧版。修复提交 `e0124b8` 重部署。教训：审计工作区未提交改动与部署清单的交叉。
- **事故2（环境）**：VM `net.ipv4.ip_forward=0` → 容器外网全断（BYOK 发现失败报 `host does not resolve` 是 netguard 正确 fail-closed）。sysctl 恢复 + `/etc/sysctl.d/99-docker-forward.conf` 持久化。
- **E2E 实测（生产，agent-browser）**：访客壳 ✅、发送→登录模态→`?next=/app` ✅、BYOK 连接 CRUD+发现/测试失败路径（401→`认证失败（auth）`）✅、模型快照回显 ✅、运行中模型锁 ✅、停止"取消中…"→cancelled ✅、`run.phase` 全链 ✅（warm 4.0s 组装、final 6.4s）。
- **加固**：`/opt/rxycode/.env` 664→600 root:root；gateway 仅绑 127.0.0.1:8080；响应头 nosniff+frame-DENY+no-referrer 实测在。
- **遗留**：warm lease→agent_assembled 4.0s vs 目标 3s（残差=子进程 spawn/import/assemble，需 warm 池）；final_answer 证据门误报（agent-runtime 后续）；version endpoint commit=unknown（镜像未注入构建标签，cosmetic）。
