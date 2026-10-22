# Full Native / Remote Grant / Cloud Isolation 权限合同

> **最高产品不变量**：用户选择本地 Full，`NativeLocalBackend` 就直接调用 OS，不经过任何 Sandbox。安全设计必须服务于这一行为，而不是将 Sandbox 冒充本机执行。

## §1 三个正交维度

- `target`：`local:<host>`, `remote:<device>`, `cloud:<sandbox>` —— **去哪执行**。
- `permission`：Ask / Auto / Full —— **是否逐项确认**。
- `isolation`：native / locally_restricted / cloud_isolated —— **进程与资源边界**。

冻结组合：**local + Full → native、无逐工具审批；remote + Full + 本机有效 grant → native、在已授权会话内无逐工具审批；cloud + Full → cloud_isolated，不获得本机权限。** 其他权限受现有 ToolOrchestrator/Python OS sandbox 管控，Runner 仍执行最终授权检查。

## §2 本机实际执行能力矩阵

| 能力 | Windows 实现方向 | 真实系统约束（不等于 Sandbox） |
|---|---|---|
| Shell 与后台进程 | `asyncio.create_subprocess_exec`, Win32, ConPTY | 以 Runner 登录用户权限运行；UAC 提权需要 OS 认可 |
| 文件 | `pathlib`, OS handles, 原工具适配 | 可直接操作用户指定目录；权限拒绝则报 OS 错误 |
| 截图 | `mss` / Win32 Graphics Capture | 需要当前交互式桌面；锁屏和 secure desktop 不承诺支持 |
| 键鼠 | Win32 `SendInput`, UI Automation | 要处理 DPI、多屏和窗口聚焦；用户随时急停 |
| 窗口 | Win32 enumerate/focus | 普通窗口可操作；受保护窗口遵循 OS 权限 |
| 浏览器 | Playwright/CDP 独立 profile | 不静默连接用户私人 Chrome 或复用 session cookies |
| macOS / Linux | Accessibility / X11/Wayland API | 需要明确系统授权，Wayland 不承诺全能 |

Native Full 测试应检查没有调用 `SandboxBackend` 或 `wrap_command`，并通过真实 OS 进程所有者/工作目录/截图确认运行地点。这样既不把 Full 关回沙箱，也不夸大 OS 的安全机制。

## §3 Remote Full 信任链

1. Web 账户绑定设备：Runner 通过出站 WSS 建立认证连接；服务端只能投递请求，不能直接写本机授权。
2. 用户选择设备并请求 Remote Full，包含 `run/session, workspace roots, capabilities, expires_at`；**本机可信 UI** 显示并确认，会话 grant 本机保存。
3. Runner 逐调用验证本机 grant 覆盖当前 call，不信 Server 传的 `permission="full"` 字符串；允许范围内跳过逐项审批。
4. 本机托盘/热键急停优先于远程消息；吊销 grant/设备、超时、断线后拒绝新工具，记录在途操作是否确认停止。
5. Cloud Worker 有机会看到工具结果/文件内容；用户需要“严格私有”时必须选择 Worker 也在本机的 Local 模式，不得误导。

## §4 云端 Sandbox 严格边界

Docker + gVisor 是候选实现，独立 sandboxd/VM 可替换；单独隔离 workspace、进程、UID、网络出口、CPU/内存、浏览器 profile、密钥和 Artifact。公共 Demo 禁 privileged 容器、Docker socket 与宿主 root mount；Cloud Full 只能在隔离工作区“Full”。缺失隔离时 **fail closed**，禁止回退到 API 主机的 subprocess。

## §5 攻击面与测试

| Threat | 防御 | 测试 |
|---|---|---|
| 跨租户 IDOR：Run、Session、SSE、Artifact、Device | 每资源服务端 owner/tenant 校验 | SEC-IDOR-01 |
| Server 被攻破自行提升远程 Full | 本机 grant 为最终权威 | SEC-GRANT-01 |
| 设备 revoke 与在途 invoke 竞态 | revocation epoch + 本机监护进程 | SEC-REVOKE-01 |
| Prompt injection 诱导读取私钥 | 不可信内容隔离、敏感操作权限和审计 | SEC-PI-01 |
| Preview/HTTP SSRF 访问宿主/云元数据 | sandbox 限制出口 + 认证端口代理 | SEC-PORT-01 |
| 工具路径 symlink/path traversal | Runner 受限模式真实路径/handle 策略 | SEC-PATH-01 |
| Trace/screenshot/API key 泄漏 | 脱敏、服务端加密、TTL、密钥最小权限 | SEC-SECRET-01 |
| WS 重放/伪造 RPC | TLS、设备身份、call_id、fencing、grant scope | SEC-RPC-01 |

Web 隐藏 Full 按钮不是安全策略；命令黑名单不是沙箱；Windows Job Object 资源限额不是完整文件/网络隔离。**Full 不是禁用审计、急停和授权控制**。
