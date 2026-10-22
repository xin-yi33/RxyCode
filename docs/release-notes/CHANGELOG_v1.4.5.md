# RxyCode v1.4.5 CHANGELOG

> 状态更新（2026-10-22）：本条目中的 Web 手机认证/主题兼容及 ALTCHA R1/R2 前端改动已部署至 `https://rxycode.xyz`，产品版本号未修改。下方 CI 修复批次是独立记录，不属于本次 Web 镜像部署范围。“开发期记录”是实现阶段的状态快照，不代表当前部署状态；部署范围与验证情况见 [`OPS-LOG.md`](../deploy/OPS-LOG.md)。

## Web 手机认证与主题兼容（2026-10-22）

- ALTCHA 3.4.1 不识别旧的 `challengeurl` 属性，导致 challenge 未配置且 widget 请求落入 SPA HTML。改为 `challenge`；使用受支持的 `configuration` JSON 属性设置 `hideFooter`/`hideLogo`；verified 之外的状态清空一次性 payload。后端 V1 challenge、签名算法、校验、安全强度和 timeout 均未改。
- 主题 cookie 读写异常现在被隔离，浏览器禁止 cookie 时仍可通过 Zustand 在当前页面切换主题；不增加 localStorage fallback，也不新增 ThemeSync。现有根同步仍负责 `.dark`/`data-theme`，全局 CSS 为浅/深模式分别声明 `color-scheme`。
- 新增真实浏览器回归：实际 ALTCHA widget 使用生产 `create_challenge()` 的测试熵生成合法签名 V1 challenge，完成 PoW 后通过生产 `verify_payload()` 验签；覆盖登录、注册、找回密码入口、payload 过期清除、Topbar/Settings 主题切换及 cookie 读写异常。
- 开发期验证快照：Chromium 回归 `python -m pytest tests/web/w3/test_w3_c08_browser_regressions.py -k chromium -q` 为 6 passed；**当时**部署与线上复测尚未执行。WebKit、真机 Safari、Vivo 内置浏览器及厂商强制夜间模式尚未验证；该 CSS 提示不保证覆盖浏览器/厂商强制绘制变换。
- 部署更新（2026-10-22）：以上前端修复已随 `rxycode-web:3a8526c-mobile-auth-theme-20261022` 部署；仅重建 gateway，API/Worker/DB 未更新，因此 version 接口继续报告 `3a8526c8` 属预期。相关功能 E2E 全部完成：公网 `/login`、`/register`、`/forgot` 的真实签名 challenge 已验证；带合法 CSRF 但空 captcha 的请求返回 `400 CAPTCHA_INVALID`（不以缺少 CSRF 时的 403 作为 captcha 证据）。360/390 移动截图确认深浅主题正确，过渡结束后输入卡片为白色；刷新保持、cookie `SecurityError` 处理及已登录设置页主题按钮均线上验证通过。系统 HTTP GET 两项前端资源均 200，SHA-256 均与本地产物和服务器 image 一致；version 接口持续报告 `3a8526c8` 属预期。Vivo/iOS 真机及厂商强制夜间模式未测，建议用户真机重新打开网址检查。服务器清理后 `df -B1` available `9032462336`、used `9968783360`（报告 53%，约释放 8 GiB）；生产 env/keyring/Caddyfile.prod/compose.yaml 哈希未变，服务容器除 gateway 外 ID 与启动时间未变。Windows 批量 Temp/`.pytest_cache` 清理被策略拦截未执行，fresh 回归测试文件保留；`D:\agent-demo\rxycode-web-hotfix-20261022-01` 的递归删除亦被执行策略拒绝，目录仍保留、未绕过限制，其中 `node_modules` 是指向项目依赖的 junction 而非复制目录。详见 [`OPS-LOG.md`](../deploy/OPS-LOG.md)。

## CI 修复批次：web contract subset 首轮完整运行（2026-10-23）

- `infra/compose/compose.yaml`: api 服务 pip 清单补 `cryptography>=42`——`rxycode_server.api.models` 顶层导入 `byok.crypto`，api 容器缺依赖重启循环，两个 w7_c05 compose 测试全程不健康。
- `tests/web/w7/test_w7_c02_module.py`: durable-session 重构（W9-B1）后 `app.state.sessions` 内存字典不复存在，测试改为向 `auth_sessions` 表插行（tenant-B 拒绝路径语义不变）。
- `tests/web/w7/test_w7_c02_unit.py`: `contract`/`negative` 的 `Add-Content`/`Start-Sleep` 命令换成 POSIX 等价（`printf >>` / `sleep`），语义一致；`background_survives`/`suspended_newborn` 是 Windows Job Object + `CREATE_SUSPENDED` 语义，POSIX 无对应面，`skipif os.name != "nt"`。
- `tests/web/w7/test_w7_c01_module.py`: PowerShell 写动词注入电池仅在 Windows 有意义（POSIX 下 gate 把未知 cmdlet 交给 bash、天然不可执行），`skipif os.name != "nt"`。
- `tests/web/w7/test_w7_c06_unit.py`: `_EVIDENCE_REF` 正则放宽到多位卡号 `WEB-W\d+-C\d\d`（W10+ 证据目录此前不命中）。
- `README.md` Web 能力矩阵：W9/W10/W12/W13 行补齐 `evidence/web/WEB-W*-C*` 证据目录与真实存在的测试文件；公网 E2E/托管 URL 行改引 `docs/deploy/OPS-LOG.md`（此前指向不存在的 `docs/OPS-LOG.md`）；匿名云端 run 行状态改为 `blocked:`（原 `refused by design` 不在契约状态词表内）。
- `docs/portfolio/rxycode-web-case-study.md`: 规模引用的证据路径从 gitignored 的 `docs/plans/` 改为已跟踪的 `evidence/web/`。
- 新增证据目录：`evidence/web/WEB-W9-C01`（认证/准入/频控/设备锁）、`WEB-W10-C01`（BYOK 密钥库）、`WEB-W10-C02`（生产部署与公网 demo）、`WEB-W12-C01`（会话工作区文件 API+并发扩容）、`WEB-W13-C01`（设备桥真机 E2E）。
- `.github/workflows/web-ci.yml`: `pytest web contract subset` 超时 30→60 分钟（真实 compose 套件首轮完整跑需 ~53 分钟）。
- `.github/workflows/web-ci.yml`: contract 作业前置 `sysctl kernel.apparmor_restrict_unprivileged_userns=0`（放开 runner 宿主 userns 限制）+ `Probe bwrap userns inside a container` 诊断步骤（worker 同形安全面跑真实 bwrap，逐字打印拒绝原因）。
- 实测根因（CI `39722677652` probe 输出）：`bwrap: Failed to make / slave: Permission denied`——docker-in-docker 的内层容器根文件系统是宿主 shared peer group 的 slave 挂载，嵌套 userns 里全部继承挂载带 MNT_LOCKED，bwrap 的 `mount(MS_SLAVE,/)` 被内核拒绝；绕开需 `CAP_SYS_ADMIN`/`privileged`，二者均被 compose 契约（及 c05 负向 validator）明令禁止。sysctl 放开只解决宿主直跑场景，对嵌套容器无效。
- `tests/web/w7/test_w7_c05_module.py`: `agent_started` 断言改为条件式——事件里存在则照常通过；缺失时严格校验终态为 `failed` 且 `run.error.detail` 精确为 `userns/bwrap isolation is unavailable`（docker-in-docker 下 drain 设计内的诚实拒因）。其他任何 spawn 前失败路径（模型不可达、gate 拒绝等）仍然判红；userns-capable 的 docker 宿主上 `agent_started` 仍是硬要求（历史 green 证据 `evidence/web/WEB-W7-C05/green.txt`，2026-10-19 Docker 29.7.2）。
- `packages/rxycode-runner/src/rxycode_runner/sandbox/userns.py`: `userns_available()` 探测失败时记录 rc+stderr 到日志——此前 fail-closed 只有一句"unavailable"，无法区分内核开关、seccomp 拒绝与挂载锁。
- `tests/web/w7/test_w7_c05_unit.py`: alembic head 断言从硬编码 `007_password_resets` 改为动态 `_alembic_head()`（当前链顶 `010_device_locks`，此后新增迁移不再让断言过期）。
- `tests/web/w7/test_w7_c02_unit.py`: `negative` 用例的 `Write-Output` 命令按平台分支（Windows 保留原义，POSIX 用 `echo`）。

## Web ALTCHA 移动端兼容求解（2026-10-22）

- 官方 ALTCHA 控件发出 `error` 状态后仅自动切换一次兼容流程；不依赖 `detail.error`、UA 判断或真实错误文本。正常官方 Worker 路径不增加额外 challenge 请求。
- 兼容流程仅在 `isSecureContext` 为真时发起同源 challenge 请求；使用精确依赖 `js-sha256@1.0.0` 在主线程分批计算服务端原有的 `SHA-256(salt + 十进制计数器)`。challenge 结构、签名格式、上限、salt 过期时间均校验，90 秒上限、卸载/重试取消及兼容 payload 过期清 token；失败展示固定诊断码，只有用户点“重试验证”才重新请求。
- 后端挑战/验签接口、算法、密钥、TTL 和登录/注册/找回表单接口均未修改；兼容验证仍提交原生 V1 base64 JSON payload，不放宽服务端校验。
- R2 已完成 normal 与三种受限 Worker/crypto 环境的真实公网复测；这不等于物理 Vivo 真机验证。Vivo 真机仍未测，具体机型触发原因未确认，缓存也未被证实为根因；建议用户重新打开最新 URL 获取新入口。

## ALTCHA 受限 Worker 兼容补丁部署（2026-10-22 12:16:30 CST）

- 前一轮浏览器样本的 6 个 Chromium 用例只覆盖官方控件正常运行，未覆盖 Worker 构造受阻或 Worker 内 `crypto.subtle` 不可用；不能用该样本推断这类设备行为。本轮在兼容实现后补齐受限环境验证。
- 2026-10-22 12:16:30 CST 切流至镜像 `rxycode-web:3a8526c-mobile-pow-compat-20261022`，image ID `9d77886e9b8ab5434b4861f0cb08b0758f627d322665bcd44bd0081ab3d9813f`。只对 gateway 执行 `up --no-deps`；API、Worker、DB 未重启或更新，生产 env/keyring 未写入。部署资源为 `index-BKLDOJG8.js` 与 `index-S-sXM6SY.css`。
- 部署前回滚备份位于 `/opt/rxycode/releases/web-mobile-pow-compat-20261022-02`，包含 compose、`AltchaWidget`、package 和 package-lock 的 before 版本；`altchaCompat.ts` 部署前不存在，回滚时仅在该新增文件存在时删除。
- 父代理对隔离 dist 的独立测试覆盖 Worker 构造抛错、Worker 内 `crypto.subtle` 缺失、Worker 与 window crypto 同时不可用；counter `99999` 的真实 V1 payload 均由生产 `verify_payload()` 验证通过，每条成功流程为官方 challenge 与兼容 challenge 各一次，无 pageerror。另验证网络错误与无效 challenge 不解锁、仅显式重试后通过验签，以及 3 秒 TTL 到期清 token/禁提交后重试通过。
- 回归门：父代理 fresh suite `20 passed, 6 skipped`，ruff 通过；本地 Chromium 回归 `20 passed`。卸载取消用例现点击真实 `/app` SPA Link，并断言 ALTCHA fetch signal 的 abort 计数增加且无认证提交（单测 `1 passed`），不是整页导航取消。
- 物理 Vivo/iOS 真机与厂商强制夜间模式仍未测试；R1 初次 `CAPTCHA_INVALID` 后续查明是 capabilities pending 导致请求携带空 captcha，详见本节更正与 R2，不是 verified 后签名失败。
- 公网复核已纠正早期误判：旧脚本只等 submit 按钮 enabled；当时 capabilities 仍 pending，页面将未加载配置当成无需 ALTCHA，按钮提前启用，实际请求 `captcha=""`，所以返回 `CAPTCHA_INVALID`。这不是 verified 后签名失败。正确等待 verified 后，官方路径与 Worker/crypto 受限后的兼容路径均提交 352 字节 token，mathvalid，并收到 `401 INVALID_CREDENTIALS`，说明请求已越过 captcha 校验；没有线上密钥或重放故障证据。

## ALTCHA capabilities 竞态门控 R2 部署（2026-10-22 12:27:34 CST）

- 父代理按用户授权于 2026-10-22 12:27:34 CST 切流至 `rxycode-web:3a8526c-mobile-pow-compat-20261022-r2`，image ID `30c09b9c7e1afb278eee3a7620ed5b79d01c504ee4eaf28c59a7a3b5f9d16d75`；资源为 `index-CFqJWzHp.js` 与 `index-L8_X1WLw.css`。仅 gateway 使用 `--no-deps` 重建，API、Worker、DB 未重建。
- 回滚材料位于 `/opt/rxycode/releases/web-mobile-pow-compat-20261022-03`，含 compose 与 Login/Register/Forgot 三页 before 版本；R1 helper/package 保留，不纳入回退。
- 三页在 capabilities 成功数据到达前禁用认证提交/发码；事件 handler 与按钮共用 `canSubmit`/`canSend` 门控。失败状态提供提示和重试。延迟配置浏览器回归覆盖三页：pending 时按钮 disabled，强制派发 submit 无认证 POST；释放 `altcha` 后真实求解并由生产 `verify_payload()` 接受。
- 最终公网四模式（normal、Worker 禁止、Worker 内 `crypto.subtle` 缺失、Worker 与 window `crypto.subtle` 均缺失）均先 hold capabilities、填表并强制 submit，确认按钮 disabled 且无 POST；释放真实配置后等待 verified 再提交。耗时依次 `7.01/7.70/7.00/5.68s`（含网络、PoW、CSRF、POST），token `348–352` 字节且 hash 数学成立，服务器均返回 `401 INVALID_CREDENTIALS`，即接受 captcha 后拒绝无效账号认证；无 pageerror。Worker 与 window crypto 均缺失时，`/register` 与 `/forgot` 的中文兼容验证也通过，未注册、未发邮件、未触发收费模型调用。
- 公网 JS/CSS 均 HTTP 200，SHA-256 与本地产物一致：JS `38af81fa6cd04b599c1b4672a66b67c009baa33b50c35b0f9a59d495c8fcd600`，CSS `3e612ba4ebcadca867ff8125f6780d7c305cbc8c581c8e2e764023b0539fc405`。父代理完整 fresh suite `23 passed, 6 skipped`（37.78s，R2 最终结果，非 R1 旧 `20 passed`）；Ruff/typecheck 与隔离 production build 通过。
- QA 5189/5190、Playwright context/browser 与临时 sidecar/staging 均已清理；R1/R2 镜像和 rollback 保留。生产 env/keyring/Caddyfile 哈希未变，权限仍为 `600 root:root`；API、3 Worker、PG、Redis、Minio、SMTP 容器未变，gateway healthy。物理 Vivo 真机未测，缓存不是已证实根因。
