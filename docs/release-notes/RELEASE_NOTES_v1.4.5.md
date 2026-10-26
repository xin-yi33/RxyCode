# RxyCode v1.4.5

2026-10-26。产品版本 **1.4.5**。JSON-RPC 仍是 `1.1.0`，导入命名空间 `RxyCode1_1_0` 不变。本次 GitHub Release 只发布一个资源 `rxycode-1.4.5.tar.gz`（sdist）；没有 wheel，没有新的 Desktop 安装包，也没有 PyPI 1.4.5。`.github/workflows/release.yml` 会拒绝非 sdist 产物。

旧的 Desktop 安装包仍可从历史 Release（例如 v1.3.0 / v1.2.10）下载；它们都不是 1.4.5 构建。

## 安装

```bash
uv tool install --force --refresh "git+https://github.com/xin-yi33/RxyCode.git@v1.4.5"
```

或从下载好的 sdist 安装：

```bash
python -m pip install --no-cache-dir --force-reinstall rxycode-1.4.5.tar.gz
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.5/install.ps1 | iex"
```

macOS / Linux：

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.4.5/install.sh | sh
```

临时试用：

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.4.5" rxycode
```

## 这次你能直接感觉到的变化

### 1. 持久 Shell：状态留住，授权不留

交互式 `bash` 现在按会话复用一个受管 Shell。`export`、`cd`、`source venv/bin/activate` 和 shell 函数能跨调用保留，不再每条命令重开进程。

安全面没有变：每条命令仍然经过参数校验、风险分级、审批、journal、输出上限和 OS 沙箱。沙箱拒绝时 fail-closed，不降级成裸进程。取消、超时或 Shell 崩溃会清掉整棵进程树，并如实说“环境状态已丢失”，下次重建，不自动重放上一条命令。

边界：`RXYCODE_MANAGED_SHELL=0` 可关闭；`sandbox_mode=docker` 不启用（一容器一命令是隔离边界）；GUI 启动类命令仍走既有路径。

### 2. 写后即时诊断：写完就检查，失败不伪装成功

`write`、`edit`、`patch` 现在共用一个写后入口：

- Python：真实 `compile()`（不执行目标程序），项目有 Ruff 时再做一次有限的文件级检查；
- JavaScript：`node --check`；
- TS/TSX：项目自己的 `tsc --noEmit --project tsconfig.json`，使用项目编译选项；
- JSX 不用 `node --check`（JSX 不是合法 JS，只会制造假错误）。

报告把“文件已写入”和“检查结果”分开。状态有 `pass` / `problems` / `unavailable` / `timeout` / `cancelled` / `stale` / `not_checked`，只有 `pass` 算通过。检查器缺失、崩溃、解析失败、tsconfig `exclude` 掉目标文件，都如实报不可用；不会临时安装依赖。

项目自带的可执行检查器配置（例如 ESLint flat config、`compilerOptions.plugins`）需要显式信任：`diagnostics.run_project_config_checkers: true`、`full_auto`，或 `safety.auto_approve` 已含 `danger`。未授权时只跳过“执行配置”的那一个检查器，`tsc`（无 plugins）、`node --check`、Python `compile()` 等安全替代继续跑。

这只是快速语法 + 有限文件级 lint，不是项目级类型检查、测试或构建；Build 的完成门仍负责后者。

### 3. 子代理协作与归属

子代理不再只是“开一个子会话”：

- `spawn_subagent` 支持 `sync`、`async`、`stream`；
- `send_message_to_subagent` 可以向子代理补充指令，也可以向父会话汇报；
- `list_agents` 列出可用角色和运行中的子会话；
- `cancel_subagent` 停止跑偏的子代理；
- `/children`、`/child`、`/parent` 查看和切换子代理树，`@explore` 直接路由。

每个子代理有独立上下文、工具范围、权限策略和预算；父子归属由运行时决定，子代理不能自选特权来源标记。`async`/`stream` 的工具和进度事件记在子会话的 `child_session` 事件上，父会话在结束时收到摘要。`RXYCODE_SUBAGENTS=0` 可回到单 Agent 基线。

专家团仍默认关闭。`/agents on` 或 `/team <task>` 才进入，适合可拆分的大型工作；日常编辑走单 Agent。

### 4. 权限分档与安全边界

三档权限的实际行为：

| 档位 | 读 | 文件编辑 | Shell |
|---|---|---|---|
| `confirm_all` | 自动 | 询问 | 询问 |
| `auto_edit` | 自动 | 自动 | 询问 |
| `full_auto` | 自动 | 自动 | 自动，硬黑名单除外 |

`auto_edit` 下，`echo hi`、`ls`、`pwd`、`git status` 这类“只读命令”也不能绕过 shell 审批；shell 的审批级别至少是 `write`：READ 会提升到 `WRITE`，DANGER 保持 `DANGER` 不降级。为读工具准备的 `auto_approve: ["read"]` 不会顺带放行 shell，`auto_approve: ["write"]` 也不能放行 DANGER 命令。

硬黑名单在审批之前执行，命中直接拒绝，不进入审批，也不受 `full_auto` 影响。写路径只允许项目根和配置的输出目录。Plan 模式在执行层只读，写操作会被拒绝。审计日志在 `~/.RxyCode/logs/audit.jsonl`，敏感字段脱敏。

这里有一个必须保留的边界：硬黑名单是基于模式的兜底，不是数学证明。命令拼写、引号、解释器包装都可能变化；处理不可信内容时仍应保留 OS 沙箱和审批门。

### 5. Web：BYOK、附件、产物、预览与多端

**BYOK-only。** Web 只接受用户自己的模型连接。平台模型引用返回 `MODEL_NOT_FOUND`，未选择模型返回 `BYOK_REQUIRED`；旧的 `RXYCODE_BYOK_ENFORCE` 开关和平台 allowlist 不再放行平台凭据。这是相对 1.4.4 的策略变化：托管 run 必须自带 Key。本地 CLI 行为不变。

**附件。** 选择、粘贴、拖入三种入口；附件先暂存，再在 `create_run` 事务里校验租户/owner/ready/session/过期并绑定。导入失败会让 run 失败，不会静默丢附件假装成功。内置 DOCX/XLSX/PPTX 与 ODT/ODS/ODP 正文抽取（纯标准库，不新增 pip 依赖）；PDF、旧版 OLE Office、RTF、压缩包、图片会给出可操作提示。中文文件名保留，路径分隔符和控制字符会被中和。

**产物与预览。** turn 收尾对工作区做快照 diff，新增/修改文件登记到产物清单；`GET /runs/{id}/artifacts` 返回 `manifest_status`、`next_cursor` 和短签下载链接。下载支持 Range。预览支持图片、HTML 和文本族；HTML 转换页有 CSP `sandbox allow-scripts` 和 `nosniff` 双墙。PDF/Office 预览不支持，会如实失败，不谎报成功。

**问题卡与时间线。** 问题卡竖排、按 payload 顺序编号、单选；只有被点中的选项显示“提交中…”，一次点击只发一次 `POST /questions`。思考块可展开；任务清单合并 `plan.updated` 和 `todo.updated`，显示 `(done/total)`。

**多端兼容。** 390px 视口可用；Chromium 90/98/148 有真实浏览器验证，Playwright Firefox/WebKit 覆盖关键路径。真实 iOS/Vivo/Safari 真机未验证，不宣称全设备通过。

**界面打磨。** 输入区单层外壳、暗色字重、中文输入法 Enter 防误发、单一滚动控制器、流式逐字动效、平滑折叠、统一复制反馈、可拖拽预览分栏、长文件名中间省略。这些不改变协议或权限。

### 6. 长任务判活：一次真实验收，但整体不是全绿

2026-10-25 的线上 300 秒真实 run（`7d66a213314648ada8eec4aa112727d3`，owner BYOK `deepseek-v4.1-flash`，`confirm` 权限）结果：

- 目标脚本自然完成：`BEGIN=1792910857.712589`、`END=1792911157.7132807`、`ELAPSED=300.000691652298`；`tool.completed` 为 `status=success`。
- `process.liveness` 在 `180.003s` 给出物理采样：5.0 秒观察窗口、进程数 `3→3`、CPU `0.0%→0.0%`、IO `0KB→0KB`，owner BYOK 模型返回有效的 `continue`，UI 可见继续运行反馈。
- 经用户批准，判活不再额外包一层固定 15 秒 deadline，改为等待当前会话模型自身的请求超时；P6 的 15 秒 decision clock、任务/工具预算、续期、权限和杀进程规则都没有改。

**整体 E2E 仍是 NOT GREEN。** 目标完成后，模型又请求查找 workspace-root 脚本的额外审批 `ca7505f206d446169e16ff98ba0f38ed`（call `call_515e7ae3d59e36f2937bb4734580b725`，seq 453），随后停在 `waiting_approval` seq 456。该审批没有批准，命令没有执行；main 通过正常 cancel API 取消自己的 run（`cancel_requested` seq 457，最终 seq 463 为 `cancelled`），不是自然 `succeeded`。

这个额外审批是 **OPEN 现象**，目前没有核实根因，不把它命名为确定性产品 bug，也不为了凑 GREEN 盲改模块。

## 云与本机的边界

| 场景 | 在哪里执行 | 能不能碰你的电脑 |
|---|---|---|
| CLI / OpenTUI | 你的机器 | 能；受权限、审批、写白名单和可选 OS 沙箱约束 |
| 云端 Web run | 云 worker 的 per-run 沙箱 | 默认不能；只能访问租户工作区 |
| Web 上传/下载 | 租户工作区 | 只在你主动上传/下载时交换文件 |
| 设备桥 `rxycode connect` | 你配对的机器 | 能；每条 shell 调用过本地审批，且限制在 connect 启动目录 |
| Web `full` 权限 | 仍在云沙箱内 | 不能；它只取消审批提示，不关闭沙箱 |

公共 worker 只执行 `cloud:{tenant}:{workspace}` 目标，租户段必须等于 run 自己的租户。沙箱不可用时 run 直接失败，绝不回落到宿主机执行。`full`/`full_auto` 在 Web 上是审批语义，不是隔离级别；挂载、网络策略和可写范围都不变。

## 保持可用的既有能力

- MCP 仍走 stdio；MCP 工具和内置工具共用 `ToolOrchestrator`、审批、审计和重试。每个 server 的工具清单会记录 schema 面，变化时告警。
- `tool_search` 仍按需发现 MCP/插件/技能的工具定义；完整 discovery 留在消息上下文里，不被普通 2000 字符截断或去重吞掉。
- 专家团仍是确定性 SOP 状态机，默认关闭。
- 协议仍是 `1.1.0`；`RxyCode1_1_0` 是稳定导入命名空间，不是产品旧版本。

## 验证与已知限制

- Windows 本机目标回归、真实 `ToolOrchestrator` 链路、真实 ESLint/tsc 对照、子代理回收与权限分档都有测试；Linux 3.10 容器（Python 3.12）有真实进程矩阵和协议复验。macOS 实机未验。
- 历史 CI 基线：源码 `247be96e` 的 main CI `40166956475` 为 6/6 job success；docs `63fcde7b` 的 main CI `40173191825` 为 6/6。它们只对应各自提交，不等于 v1.4.5 tag 已通过；tag 需要自己的新 CI。
- Web E2E 的 300 秒判活只有一次 run、一个模型；额外审批 `ca750...` 仍是 OPEN。不要据此说“全场景全链路绿”或“没有已知问题”。
- Web 控制台是早期预览，跑在小 VM 上，worker 上限 3，没有 SLA。PDF/Office 预览不支持。真实 iOS/Vivo/Safari 未验；Chromium 90/98/148 与 Playwright Firefox/WebKit 是已验证范围。
- 1.4.5 只发 sdist；没有 wheel、没有新 Desktop 安装包、没有 PyPI 1.4.5。旧 Release 上的 Desktop 包不是 1.4.5 构建。

## 升级注意

- 从 1.4.4 升级到 1.4.5：CLI 安装方式不变，协议不变。
- 托管 Web 从平台模型切到 BYOK-only。已有平台模型引用不会自动迁移；需要在“模型与 BYOK”里添加自己的连接，并设为默认模型。
- 持久 Shell 是默认开启的受管路径；如果现有自动化依赖“每条命令全新环境”，设置 `RXYCODE_MANAGED_SHELL=0`。
- 旧 Desktop 安装包不受影响，但它不会获得 1.4.5 的 CLI/Web 改动。

## 链接

- 完整开发记录：[CHANGELOG_v1.4.5.md](CHANGELOG_v1.4.5.md)
- 上一版说明：[RELEASE_NOTES_v1.4.4.md](RELEASE_NOTES_v1.4.4.md)
- 仓库总 changelog：[CHANGELOG.md](../../CHANGELOG.md)
