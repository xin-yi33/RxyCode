# RxyCode 运维操作日志（OPS LOG）

> 用途：记录 agent 对仓库 / 本机 / VM / 线上环境的**每一次实际操作**——做了什么、在哪台机器、用什么方式、结果如何。
> 规则：之后每个动作完成后立即追加一条（倒序，最新在最前）；只写事实不写秘密（密码、key 一律不写值，只写"已配置"/"在 .env"）。
> 环境记号：🪟=Windows 宿主 / 🐧=CentOS VM(192.168.88.128, SSH ruanxinyi) / 📦=Docker 容器 / 📁=仓库 `D:\agent-demo\RxyCode\RxyCode1_1_0` / 👤=用户本人操作。

---

## 2026-10-22

### ~22:08 CST 🐧📦 BYOK-only 前后端分阶段上线（R6）
- 前端 gateway run `mobile-compat-20261022-134117-e08ccec8`：`rxycode-web:3a8526c-mobile-css-compat-20261022-r6`, image `sha256:d81517a1471a0df02981216e736c8308a01d1e662b5f8e1f916e6bd6f58ca590`, StartedAt `2026-10-22T13:42:55Z`（21:42:55 CST）。root/www HTTP 308、HTTPS 200、HSTS `max-age=86400`；JS `/assets/index-DZYcwX6P.js` SHA-256 `7da9b3d1c7ff4db4b327291e698375cfae9b73aaa4469dab5281a18f5a7777ed`，CSS `/assets/index-YfOn1oRs.css` SHA-256 `849f48b2cb3816c15196b13113f217682d95041e8f84c621a5090c185c0e8f49`。候选真实 Chromium 98 synthetic 四屏通过；公网 live synthetic picker/settings 在 320×640、667×375 通过，四张截图见 `D:/agent-demo/rxycode-web-modelpicker-r6-live-evidence/`。同源 RUM POST 5 条单独计数并 abort，业务写为 0。
- API `rxycode-api:byok-7da66e3cc8c2`, image `sha256:8bfd0887306ce323edaf15945628ce1bbc3ff85b3704b0c3c39fa7eabf94b1c2`, container `efab3e018a42c0539c30a6b44d9d9d5cae149eb39644e5b2265aaa7858481c7f`; StartedAt `2026-10-22T14:06:07.279218977Z`（22:06:07 CST）。3 个 worker 均为 `byok-724f6758599b`, image `sha256:3579c004d5624d5836a970f0f7f30434169a380a70f1dfcac1ded3cc8374a3c3`，StartedAt 分别 `14:07:20.856737781Z`、`14:07:19.781289068Z`、`14:07:20.298832815Z`（22:07:19–20 CST）。API、3 workers、gateway 均 healthy；`active_after_worker=0`。
- API 真实只读 DB probe：目录 1 个模型且 `source=byok`，access 为 `platform_allowed=false` / `require_byok=true`，不暴露旧 platform default；显式 platform ref 与旧 default 缺失模型均被拒绝。每个 worker runtime probe 对 platform 返回 `PLATFORM_NOT_ALLOWED`、缺 snapshot 返回 `BYOK_REQUIRED`，env gateway 未调用。DB 计数前后相同：28 runs / 20 sessions / 3059 events / 1 connection / 1 model。未调用真实收费 provider，未做完整 HTTP-auth E2E；Chromium UI 为合成 catalog，非真实账户目录。历史 platform run 成功（事件 seq 268）；用户授权取消的 waiting run 已 cancelled（approval event seq 68、run status seq 69）。
- 父级 fresh 检查：UI 2、BYOK 5、deploy-ops 7、旧 front-ops 9、typecheck、Ruff 与目标 diffcheck 通过。运维脚本曾遇 Docker 数组 guard 比较及 backup 缺 expected 参数两处接线问题，修复后 7 单测通过；两次失败尝试均未执行 mutation，不是产品/Harness 改动。
- 完整性/清理：`.env` SHA-256 `2619d92620086aa00d4b0bc27f44d6c62689a34da0c1bbda576f7f373c5a5b12`、keyring SHA-256 `7053c0b7ec27c9b9ae1d0783955217ccd9fef74acd10ab32e2bc591aaea02ebc` 与此前一致。backend state `D:/agent-demo/rxycode-web-hotfix-20261022-01/backend-byok-state-r6.json` 的 `builds.api.image_id` 与 `baseline.protected.env` 核对后记录；state 标记 `staging_cleaned=true`。前端 run `mobile-compat-20261022-134117-e08ccec8` 及后端 `/opt/rxycode/.ops/staging/byok-2657028e57fc` 的远端 staging 均已 cleanup。Windows 本地 exact backend stage 的 `Remove-Item` 被 policy 拒绝，未绕过；本地 staging、overlay、evidence 与 rollback 保留，不记为本地临时文件全删。rollback `/opt/rxycode/backups/backend-byok/byok-20261022-135854-53c8f703`。
- 附加 guest-after-backend smoke 运行 1 次，未通过：Chromium 98 打开 `/app` 得到 Cloudflare Tunnel Error 1033 页面，因无 Composer textbox 等待超时；selector 源码仍为“消息”，未修改/修复，不据此认定产品 UI 故障。诊断截图 `D:/agent-demo/rxycode-web-modelpicker-r6-evidence/public-guest-after-backend/guest-diagnostic-320x640.png`。

### 16:01:31 CST 🐧📦 Web mobile CSS compatibility R4 最终上线
- R4 是当前最终版本，已替代 15:51:46 上线的 R3 中间态。目标为 VM `192.168.88.128` 与公网 `https://rxycode.xyz` / `https://www.rxycode.xyz`；镜像 `rxycode-web:3a8526c-mobile-css-compat-20261022-r4`，image ID `a45caa41399b2f89a6576245a3a406c95aa734cf35f1bf00d43a8a1fe5959629`，gateway container ID `826da753d750f44cceafb1fe187f0d2d4e6ba15ec666a6c751090107f42130aa`。只替换 gateway image；服务器源码未再次修改，构建保留 3 个已有并发文件，产品 version 未修改（不是 v1.4.6）。
- 并发源码接缝已在 R4 构建中完整保留：`features/runs/eventReducer.ts`、`features/timeline/ThinkingBlock.tsx`、`sdk/errors.ts` 均从服务器原样取回并与 main 逐个 hash 一致；服务器全部 `apps/web/src` 递归 SHA 对比隔离构建树为 0 差异。R4 生产 JS `index-DuHnztVW.js` SHA-256 `4f08773531b8dc9d4e480e37553ee1f066a87a71ec2078474eafa41e50f408d5`，CSS `index-7bXesqCx.css` SHA-256 `440585fa390ebbb946036ddaf1ea456990fa847828f5b5a3afd5e2c45c9787bb`；root/www 均 HTTP 200 且 hash 匹配。最终脚本包含 `thoughts` 与「您没有额度了」，不含「今日额度已用完」。
- R4 上线后 fresh 全文件回归 `27 passed, 6 skipped`（48.12s；6 项因未安装 WebKit 而跳过；R3 的 48.22s 是历史结果）。公网真实 Chromium `90.0.4427.0`、`98.0.4758.0`、`148` 在 390/1440 视口共六组验证访客 `/app` 的 layout、theme、sidebar、model/send 登录门控与 console tabs，全通过且无 pageerror；未做公网已登录账户发送 E2E。另在真实 Chromium 98 禁用 Worker 完成 PoW 并实际 POST 无效凭据，得到 `401 INVALID_CREDENTIALS`（captcha 验证通过后因凭据无效而拒绝，不是成功登录），无 pageerror。另有本地隔离 production dist + 受控 API（mock `me`/CSRF/tasks）的发送回归：在 90/98/148 验证安全 UUIDv4、模拟断网后重试复用同一 request ID、收到可见 `BYOK_REQUIRED`；无模型调用。过程中曾有 label 定位超时，改用既有 `input[name=email/password]` 定位成功；未修改产品代码。截图已实际查看。
- 回滚/完整性：`/opt/rxycode/releases/web-mobile-css-compat-20261022-05` 保存 R3 compose；回滚目录 `...-04` 额外保存服务器 15:40 已构建 dist 的 `pre-r3-server-built-dist.tar.gz`，用于保留 R2 容器曾热更新、单独旧镜像未包含的回滚证据。生产 env/keyring/Caddyfile hashes 与之前一致；gateway 为 R4 healthy。R4 staging `/home/ruanxinyi/rxycode-web-css-compat-20261022-04` 经 realpath 校验后删除，R3 staging `...-03` 已删除，own sidecars none。5190 无 listener、QA Chrome 无进程。Windows QA 目录 `D:/agent-demo/rxycode-web-hotfix-20261022-01/qa-app-css-20261022` 删除被策略阻止，仍保留；未重试绕过。未 git commit/push。
- 截图证据：`docs/deploy/evidence/2026-10-22-mobile-css/` 共保留 9 张真实截图：before `before-chromium98-mobile-dark.png`；R4 最终截图 `online-r4-mobile-light.png`、`online-r4-mobile-dark.png`、`online-r4-mobile-login-compat.png`、`online-r4-desktop-light.png`；另有 4 张 R3 中间态历史截图（`online-r3-*`）。删除这 4 张旧图的精确路径操作被执行策略拒绝，未绕过，故保留为历史证据。父代理已查看 R4 移动深浅主题与 login 真实画面。Vivo 实体设备未测，不作真机通过声明。

### 15:51:46 CST 🐧📦 Web mobile CSS compatibility R3 中间态（已被 R4 替代）
- 部署目标：VM `192.168.88.128`，公网 `https://rxycode.xyz` / `https://www.rxycode.xyz`。切换至 `rxycode-web:3a8526c-mobile-css-compat-20261022-r3`，image ID `dc1cc7e75d090d9f8a2b5edad1b42ce98e41c580935d07adb430d6ae5cf86b6d`，gateway container ID `6ca2f6f681d89d300d79a7050e55a360a0f700de50691db3f6cfaa34a1a58694`。产品 version 未修改。
- 本次只对 `services.gateway` 执行 `up --no-deps gateway`。解析后的 compose 配置仅 `services.gateway.image` 不同；保留 `!reset` 等 compose 语义。API 与 Worker 的 before/current container IDs 未变，但采样中的 `StartedAt` 在约 15:37:35–15:38:07 CST 观测窗口出现差异；`RestartCount=0`、`OOMKilled=false`。这与下方既有 15:40 thoughts/BYOK 记录中的 API/Worker `docker cp` 更新后重启相符；按该 OPS 记录理解，不猜测执行者。PG/Redis/Minio 的 `StartedAt` 仍为原值。本次 R3 deploy 命令仅重建 gateway。
- 回滚材料在 `/opt/rxycode/releases/web-mobile-css-compat-20261022-04`，含 compose、package、npm/Bun locks、Vite 配置、globals CSS 与 Composer 的 before 版本。`postcss.config.cjs`、`tailwind.config.js`、`src/lib/secureRequestId.ts` 上线前确认不存在，若回滚源码需移除这些新增文件；旧 R2 镜像保留。
- 公网 `root` 与 `www` 的 JS/CSS 均 HTTP 200，资源名为 `index-CllmMfSv.js`、`index-7bXesqCx.css`，SHA-256 与构建产物及镜像一致：JS `a218d8a9eef9b0f427a16a3a4b77b1407de06637b87c59fc7346825a1a67dc9f`，CSS `440585fa390ebbb946036ddaf1ea456990fa847828f5b5a3afd5e2c45c9787bb`。
- 父代理 fresh 全文件回归 `27 passed, 6 skipped`（48.22s；6 项因未安装 WebKit 而跳过）；Ruff、typecheck、diffcheck 均通过。真实 Chromium `90.0.4427.0`、`98.0.4758.0`、`148` 在 390 与 1440 视口共六组验证 `/app` flex root、移动侧栏/菜单、主题及刷新、模型/发送登录门控、控制台三 tab，均无 pageerror。父代理目视核验移动端深浅主题与桌面布局；浅色截图需等待 drawer 退出及 composer 卡片 transition 完成。
- 公网认证复验：Chrome 90 normal、98 Worker blocked、148 normal 的真实 PoW 后提交无效凭据，均得到 `401 INVALID_CREDENTIALS`（不是 captcha 错误，且不代表成功登录），token `348–352` 字节且 SHA 数学关系正确；三个引擎的 `/register`、`/forgot` 真实验证均成功，未注册账号、未发邮件。本地隔离 production dist + 受控 API（mock `me`/CSRF/tasks）的发送回归在 90/98/148 验证安全 UUIDv4、模拟断网后重试复用同一 request ID、收到可见 `BYOK_REQUIRED`；不是公网已登录账户 E2E，无模型调用、无 pageerror。
- 并发源码接缝（R3 时）：逐个 hash 比较服务器与隔离树全部 `apps/web/src`，当时恰有三处差异：`features/runs/eventReducer.ts`、`features/timeline/ThinkingBlock.tsx`、`sdk/errors.ts`。它们承载 15:40 thoughts 与「您没有额度了」前后端显示；三份服务器版本已由 15:40 记录中的 API/Worker 更新上线，但 R3 隔离构建仍是相对 `3a8526c8` 的旧版本，故 R3 中间态曾临时覆盖这两项显示。R3 不构成回滚这些并发改动的决定；三文件已在 R4 原样恢复，详见上方 R4 最终上线记录。
- 完整性：9 个服务器源码文件与隔离构建树逐字节一致；生产 env/keyring/Caddyfile hashes 前后不变，env/keyring 权限仍为 `600 root`。服务器可用磁盘约 `7.7 GB`。产品 version 未改，未 git commit/push。
- 清理/证据：预览端口 `5190`、session `54169` 已 Ctrl+C 结束；只读复核无 5190 listener、无 QA Chrome 进程，own sidecars 为 none。服务器 staging `/home/ruanxinyi/rxycode-web-css-compat-20261022-03` 经 realpath 校验后删除，`test ! -e` 通过。Windows QA 目录 `D:/agent-demo/rxycode-web-hotfix-20261022-01/qa-app-css-20261022` 的递归删除在执行前被策略阻止，未绕过，目录仍存在（含旧 Chromium 90/98、额外截图及 tar）；不能记作全部临时文件已清理。
- R3 当时的 4 张截图保留为中间态历史证据；精确路径删除被策略拒绝，未绕过。最终目录共 9 张（1 张 before、4 张 R4、4 张 R3；文件清单见上方 R4 条目）。父代理核验 R4 的 drawer 退场、composer 颜色过渡完成后的稳定帧，无裸样式或重叠。Vivo 实体设备未测，不作真机通过声明。

### 15:40 CST 🐧📦 thoughts 标题与 BYOK 额度门控上线
- 目标：VM `192.168.88.128`，公网 `https://rxycode.xyz`。没有改 `.env`、密钥、数据库或超级号。
- 源码备份在 `/opt/rxycode/releases/thoughts-byok-20261022/`。API 与三个 worker 用 `docker cp` 换上额度门控和 reasoning 投影后重启，随后均为 healthy。API 内 `DEFAULT_LIMITS.meter_user_quota` 为 False。worker 的 drain 含 `channel: reasoning`。
- 前端在 VM 上从 `/opt/rxycode/src/apps/web` 重新构建并写入 gateway `/srv/www`。公网首页脚本为 `/assets/index-C3Uhjm3v.js`。该文件含 `thoughts` 与「您没有额度了」，不含「思考过程」和「今日额度已用完」。
- 本地提交 `989f9f4a` 只在 `feat/rxycode-web`，这次没有把该提交 push 到 GitHub。

### 12:27:34 CST 🤖🐧📦 父代理按用户授权部署 ALTCHA capabilities 竞态门控 R2
- 父代理按用户授权于 2026-10-22 12:27:34 CST 将 R2 切流至 `rxycode-web:3a8526c-mobile-pow-compat-20261022-r2`，image ID `30c09b9c7e1afb278eee3a7620ed5b79d01c504ee4eaf28c59a7a3b5f9d16d75`。新资源为 `index-CFqJWzHp.js`、`index-L8_X1WLw.css`。
- 仅 gateway 执行 `--no-deps` 重建；API、Worker、DB 未重建。回滚材料位于 `/opt/rxycode/releases/web-mobile-pow-compat-20261022-03`，含 compose 与 Login/Register/Forgot 三页 before 版本；R1 的 helper/package 不回退。
- 三认证页现以 capabilities 已有成功数据为提交前提；登录/注册的 submit 与发码 handler 复用 `canSubmit`/`canSend`，找回密码提交同样要求 captcha 就绪。配置失败有可见重试。产品源码已冻结。
- 初次公网 `CAPTCHA_INVALID` 的因果已纠正：旧探测脚本只等 submit 按钮 enabled，未等 capabilities 返回；此时页面把未加载配置当成无需 ALTCHA，按钮提前启用，实际 POST 的 `captcha` 是空字符串。不是已通过 UI 求解后签名失败。
- 最终公网四模式验证（normal、Worker 禁止、Worker 内 `crypto.subtle` 缺失、Worker 与 window `crypto.subtle` 均缺失）：先真实 hold capabilities、填写表单并强制 submit，四种均按钮 disabled 且无 POST；释放真实 capabilities 后等待 verified 再提交。顺序耗时 `7.01/7.70/7.00/5.68s`（含配置网络、PoW、CSRF 与 POST）；token `348–352` 字节、hash 数学成立，服务器均回 `401 INVALID_CREDENTIALS`，即 captcha 校验接受后才因无效账号凭据拒绝；无 pageerror。
- Worker 与 window crypto 均缺失时，`/register`、`/forgot` 显示兼容验证中文状态；测试未注册账号、未发邮件、未触发收费模型调用。公网 JS/CSS 均 HTTP 200，资源 SHA-256 与本地产物一致：JS `38af81fa6cd04b599c1b4672a66b67c009baa33b50c35b0f9a59d495c8fcd600`，CSS `3e612ba4ebcadca867ff8125f6780d7c305cbc8c581c8e2e764023b0539fc405`。
- 最终验证：父代理完整 fresh suite `23 passed, 6 skipped`（37.78s；包含三页 pending-capabilities 回归，非 R1 的旧 `20 passed` 记录）；Ruff、typecheck 与隔离 production build 通过。物理 Vivo 真机未测，具体设备触发根因未确认；不把浏览器缓存列为根因，建议用户重新打开最新 URL 获取新入口。
- 清理/完整性：QA 5189/5190 服务均 Ctrl+C 退出，Playwright contexts/browsers 均 finally 关闭；sidecar `rxy-web-pow-check-20261022` 已停并删除；上传/staging `/home/ruanxinyi/rxycode-web-pow-compat-20261022-02` 经核对路径后删除。R1/R2 镜像与 rollback 目录保留。服务器可用磁盘约 `8.4 GB`（53%）。生产 env、keyring、`Caddyfile.prod` 的 SHA-256 前后不变，env/keyring 仍为 `600 root:root`；API、3 个 Worker、Postgres、Redis、Minio、SMTP 容器 ID 与 `StartedAt` 不变，gateway healthy；服务器五个 auth 源文件与主 repo 当前内容逐字节一致。
- 本机复用已有 `D:\agent-demo\rxycode-web-hotfix-20261022-01` 隔离构建目录，没有新增构建根目录；该目录先前递归删除被策略拦截，仍保留。不要记为 Temp 全部清理完成。

### 11:36 CST 🐧📦 Web 手机认证与主题兼容部署
- 部署目标：VM `192.168.88.128`，公网 `https://rxycode.xyz`。以 Git 基线 `3a8526c8` 加 `AltchaWidget.tsx`、`ui.ts`、`globals.css` 三个隔离修复文件构建；不是整工作区部署。线上 `/opt/rxycode/src` 已同步这三个文件。
- Web 镜像：旧 `rxycode-web:3a8526c`（image ID `e958976b355710a152844212ed5b00d0ef11eadcd58e06d03dccd84371311027`）；新 `rxycode-web:3a8526c-mobile-auth-theme-20261022`（image ID `1ba6c174359ed8c314756c45207a7bd04384718a86aa387d139a5450f24c342b`）。仅 gateway 使用 `--no-deps` 重建；API、Worker、DB 未更新。`/opt/rxycode/compose.prod.yaml` 解析后仅 `services.gateway.image` 不同，其余配置相同；未修改 `.env` 或密钥。
- 新前端资源：`assets/index-BahcHKpg.js`、`assets/index-D9GookH7.css`；旧 hashed assets 保留，供已打开的旧标签页使用。最终系统 HTTP GET 两项资源均为 200，SHA-256 均与本地产物及服务器 image 一致。version 接口持续返回 `3a8526c8`，属预期，不代表前端未部署。Playwright APIRequestContext 取 asset 曾报 Node `ENOTFOUND`；浏览器页面实际加载及功能 E2E 成功，该执行器错误不作为产品缺陷，也不能据此证明服务器 DNS 异常。
- 验证：本轮 fresh 回归 6 passed、6 skipped（环境未安装 WebKit）；typecheck/build 通过，回归测试文件保留。公网 `/login`（3.95s）、`/register`（2.07s）、`/forgot`（1.86s）均完成真实签名 challenge 验证，各自请求 `/api/v1/auth/altcha` 返回 200 JSON；使用非真实 `.invalid` 邮箱做一次无效凭据登录返回 `401 INVALID_CREDENTIALS`，非 captcha 错误，未创建账户、未发邮件。另以带合法 CSRF、空 captcha 的认证请求验证，返回 `400 CAPTCHA_INVALID`，证明认证安全门未绕过；不把缺少 CSRF 时的 `403` 作为 captcha 证据。匿名新 context 在 360/390 移动视口、浏览器 dark 偏好下，light↔dark 全局背景切换并在刷新后保持；模拟 cookie 读写 `SecurityError` 仍可切换且无 pageerror。最终截图已检查：过渡结束后输入卡片背景为白色，深浅主题正确。真实已登录设置页 Topbar 和 Settings 按钮线上操作均通过，最后恢复 light。相关功能 E2E 全部完成；所有浏览器和 QA sidecar 均已关闭。
- 回滚备份位于 `/opt/rxycode/releases/web-mobile-auth-theme-20261022-01`（含 `compose.prod.before.yaml` 与三个源码文件的 before 备份），旧镜像保留。回滚仅恢复 compose 中 gateway 镜像及上述三个源码文件；不改 `.env` 或数据库。
- 服务器清理：执行 `yum clean all`、`docker builder prune -af`、dangling image prune；检查容器引用后删除 18 个未引用旧 `rxycode-*` 镜像 tag，保留当前镜像和 `3a8526c` 完整回滚镜像；删除 `/tmp` 下 3 个确认无进程打开的旧传输包（1 tar、2 git bundle）、server `.pytest_cache`、本轮 staging 临时目录，并停止/删除本次 sidecar 验证容器。数据库及全部 named volumes 未动。最终 `df -B1`：available `9032462336`、used `9968783360`（报告 53%）；相较初始 432 MB 可用、98% used，约释放 8 GiB。
- 完整性/运行状态复核：`/opt/rxycode` 的 `.env`、keyring、`Caddyfile.prod`、`compose.yaml` SHA256 前后完全相同；`.env` 与 keyring 仍为 `600 root:root`。API、3 个 Worker、Postgres、Redis、Minio、SMTP 的容器 ID 与 `StartedAt` 均未变化，只有 gateway 更换容器 ID，当前 healthy。服务器上 3 个修复源码文件与本地逐字节一致。
- 未完成的本机清理：Windows 批量 Temp/`.pytest_cache` 删除被执行策略拦截，未执行且未绕过；本轮 fresh 回归测试文件须保留，不作为垃圾清理。`D:\agent-demo\rxycode-web-hotfix-20261022-01` 的递归删除亦被执行策略拒绝，目录仍保留；未绕过限制。目录内 `node_modules` 是指向项目依赖的 junction，不是复制目录，勿误删实际依赖。真机 Vivo/iOS 与厂商强制夜间模式未测，不作已验证承诺；建议用户用真机重新打开网址检查。现有 CSS 提示不保证覆盖厂商强制绘制变换。

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

## 2026-10-22 20:32 CST 📱 Web mobile/ALTCHA R5 已部署（不发版）

- 运行记录：`mobile-compat-20261022-091225-9e85b988`；实际 gateway image `rxycode-web:3a8526c-mobile-css-compat-20261022-r5`，image ID `sha256:b2c80f9e8fc6445dc33fd8b7edebaed849e1586631781ab12f0d2923136d2f67`，gateway container ID `43846624e6807c89199e1d2a6dfbc8c0a8b250f0ba456ee43bfd1309daf86eb4`。报告 StartedAt `2026-10-22T12:32:24.956927904Z`（20:32:24 CST）。回滚备份保留于 `/opt/rxycode/backups/web-mobile-compat/mobile-compat-20261022-091225-9e85b988`。
- 仅 web 前端镜像更新；产品版本未改、未发版。只读 `/api/v1/version` 仍为 commit `3a8526c8`、built_at `2026-10-21T16:09:29Z`，符合 frontend-only 预期。公网 CSS `/assets/index-CCx41QaJ.css` SHA-256 `9822c6903817daa675944e77cd6492a3ccc3c101a5931c02114581d08cd4b027`；JS `/assets/index-ZiffSGm4.js` SHA-256 `405d5127177f2e2b5f15d915ecc418920ec7936e8e1ff8c36873bb52e5df77dd`。
- 部署验证报告：`D:/agent-demo/rxycode-web-hotfix-20261022-01/ops-runs/mobile-compat-20261022-091225-9e85b988/verify-result.json`。root 与 www 的 HTTP 探测为 direct，均 308 到对应 HTTPS `/login?ops_probe=verify-mobile-compat`（路径与 query 保留）；HTTPS 200 和 `Strict-Transport-Security: max-age=86400` 是经现有 system proxy 验证。主机直连 root TLS 曾间歇超时，首轮 verify 超时、复跑通过代理成功；不据此声称 direct HTTPS 全通过。
- 安全/影响面核对：报告 `non_gateway_services_unchanged=true`、`production_secret_files_unchanged=true`；`.env` 与 keyring hash/权限未变，非 gateway 容器的 ID 与 StartedAt 未变。无服务端 ALTCHA verifier、API 或数据迁移改动。远端 staging 已按父的实际清理结果清理、备份保留；本机 cleanup 受既有策略限制未删除，未绕过。
- 浏览器证据：公网匿名 live Chromium 148、98、90 各三种场景共 9/9 passed；真 Chromium 90 的 3 项用时 47.21s。覆盖移动正常能力、HTTPS 下 `isSecureContext=false` 且 Worker/Subtle 不可用、桌面官方 Worker `getState() === "verified"`。认证 POST 均在浏览器路由处拦截；无真实账号、邮件或模型调用。本地浏览器入口 `32 passed, 7 skipped`（6 个 WebKit binary 缺失、1 个 opt-in live 参数未设置）；独立 UI Chromium 90 与 98 各 3 passed 并已目检截图。上述结果只代表实际 Chromium 场景，不代表 WebKit 或实体手机。
- Public UI 首轮末断言曾把同源 Cloudflare `POST /cdn-cgi/rum`（4 次、均 abort）算作业务写，属分类误报；第二轮还曾采到 theme transition 中帧，均已由测试侧修正。最终 fresh live UI 在真实 Chromium 98 的 320×640 与 667×375 两尺寸通过：dark 与 restored 状态均等 transition 完成后，topbar/card/textarea 的 computed colors 与 CSS vars 精确相等；drawer 最终位置及关闭后 focus 恢复，login 等 capabilities 与验证码完成。10 张匿名截图已更新；父报告 Ruff、diffcheck 通过。RUM POST ×4 继续 abort，其他业务写 0，无 preferences stub。R5 冻结源主题按钮使用 `useUi`/`rxy_theme` cookie；本次仅测试时序更新，无产品代码变化、无需重部署。当前 dirty main 后续 WIP 不代表 R5 内容。
- anonymous evidence 在 `docs/deploy/evidence/2026-10-22-mobile-browser-r5/{current,chromium98,chromium90,ui}/`；截图上下文无账号。Vivo 实体机、iOS 实机与 WebKit 未测。ALTCHA 继续使用服务端原 V1 签名/TTL/replay 验证，手机分片纯 JS 求解、桌面官方 worker widget 与错误回退；无降级服务端验证强度。

## 2026-10-23 W11 收尾部署（49ca62dc）

- About 对话框上设置页；api.Dockerfile 补传 `RXYCODE_BUILD_COMMIT/TIME` build ARG，`/api/v1/version` 现在回真实 commit（此前 `unknown`）。
- **事故**：`compose -f prod.yaml -f base.yaml` 顺序写反让 dev 配置赢（migrate 变 dev-seed 等待 sync 哨兵卡死）；正确顺序 = base 在前 overlay 在后。顺手起了 `rxycode-*` 游离栈抢 54433，已清。rxyprod-postgres 重建但同卷，数据无损（12 sessions / 6 users / 1 device_lock / 1 conn 复核）。
- 生产终态：web/api `49ca62d`，worker `5499470`（代码等价已打双 tag），version 端点回 `49ca62dc`。浏览器实测：设备冲突模态+抢占、markdown 加粗、思考链×2、bash 工具卡、BYOK `deepseek-flash` 徽标、模型切换提示、390px 移动视口、About 对话框全部通过。
- VM 源码 checkout `5e81f215`（含 changelog 补记）。未做整机重启——容器重启已满足"域名最新内容"，SSH 断连风险不值。

## 2026-10-23 W12 文件 API + 并发扩容（aa5581a6）

- `files.py`：会话工作区列表/下载，`{tenant}/{session}` 目录 scoped、穿越/符号链接/dotfile 全部拒绝。
- prod overlay api `volumes: !reset` 清掉 base 挂载是已知坑——worker-data 需在 overlay 显式补回，否则 api 读不到工作区。
- `--scale worker=4` 实测 4 用户并行 run 成功（4 个不同 lease_owner 同时持有 77s+）；生产保留 4 worker。
- 测试用 mint 的 auth_sessions 已全部 revoke；PLATFORM_MODEL_USERS 恢复仅 owner。

## 2026-10-23 并发封顶 + 重启验证（aea73aa→96ddbbf）

- prod overlay worker `deploy.replicas: 3`（`RXYCODE_WORKER_REPLICAS` 可覆盖）——全局在途并发封顶 3，上游限流红线。
- VM 整机重启验证：docker/cloudflared 均 enabled + 容器 restart unless-stopped——重启后 52s 全栈自愈，域名直接回 `3a8526c8`。
- BYOK 链路复核：keyring 挂载修复后真实 run `32cf733a` succeeded（deepseek-flash 个人额度）。

## 2026-10-23 BYOK Composer 模型生命周期热修（rxyprod）

- 候选从线上 `apps/web` 1.4.3 冻结源构建；冻结包 SHA-256 `d7fdf40d4d7e307f764d207eb6baf5d876430d6a615dd299910192b86180af67`。与候选逐文件比对 84 个归档文件，仅 `src/state/ui.ts`、`src/features/console/Composer.tsx` 两处不同；`ModelPicker.tsx`、`SessionPage.tsx`、responsive CSS、`package.json` 与 lockfile 均与线上源哈希相同。未包含当前工作树的 preview/artifact/attachments WIP。
- 隔离候选 `npm run build` 成功；`pytest -q tests/web/w10/test_composer_model_lifecycle.py`：2 passed。390px 浏览器证据等待侧栏真实边界移出视口且动画矩形稳定，并断言模型按钮完整在视口内后截图：`D:/agent-demo/rxycode-web-hotfix-20261023-live/evidence/mobile-390.png`。
- 用线上 gateway 基底 `rxycode-web:3a8526c-mobile-css-compat-20261022-r6`（image ID `sha256:d81517a1471a0df02981216e736c8308a01d1e662b5f8e1f916e6bd6f58ca590`）加仅含已验证 dist 的静态层构建 `rxycode-web:byok-draft-persist-20261023-01`（image ID `sha256:0a4a19a01f25a9c17f6ee4eb9477ae8475c365d950f82bdbd0d96a42beca8048`）。**运行态**仍是 gateway 容器 `1e57c00c29c25b2ae784db7a2846d014a1814f992fa20e6aa42a9dc421f3e8f2`、旧 image ID/tag；仅将新哈希 assets 复制入该容器，最后原子替换 index，未重启 gateway。远端 `compose.prod.yaml` desired image 已单行改指向新 tag，未执行 compose up/recreate；旧 index 与 compose 备份保留在 `/opt/rxycode/backups/web-byok-model-lifecycle-20261023/`。本地 `infra/compose/compose.prod.yaml` fallback 同步改为此 tag。
- 公网原始 HTTP bytes（部署前 → 部署后）：index `f7dcd09be3da4aea990b2c010445778b9e0e63578b8a42749a25b35d1ab6a449` → `00d88832b9fa16756f16c5837606dbd4a4c490bb4fe54577c81043f9814371b2`；主 JS `7da9b3d1c7ff4db4b327291e698375cfae9b73aaa4469dab5281a18f5a7777ed` → `927ecffe38c4828632dcb1e84271758de8b99c48434c17e22376367947373571`；CSS `849f48b2cb3816c15196b13113f217682d95041e8f84c621a5090c185c0e8f49` 保持不变。公网新 index 与 JS/CSS、altcha、xterm 均逐字节匹配候选；相关原始文件留在上述本机 evidence 目录。
- 真实浏览器连续两轮 `deepseek-flash`（`credential_source=byok`）均 succeeded，Run `4d23770f4dfb450e81d552c0ec909334`、`4c5be832b3b74bfd834acd508412251a`；两轮浏览器 POST body 的 `model_ref` 均为 `m_8f193a80f3a84948b7ff3e9974160c5f`。首轮 `/api/v1/tasks` request ID `8b83589b-4111-4f35-885a-45563e6b2a8c` 接受后创建 session `d0c04f6b4ba7422082623c92ab2da633`；续问 `/api/v1/sessions/{session_id}/runs` request ID `9d48bd41-2b6a-4458-94af-c3509a4cfa73` 仍提交同一 `model_ref`。最终选择按钮为 `选择模型：deepseek-flash`，菜单只显示模型名。
- 部署前后 API/worker 容器 ID 未变；`.env` SHA-256 `2619d92620086aa00d4b0bc27f44d6c62689a34da0c1bbda576f7f373c5a5b12`、BYOK keyring SHA-256 `7053c0b7ec27c9b9ae1d0783955217ccd9fef74acd10ab32e2bc591aaea02ebc` 前后相同。未触碰 Caddy 配置、API、worker、数据库或密钥内容。
- 测试使用的浏览器登录已通过站点正常登出并关闭浏览器自动化会话；远端一次性 build staging 与 helper container 已清理，回滚备份和已构建镜像保留。

## 2026-10-23 BYOK Composer 模型恢复待定保护（批准候选静态热更新）

- 主审批准后部署原候选 `apps/web/dist`，未修改产品源/重新构建不同 hash。薄镜像 `rxycode-web:byok-draft-persist-20261023-02` 以已验证的 `-01`（`sha256:0a4a19a01f25a9c17f6ee4eb9477ae8475c365d950f82bdbd0d96a42beca8048`）为 base，image ID `sha256:7e39cf2d0122ab814533ce99af682e3dd847e3e0fd9606493ab9b20e372dbcd1`；保留 base layers 和 `index-Cb9nsFp9.js`（`927ecffe38c4828632dcb1e84271758de8b99c48434c17e22376367947373571`）。
- 先逐个验证/写入新静态 assets，最后同目录临时文件原子替换 `/srv/www/index.html`；未执行 `compose up`，未重启/recreate 业务容器。远端 `compose.prod.yaml` 仅将 gateway desired image 从 `-01` 改为 `-02`。gateway 仍为 R6 容器 `1e57c00c29c25b2ae784db7a2846d014a1814f992fa20e6aa42a9dc421f3e8f2`，image ID、StartedAt 均未变；所有 Compose 容器 ID/StartedAt 未变。
- `.env` SHA-256 `2619d92620086aa00d4b0bc27f44d6c62689a34da0c1bbda576f7f373c5a5b12`、BYOK keyring SHA-256 `7053c0b7ec27c9b9ae1d0783955217ccd9fef74acd10ab32e2bc591aaea02ebc` 不变；Caddy、基础 `compose.yaml` 指纹不变，prod resolved config 仅 gateway image 有差异。
- 匿名公网字节核验：两个主机的完整原始 index entity 通过 `206 bytes 0-414/415` 返回，SHA-256 `5d0e7a0756d01f64979b9520294484cce16e1c82ba5d6f8097cb1c4630b67bbf`；JS `200`/726505 bytes/SHA `a8aa1dd40255755a38865461b6cc8f1b2a8b41aae7ebf6c14261f8a3ba5b0863`；CSS `200`/29218 bytes/SHA `849f48b2cb3816c15196b13113f217682d95041e8f84c621a5090c185c0e8f49`。Cloudflare 对普通完整 HTML GET 注入现有 Web Analytics beacon（782 bytes，SHA `7ee01623d7556b82693dcd71a5683efe2e9cc9eabe0368fb72b7fd66e501fd1b`），故 full edge response 与 origin index hash 不同；Range 覆盖全文件并确认 origin bytes 精确。未改平台设置。
- 回滚目录：`/opt/rxycode/backups/web-model-restore-guard/model-restore-guard-20261023-bb34d809`（旧 index SHA `00d88832b9fa16756f16c5837606dbd4a4c490bb4fe54577c81043f9814371b2`，同时保存原 `compose.prod.yaml`）。回滚命令：`sudo -n cp -p /opt/rxycode/backups/web-model-restore-guard/model-restore-guard-20261023-bb34d809/compose.prod.yaml.before /opt/rxycode/compose.prod.yaml.rollback && sudo -n mv -f /opt/rxycode/compose.prod.yaml.rollback /opt/rxycode/compose.prod.yaml && sudo -n docker cp /opt/rxycode/backups/web-model-restore-guard/model-restore-guard-20261023-bb34d809/index.before.html 1e57c00c29c25b2ae784db7a2846d014a1814f992fa20e6aa42a9dc421f3e8f2:/srv/www/.index.rollback.tmp && sudo -n docker exec 1e57c00c29c25b2ae784db7a2846d014a1814f992fa20e6aa42a9dc421f3e8f2 mv -f /srv/www/.index.rollback.tmp /srv/www/index.html`。assets 与新镜像不删除。
- 主审独立确定性测试：Node 4/4、候选真实页面 pytest 10/10、主仓原 pytest 2/2、`npm test`、`npm run build` 均通过。该部署记录当时未登录生产应用、未触发业务 API/真实 provider；两轮真实 provider 验收当时待主审完成（后续结果见下节）。未修改产品版本号；未触碰本地主仓 compose、未提交/推送。远端本次 staging/helper 已清理，备份保留。

### 主审真实 provider 验收完成（2026-10-23）

- 主审正常登录且未修改 Key。会话 `28093b300301433497d66789cf9f808a` 的首轮 run `aa43aa3a71ba43dcaea72b218c26eb1c` 回复 2；刷新同会话、不重选后按 Enter 的 run `8615057e01f0478c855964d738f470a7` 回复 4。两条 Run GET 均 HTTP 200、`status=succeeded`、`model_id=deepseek-flash`、`credential_source=byok`、`model_ref=m_8f193a80f3a84948b7ff3e9974160c5f`；两次 POST body 的引用相同。
- 主审正常退出并重登，打开该会话后模型自动恢复且没有误报 Key 缺失。独立 SSH 核验 gateway `1e57c00c29c2`、API `efab3e018a42`、workers `aefca5cffd23` / `73ccc9279929` / `34490b8bab77` 及 StartedAt 均未变化；`.env`、keyring、Caddy、base compose 的 hash 均匹配部署前。
- 主审浏览器直接 fetch 的 index（SHA-256 `5d0e7a0756d01f64979b9520294484cce16e1c82ba5d6f8097cb1c4630b67bbf`）、JS（726505 bytes，SHA-256 `a8aa1dd40255755a38865461b6cc8f1b2a8b41aae7ebf6c14261f8a3ba5b0863`）与 CSS（29218 bytes，SHA-256 `849f48b2cb3816c15196b13113f217682d95041e8f84c621a5090c185c0e8f49`）均匹配批准产物。证据：候选保留的 `evidence/extra/online-after-refresh.png`、`online-two-turns-390.png`、`online-after-relogin.png`。
- 390×844 无横向溢出，模型按钮只显示 model-name，主题切换不清模型；这是 Chromium 手机视口验证，不是 vivo 真机。真实 provider 仅验证 `deepseek-flash` 一个模型，不把本地模拟多模型测试表述为真实多模型验收。临时 auth profile `rxycode-release-verify` 已删除，浏览器 session 已关闭。

## 2026-10-23 v1.4.5 全栈部署 + 真实 BYOK 验收（fa366863）

- 部署单元：`rxycode-{api,worker,web}:web-fa366863`，源 = `feat/rxycode-web` tip `fa366863`（master merge `66eea4a2` + serve() 修复 + 012 迁移修复）+ 工作区 WIP 叠加（60 文件，与线上既有未提交功能一致——草稿保持/ALTCHA/移动修复）。同步方式：git bundle（`60da12e..feat` + `7c74ee2e..feat`）+ tar overlay → `/opt/rxycode/src` checkout `fa366863`。
- 部署步骤：`docker build` 三镜像（api `0772d866`… worker/web 同 tag）→ `RXYCODE_IMAGE_TAG=web-fa366863 compose run --rm migrate`（alembic head→`012_files_batch`）→ `compose up -d`。worker replicas=3 未变。
- **部署中发现的真 bug（已修）**：
  - alembic 012 `UniqueConstraint(postgresql_where=)` 在 SQLAlchemy 2.x 下非法（仅 `Index` 接受），生产 `upgrade head` `ArgumentError` 全量回滚（DB 停在 011，无残态）。修为 `op.create_index(unique=True, postgresql_where=)`，提交 `f2b9872e`，test pg 全量 001→012 重验。
  - worker 服务无 S3 env：`_stage_attachments` 经 `blob_config_from_env()` 落到 FS 后端读容器内不存在路径 → 首个附件 run `fa1713ec` 失败（`attachment.import FileNotFoundError`）。compose.prod.yaml worker 块补 `RXYCODE_S3_*`（与 api 同源 MINIO_ROOT 变量），三 worker 重建。
  - 注：`compose run --rm migrate` 不带 `RXYCODE_IMAGE_TAG` 会用 `rxycode-api:latest`（旧镜像无 012 定义）报 `Can't locate revision`——DB 无影响，带 tag 重跑即幂等。
- **真实 BYOK 验收（DeepSeek `mc_28019d…` / `m_8f193a8…` deepseek-flash，真 token 计费）**：
  - run `379d325b`：真模型调 bash 建 `hello.txt`+自校验，`run.phase` 全链 trace，`succeeded`（80.9s e2e）。
  - run `564d6481`：附件 `acc-note.txt` 86B（POST→PUT→sha256 `eb71bf5b`→worker MinIO `attachment.import: imported`+sha256 校验→模型实读），final 精确返回行内标记 `attachment-binding-check-42`，`succeeded`，19.8k in/1.5k out tokens。
  - run `c9d3c1e5`：模型写 `report-accept.md` → `_register_run_artifacts` 登记（sha256+signed URL+expires），`GET artifacts` manifest complete → 签名下载返回真实字节 `acceptance report ok`；坏 cookie 401。
  - run `e8a1b8b3`：`cancel` → `cancel_requested` → `cancelled` 终态。
  - 负例：`ATTACHMENT_SIZE_MISMATCH`（声明 98 实发 86 拒收）、`ATTACHMENT_SESSION_MISMATCH`（跨会话重绑拒绝）均如实返回。
  - UI：公网 bundle 已含附件按钮/模型选择器，agent-browser 快照正常、console 0 error。
- 验收会话经临时 `auth_sessions` 行（operator 铸 token，标注 `ops-acceptance`），验收后已全部 `revoked_at`；未触碰 keyring/密钥/Caddy 配置。`.env` 未改。compose.prod.yaml 远端与 repo 现已同步（worker S3 env + image tag）。

## 2026-10-23 — web-52e6c7a8 (二次同步：overlay 探针修复)

- **部署**：`rxycode-worker:web-52e6c7a8`（api/web 保持 `web-dfb6f356`——仅 worker 镜像含 userns 修复）。migrate 服务用 `RXYCODE_IMAGE_TAG=web-dfb6f356` 独立传参。三 worker 健康，pg/redis/minio 数据卷未动。
- **镜像构建**：pip 走 tuna mirror（index 0.5s vs pypi.org 死等 40min）、apt/npm 走 mihomo 7890 代理（apt 7.6s）、base image 走 docker.m.daocloud.io retag。dockerd 磁盘 99%→64% 清理后全量重建 ~8min/镜像。
- **线上 UI 实测**（铸临时 auth_session 验收）：「思考过程 (2 步)」可展开真实推理文本、「任务清单 (3/3)」三 check、工具行/产物块/console 零错——符合需求验收样。
- **延迟实测**（`GET /api/v1/runs/{id}` timings.phases）：

  | run | sandbox_probed 块 | prompt_dispatched 累计 |
  |---|---|---|
  | 修复前 `15d7d3d1` | ~8.5s（9158ms−645ms） | 14.1s |
  | 修复后 `aa5d8819` | ~33ms（521−488ms） | **3.9s** |

- **根因记录**：生产 worker 容器无 userns overlay 能力 → `overlay_dests` 全负；但探针对每候选先 copytree 后探测（/usr 662MB），负 verdict TTL 过期还会周期性重付。`_overlay_preflight` 一条 50ms `bwrap --unshare-user /bin/true` 让全负环境直接落缓存；候选改 /etc→/var→/usr 且首个双败即停。
- **验收临时会话已回收**（auth_sessions + device_locks 清理见 git note）。
