# RxyCode v1.4.5 CHANGELOG

> 状态更新（2026-10-22）：本条目对应的 Web 改动已部署至 `https://rxycode.xyz`，产品版本号未修改。下方“开发期记录”是实现阶段的状态快照，不代表当前部署状态；部署范围与验证情况见 [`OPS-LOG.md`](../deploy/OPS-LOG.md)。

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
- `.github/workflows/web-ci.yml`: contract 作业前置 `sysctl kernel.apparmor_restrict_unprivileged_userns=0`——ubuntu-latest (24.04) 默认限制非特权 userns，worker 容器内 `bwrap --unshare-user` 被拒，`userns_available()` 探测为 False，drain fail-closed 直接 failed、confined turn 从未 spawn（全部事件父进程所写，缺 `event/agent_started`）。放开 runner sysctl 让真实内核沙箱边界在 CI 运行，turn 仍在 bwrap 内执行。
- `tests/web/w7/test_w7_c05_module.py`: `agent_started` 缺失断言改为带完整 `kinds` 列表与 `run.error` payload 的自诊断报错；断言本身未放宽（turn 仍必须真实 spawn）。
- `tests/web/w7/test_w7_c05_unit.py`: alembic head 断言从硬编码 `007_password_resets` 改为动态 `_alembic_head()`（当前链顶 `010_device_locks`，此后新增迁移不再让断言过期）。
- `tests/web/w7/test_w7_c02_unit.py`: `negative` 用例的 `Write-Output` 命令按平台分支（Windows 保留原义，POSIX 用 `echo`）。

## Web ALTCHA 移动端兼容求解（2026-10-22）

- 官方 ALTCHA 控件发出 `error` 状态后仅自动切换一次兼容流程；不依赖 `detail.error`、UA 判断或真实错误文本。正常官方 Worker 路径不增加额外 challenge 请求。
- 兼容流程仅在 `isSecureContext` 为真时发起同源 challenge 请求；使用精确依赖 `js-sha256@1.0.0` 在主线程分批计算服务端原有的 `SHA-256(salt + 十进制计数器)`。challenge 结构、签名格式、上限、salt 过期时间均校验，90 秒上限、卸载/重试取消及兼容 payload 过期清 token；失败展示固定诊断码，只有用户点“重试验证”才重新请求。
- 后端挑战/验签接口、算法、密钥、TTL 和登录/注册/找回表单接口均未修改；兼容验证仍提交原生 V1 base64 JSON payload，不放宽服务端校验。
- 线上 Chromium/Vivo-like UA 新旧资源和具体真机故障根因仍由独立复测确认；本次客户端兼容实现本身不声称已验证具体用户设备根因。
