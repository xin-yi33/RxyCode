# RxyCode v1.4.1 — CLI 维护版本

发布日期：2026-10-07。上一版本：v1.4.0。

本次发布 CLI / OpenTUI，唯一分发资源为 `rxycode-1.4.1.tar.gz`。
不发布 wheel 或新的 Electron Desktop 安装包。源码中的 Desktop 元数据同步
为 1.4.1，不代表发布了新的桌面二进制。

## 这次改了什么

### 可选 OS 沙箱与 Windows venv 修复

新增 `core/sandbox/`：Windows 使用 Job Object 限制内存、进程数并在关闭 Job
时清理进程树；Linux 使用 bubblewrap；macOS 使用 Seatbelt `sandbox-exec`。
配置位于 `execution.os_sandbox`，**默认关闭**，Docker 路线不叠加此沙箱。

Windows 生产 shell 路线在 spawn 前建立 Job，以 `CREATE_SUSPENDED` 创建
进程，绑定 Job 后才恢复主线程。它修复了“进程先跑再绑定”的子孙漏管竞态，
也避免 Python venv launcher 自建 Job 后再跨层重归属导致的拒绝访问。
绑定失败时拒绝执行并清理挂起进程，不静默放行。

边界：Job Object 是资源与进程生命周期控制，不等于文件系统或网络隔离。
Windows 上不能执行的 read-only、网络或 deny-glob 约束，根据配置 fail closed
或显式降级；受限令牌原语不等于已接入完整异步执行链。
MCP、Playwright 和 GUI 子进程不在本次覆盖范围；文件工具仍走现有权限闸。
Linux/macOS 原生沙箱执行未在 Windows 发布主机上验证。

### 日志保留与连接恢复

- 日志使用带时间戳的文件名，默认保留 72 小时；
  `RXYCODE_LOG_RETENTION_HOURS` 可覆盖。清理根据文件名时间戳，不依赖 mtime。
- 默认瞬态模型连接最多重试 7 次，退避从 2 秒递增，封顶 128 秒并带抖动。
  移除旧配置中的固定 5 次覆盖；已有本地覆盖配置仍有效。
- 同一逻辑工具回合里的传输重试不再重复计入外层熔断器，避免一轮弱网络请求
  提前打满失败阈值。永久错误不会因本次修改变成可重试错误。

### 会话、终端与开发任务可靠性

- 打开会话列表时发现 appserver 已退出，会重新启动而非显示空列表。
- stalled-job 降级后能继续接纳新会话。
- 修复 Windows 鼠标跟踪、会话列表点击事件时机与滚轮影响输入框光标的问题。
- 开发任务在尚未产生要求的文件时，不会因模型过早输出“最终结果”直接结束。
- Responses 拉流抛错按失败处理，不伪装成正常流结束。
- 废弃路线保留带原因的标注：旧 DSML 解析、history、LSP 和旧 scheduler。
  `/loop` 的 OpenTUI 权威仍是 appserver ScheduleService，不新增第二套调度器。

## 版本与兼容性

产品版本统一为 **1.4.1**：Python 元数据、console/module 入口、安装脚本、
OpenTUI/Ink 标题、前端包与锁文件、MCP 客户端标识、appserver 和 runtime manifest。

JSON-RPC 保持 **1.1.0**；MCP 协议版本不变。Python 导入路径
`RxyCode.RxyCode1_1_0` 是稳定命名空间，不随补丁版本重命名。
schema 的产品版本默认值与 runtime 摘要同步，并增加版本一致性回归测试。
旧版发布说明、历史 changelog 和旧 Desktop 资源名称保留原版本。

## 安装或升级

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.1/install.ps1 | iex"
```

macOS / Linux：

```sh
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.1/install.sh | sh
```

已安装 uv：

```sh
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.4.1"
rxycode --version
rxycode
```

或下载本页 `rxycode-1.4.1.tar.gz` 后安装：

```sh
python -m pip install --upgrade rxycode-1.4.1.tar.gz
```

CLI 包不含 Electron。不要把 `rxycode gui` 当作本版本安装后的桌面启动保证。
运行环境与备用入口见 [Quickstart](../quickstart.md)。

## 验证记录

发布前在 Windows 主机独立重跑：沙箱、真实 venv shell、取消契约、Agent 主链、
文档依赖与会话 catalog，共 **78 passed / 6 skipped**（19.93 秒）。六项跳过仅
对应本地被 Git 忽略且缺失或为空的计划文档，不代表运行时能力通过。

后续发布门禁结果在完成后补充。未完成的检查不标记为通过；GitHub Release
工作流仅在 Linux/Windows 分发安装冒烟通过后上传源码包。

实现阶段的完整修复原因和复跑记录见
[CHANGELOG_v1.4.1.md](CHANGELOG_v1.4.1.md)，概要见 [根 CHANGELOG](../../CHANGELOG.md)。
