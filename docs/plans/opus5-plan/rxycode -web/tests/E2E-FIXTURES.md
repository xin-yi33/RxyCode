# E2E Fixture / Demo Users / Controlled OS / Failure Injection

> 任何公共 E2E 演示都只能使用专门测试用户、测试仓库、受限云端 Sandbox 或受监管的本机无害项目。**严禁在用户私人电脑运行 destructive 负测**。

## §1 固定假设

`test_user_a`、`test_user_b`：独立租户/组织；`repo_auth_fixture`：公开许可的小型认证服务示例项目，固定 commit/hash；`repo_ui_fixture`：可启动真实 dev server 的示例 Vite 项目；`test_device_win`：Windows Runner（单独专用测试目录，含允许截图/桌面点击的测试应用）；`sandbox_a`/`sandbox_b`：隔离的 gVisor 目标；`cost_budget`：明确额度上限。真实 OAuth 网络测需要专门 GitHub Test Org，不使用用户私人主仓作为自动化测试目标。

## §2 Web 与 Full E2E

| ID | 真实路径 | 成功判据 | 失败分支 |
|---|---|---|---|
| E2E-WEB-01 | Web 登录/LocalOnboarding→Project→Run | 刷新后项目和任务仍可见 | 401/CSRF/Repo 无权限 |
| E2E-WEB-02 | 真 Run 中关闭 SSE/重新登录 | 严格 seq 无丢/重/越权 | gap/expired cursor |
| E2E-WEB-03 | 审批要求→关页→重启 Worker→决定 | Graph 安全继续、工具至多一次 | 决定过期/拒绝 |
| E2E-WEB-04 | File edit→Tests→Diff→Review | 真实文件 hash 改变、测试结果可验证 | revision conflict/test failure |
| E2E-WEB-05 | xterm.js→ConPTY/PTY→交互→退出 | stdout/input/resize/exit_code 真值一致 | session owner 不匹配 |
| E2E-WEB-06 | Mobile 375/768/1440/keyboard | 无关键阻塞，审批/取消可达 | API failure/disconnected |
| E2E-FULL-01 | Local Full native shell/file | native pid/用户名/文件路径真实 OS、无 SandboxBackend | OS 拒绝与 unsafe target |
| E2E-FULL-02 | Windows screenshot/window/click | 普通测试应用可被点击/读回 | 锁屏/高 DPI/权限不足 |
| E2E-FULL-03 | Pair `rxycode connect` | WSS handshake/设备 online | token expired/duplicate connection |
| E2E-FULL-04 | Remote call→网络断开→status query | 同 call_id 无重复写入 | ACK 丢失/unknown |
| E2E-FULL-05 | 本机确认 grant→工具→revoke | grant scope 范围内无逐项审批，撤销后拒绝 | Server 伪造 Full |
| E2E-FULL-06 | 本机运行长进程→脱网→急停 | 杀整个受管进程树，无残留 | 无网络时本机急停 |
| E2E-CLOUD-01 | tenant A/B 各启动 sandbox | 文件、进程、网络隔离 | metadata、host file escape |
| E2E-CLOUD-02 | sandbox 启 devserver→预览 | 经认证 proxy 看见页面 | 跨用户端口/SSRF |
| E2E-CLOUD-03 | GitHub 测试 repo→tests→branch→PR | PR URL 与项目真实修改对应 | 无 scope/重复 PR |
| E2E-CLOUD-04 | 多用户并发/配额/沙箱 GC | 不串状态；quota 返回受控错误 | orphan sandbox/leaked ports |
| E2E-BROWSER-01 | Playwright navigate/click/snapshot | 真实 DOM/事件可观测 | 用户 Chrome cookies 不泄漏 |
| E2E-TEAM-01 | Solo/Team 同任务运行 | 真实 child trace/费用/状态 | intermediate 误进 final |
| E2E-PRODUCT-01 | Schedule→background Run→notification | 即使 Web 关闭也触发并通知 | 重复通知/泄漏 |
| E2E-CHAOS-01 | Run→Worker kill→恢复 | 不重复副作用，状态有回归证据 | checkpoint corrupt |
| E2E-SECURITY-01 | A/B 账号与假恶意网页/URL | 数据隔离、Local grant、preview all denied | 伪造 id/token/target |
| E2E-EVAL-01 | Eval fixture 5 任务+trace | 成功与失败都存报告、任务 hash 可复核 | LLM Key 无时必须标未跑 |
| E2E-DEPLOY-01 | 干净 Compose→migration→HTTPS Demo | Cloud 工具真实运行且租户独立 | DB/Queue unavailable |
| E2E-PORTFOLIO-01 | 第三人照 README 操作 | 从零安装、完成三个 Demo、读取真实测量 | 未部署或功能未开不冒充 |
| E2E-RELEASE-01 | 首次使用 Local/Cloud/Remote | 三路径同 Agent 核心且独立执行目标真实 | Remote 未授权不执行 |

## §3 测试隔离 / 时间与负测

- 需要跨天行为时通过可控 clock/time provider 前进，而不是 CI 真等 24 小时；同时真实进程退出/恢复必须真实执行。
- 开发机运行真机 Full E2E 只在临时工作区、测试应用、无破坏性命令；模拟危险命令仅测试权限 gate，不执行破坏性真实调用。
- 浏览器 E2E 使用不同 user data directory，不共享个人 Chrome OAuth 登录会话；浏览器截图必须与 API trace、DB 事件对账。
- Linux Cloud Sandbox 网络负测隔离在测试虚拟环境；不得在生产云上尝试未授权越界攻击。
