<!-- README_SYNC: source=working-tree; updated=2026-09-02 -->
<div align="center">

[English](./README.md) · **简体中文**

# RxyCode

**给开发者用的本地规划-执行型编程助手：v1.3.0 把 Desktop 做成一等公民工作台；在 cmd 里输入 `rxycode` 仍是 OpenTUI。每次工具调用都先过安全门。**

[⭐ 给仓库点 Star](https://github.com/xin-yi33/RxyCode) —— 方便以后回来，也让同样在找「会规划、会调工具、危险操作会问你」的本地 Agent 的人更容易发现它。这一版 GUI 不再是停在 v1.2.10 的旧窗口。

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml/badge.svg)](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml)
[![Issues](https://img.shields.io/github/issues/xin-yi33/RxyCode)](https://github.com/xin-yi33/RxyCode/issues)
[![Stars](https://img.shields.io/github/stars/xin-yi33/RxyCode?style=social)](https://github.com/xin-yi33/RxyCode/stargazers)

</div>

## Desktop GUI —— 1.3.0 真正大的那一步

1.2.10 证明 Electron 能拉起 `python -m appserver`。**1.3.0 交出的是工作台：** 置顶 / 项目 / 最近、运行中任务条、权限三档、插件主栏、侧边对话、计划 / 目标，以及和上次一样的 Windows 安装器（可选目录、预览、桌面快捷方式）。Linux 发 AppImage。**本标签不对 macOS 打包。**

下面是对 <code>rxycode gui</code>（RxyCode Desktop）的实机录屏，不是效果图。

<p align="center">
  <video width="800" controls muted playsinline preload="metadata">
    <source src="docs/assets/gui-demo-v1.3.0.mp4" type="video/mp4">
    <a href="docs/assets/gui-demo-v1.3.0.mp4">RxyCode Desktop 1.3.0 实机录屏（mp4）</a>
  </video>
</p>

| 系统 | 从 [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) 下什么 |
|------|--------|
| Windows | `rxycode-desktop-1.3.0-setup.exe`（安装包：默认 `%USERPROFILE%\.rxycode\desktop`，可 Browse，桌面快捷方式默认勾选）或 `RxyCode.Desktop-1.3.0-win.zip`（便携包） |
| Linux | `rxycode-desktop-1.3.0.AppImage`（先 `chmod +x`；立刻退出则加 `APPIMAGE_EXTRACT_AND_RUN=1 ./rxycode-desktop-1.3.0.AppImage`） |
| macOS | 本版不提供安装包。请用 OpenTUI，或从源码 `npm run dev` |

<code>rxycode gui</code> 只会启动已经装好的 Desktop
（<code>~/.rxycode/desktop</code>、<code>RXYCODE_DESKTOP_DIR</code> 或 <code>--desktop-dir</code>）。
只装 CLI 无法打开桌面端。任务区底部仍是 Composer。点 `+` 仍是：文件和文件夹 / 在项目中使用 / 目标 / 计划模式。计划卡片仍提供 **是，实施此计划**、**补充说明** 和 **跳过**。权限档位：更改前询问 / 自动编辑 / 完全访问。设置「关于」显示 **1.3.0**。完整 GUI 说明：[docs/GUI.md](docs/GUI.md)。

## CLI / OpenTUI

默认 CLI 仍是 **OpenTUI**。在 `cmd`（或任意终端）里：

```bat
rxycode
```

<p align="center">
  <video width="800" controls muted playsinline preload="metadata">
    <source src="docs/assets/cli-demo-v1.3.0.mp4" type="video/mp4">
    <a href="docs/assets/cli-demo-v1.3.0.mp4">RxyCode OpenTUI 实机录屏（mp4）</a>
  </video>
</p>

同一套 <code>Session</code>、同一道安全门，只是换了表面。请播放上面的 mp4。

RxyCode 是一个 Python 编程 Agent。核心无界面：`Session`（`core/session.py`）包着 `AgentV2`。前端三条路：**Desktop**（`rxycode gui`）、**OpenTUI**（默认 CLI）、**Ink** 回退。复杂任务走 LangGraph：规划 → 拆解 → 执行 → 验证 → 综合；简单问题走快速路径。隔离式子代理、MCP 和 30+ 工具都挂在按风险分级的安全门后面。

## 1.3.0 大在哪

| 1.3.0 之前 | 1.3.0 之后 |
|---|---|
| 最新 GitHub Release 只有 CLI `tar.gz`；Desktop 停在 v1.2.10 | 本标签同时发 **Desktop + CLI**。Windows setup.exe / zip 和 Linux AppImage 是正式资产 |
| GUI 还是「能把后端拉起来的聊天窗」 | 三栏工作台：会话分类、运行态整行、sash 吸附、插件主栏、侧边对话 |
| Windows 新建会话发 `hi` 可能卡在 Starting Agent worker 直到 600s | worker bootstrap 不再和管道 stdin 死锁（`appserver/agent_worker.py`） |
| 插件连接偏 PAT | GitHub / Canva 走 `plugin/connect/start`；token 只进插件 `user.json` |

仓库里的时延 / 缓存硬门槛没放宽：简单首字 **1s**、复杂首字 **3s**、Primary 前缀缓存 **97%**（Phase L / M）。这是套在同一套 AgentV2 前缀上的门，不是 GUI 宣传数字。

## 特点与优势

| 特点 | 实际效果 | 代码位置 |
|---|---|---|
| Desktop 工作台 | 会话、项目、权限、插件、计划 / 目标走同一套协议 | `frontend/desktop-app/`、`appserver/` |
| 先验证再报成功 | 验证器对照原始目标检查工具结果 | `validation/` |
| 先规划再执行 | 分层拆解、按依赖并行执行，再综合答案 | `planning/`、`execution/`、`synthesis/`、`core/graph.py` |
| 每次工具调用过安全门 | READ / WRITE / DANGER 分级、写入白名单、审批框、审计日志 | `core/safety/` |
| OpenTUI 仍是默认 CLI | cmd 里输入 `rxycode`；stdio JSON-RPC | `frontend/opentui-app/` |
| 隔离式子代理 | 独立会话、工具、权限和预算 | `core/subagents/` |
| 可选专家团 | 团长 + SOP；默认关（`settings.agents.enabled`） | `core/agents/` |
| 无头核心 | `Session.prompt()` 自己不画界面；TUI / GUI 只订阅协议事件 | `core/session.py` |

## 快速开始

### 前置条件

| 要求 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 后端运行时 |
| Bun | 最新 | 一键安装在缺失时会自动装（OpenTUI） |
| Node.js | 20+ | Desktop GUI、Ink 回退（`RXYCODE_TUI=ink`） |
| OpenAI 兼容 API 密钥 | — | 你配置的任意提供商（OpenAI、DeepSeek、OpenCode Go 等） |

### 方式一：一键安装（CLI / OpenTUI）

**Windows PowerShell：**

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.ps1 | iex"
rxycode
```

**macOS / Linux：**

```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.3.0/install.sh | sh
rxycode
```

安装脚本会在需要时引导安装 `uv`，创建隔离环境，并安装钉死的 **`v1.3.0`**。这是 **CLI / OpenTUI** 包，不包含 Electron Desktop。

设置 `RXYCODE_NO_MODIFY_PATH=1` 可跳过改 PATH。PATH 更新失败只警告，安装仍算成功。

**下载说明：** 最新版（**`v1.3.0`**）发布 `rxycode-1.3.0.tar.gz`，以及 Desktop 资源（`rxycode-desktop-1.3.0-setup.exe`、`RxyCode.Desktop-1.3.0-win.zip`、`rxycode-desktop-1.3.0.AppImage`）。不提供 wheel，也不提供 macOS 安装包。GitHub 的 “Source code” zip/tar.gz 是完整前后端源码，用来自己构建，不是开箱即用的 Desktop。更细的步骤见 [docs/quickstart.md](docs/quickstart.md)。

### 方式二：一次性运行

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0" rxycode
```

### 方式三：永久安装

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.3.0"
rxycode
```

### 方式四：从源码安装

```bash
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode
python -m pip install -e .
rxycode
```

### 方式五：Docker

```bash
cp .env.example .env   # Set OPENAI_API_KEY and RXYCODE_API_TOKEN
docker compose up -d api       # API server (loopback only)
docker compose run --rm tui    # Interactive TUI (needs TTY)
```

### 首次启动

| 命令 | 打开什么 |
|------|----------|
| `rxycode` 或 `python -m RxyCode` | 默认 **OpenTUI** |
| `rxycode --version` | 打印包版本，不初始化运行时 |
| `rxycode gui` | 仅在已安装 Desktop 构建后打开（CLI/`uv` 安装不带 Electron） |
| `rxycode --api` | 只起 API（`api_server.py`） |
| `RXYCODE_TUI=ink rxycode` | Ink 回退 TUI |

1. 运行 `rxycode`。即使还没配模型，TUI 也会打开。
2. 若模型列表为空，OpenTUI 会提示并自动打开 `/addmodel`（凭据输入有掩码）。
3. 若 `~/.RxyCode/config.yaml` 里已有模型，则不再弹向导。
4. 直接用自然语言布置任务。例如：让它在当前目录写一个单文件 `click-counter.html`。
5. 无界面（`rxycode --api`）：先设置 `RXYCODE_API_KEY`，再运行 `rxycode config add-model <id> <provider-model-id> --base-url <url>`。密钥不会从命令行读取。

OpenTUI 和核心之间是 **stdio JSON-RPC**：前端拉起 `python -m appserver`，后者托管 `Session` → `AgentV2`。你会看到流式输出、工具调用、必要时的审批，以及最终回答。

## 架构

```
OpenTUI (frontend/opentui-app)     Desktop (frontend/desktop-app)
        │ stdio JSON-RPC                    │ stdio JSON-RPC
        └──────────────┬────────────────────┘
                       ▼
              python -m appserver
                       │
                       ▼
              Session (core/session.py)
                       │
                       ▼
              AgentV2 (core/agent_v2.py)
                 ├── simple query  →  fast path + cache
                 ├── multi-task    →  isolated child agents
                 ├── compose       →  Plan + Build
                 └── complex       →  LangGraph:
                       goal_planner → decomposer → executor
                            → ToolOrchestrator + core/safety
                            → validator → synthesizer

Ink fallback: RXYCODE_TUI=ink → api_server.py (HTTP + SSE) → same Session
```

`Session` 与传输无关：只发协议事件，不画界面。`appserver` 把事件写成 stdout JSON-RPC。`api_server.py` 把同一批事件映射成 SSE，给 Ink 用。

## 工作模式

| 界面 | 怎么开 | 行为 |
|------|--------|------|
| 构建 | TUI `/build` 或 Desktop 默认 | 规划 → 拆解 → 执行 → 验证 → 综合 |
| 规划 | `/plan` 或 Desktop 计划模式 | 只读分析并产出计划文档；点实施之前不改文件 |
| 编排 | `/compose` | 规划 + 构建（更短的管道） |

## 配置

配置在 `~/.RxyCode/config.yaml`。请求始终打向你选定的 `base_url`，**不会**被静默改成别的厂商。

```yaml
cache:
  enabled: true
  prompt_prefix_cache: true   # Provider-side KV cache
  ttl: 3600

# Example: OpenCode Go
models:
  opencode-go/deepseek-v4-flash:
    model_name: deepseek-v4-flash
    provider_id: opencode-go
    provider_name: OpenCode Go
    api_key_env: OPENCODE_GO_API_KEY   # or api_key_secret, stored outside the repo
    base_url: https://opencode.ai/zen/go/v1
    max_tokens: 8192
    temperature: 0.7
```

OpenTUI 里用 `/addmodel` 走引导向导。不要把 API key 写进仓库、README 或截图。

## 安全边界

工具真正执行前，`core/safety/` 会分级：

- **READ** — 只读检查（`read`、`grep`、`glob`、`webfetch` 等）
- **WRITE** — 可逆副作用（`write`、`edit`、多数 `bash`）
- **DANGER** — 破坏性或安装类命令；bash 可按模式升级（`rm -rf /`、`git push --force` 等）

白名单外的写入会被拦住。TUI 和 Desktop 弹出审批框；审计日志在 `~/.RxyCode/logs/audit.jsonl`，敏感字段会打码。Desktop 默认权限是「更改前询问」。

## 常用命令与快捷键（OpenTUI）

| 命令 | 说明 |
|------|------|
| `/help` | 全部命令（含专家团/子代理怎么用） |
| `/agents on` `/team <任务>` | 专家团（默认关；普通 coding 不自动走） |
| `/addmodel` | 添加模型（凭据掩码） |
| `/models` / `/model <name>` | 列出 / 切换模型 |
| `/build` `/plan` `/compose` | 工作模式 |
| `/clear` | 清除对话上下文 |
| `/memory add/list/search` | 记忆 |
| `/queue add/run` | 任务队列 |
| `/cache` | 缓存统计 |
| `/language` | 界面语言 |
| `/thinking` | 思考面板 |
| `/children` `/child` `/parent` | 隔离式子代理树（默认开；`RXYCODE_SUBAGENTS=0` 关闭） |

| 快捷键 | 作用 |
|--------|------|
| `Tab` | 切换工作模式 |
| `Ctrl+P` | 命令面板 |
| `Ctrl+T` | 开关思考内容 |
| `Esc` | 取消 |
| `Ctrl+C` | 复制 / 取消流式 / 清空输入；2 秒内连按两次退出 |

## 版本历史

| 版本 | 日期 | 要点 |
|------|------|------|
| [v1.3.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.3.0) | 2026-09 | **Desktop 工作台**（会话 / 插件 / 权限 / 计划）；Windows setup.exe + zip 与 Linux AppImage；worker bootstrap 死锁修复；CLI 仍是 OpenTUI；不对 macOS 打包 |
| [v1.2.12](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.12) | 2026-08 | Muse Spark + HY3；Responses 推理回放；自定义 `resource_path`；GitHub Release 只提供 `rxycode-1.2.12.tar.gz` — Desktop 仍在 v1.2.10 |
| [v1.2.11](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11) | 2026-08 | 专家团（默认关）；CLI 稳定性；GitHub Release 只提供 `rxycode-1.2.11.tar.gz` — Desktop 仍在 v1.2.10 |
| [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) | 2026-08 | 第一次交付 Desktop 计划 / 目标 / `+` 菜单；计划卡片实施/补充/跳过；默认 CLI 仍是 OpenTUI（`rxycode`） |
| [v1.2.9](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.9) | 2026-08 | 隔离式子代理（Phase C）：独立 Child 会话；`@agent`、Task 工具、`subtask=true`；OpenTUI 子代理树 |
| [v1.2.8](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.8) | 2026-08 | 模型适配：DeepSeek v4、豆包（ark）、Anthropic Claude 5；能力精确隔离 |
| [v1.2.7](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.7) | 2026-08 | 完成的回答不再被只读探测失败丢掉；搜索词更干净；豆包 provider |
| [v1.2.6](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.6) | 2026-08 | webfetch 解码、MCP 误路由、Windows shell/编码、搜索加固 |
| [v1.2.5](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.5) | 2026-08 | DeepSeek / 通义千问 / Claude 适配；延迟导入；显式路由；stdio 传输 |
| [v1.2.4](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.4) | 2026-08 | 添加模型体验；评测 harness；协议层与 TS 客户端 |
| [v1.2.3](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.3) | 2026-07 | 10 家预设、自动发现、批量添加 |
| [v1.2.2](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2) | 2026-07 | 自动安装 Bun 与 OpenTUI 依赖；无模型时打开 `/addmodel` |
| [v1.2.1](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.1) | 2026-07 | 安装包内带上 OpenTUI 源码 |
| [v1.2.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.0) | 2026-07 | 默认 OpenTUI（Ink 回退） |
| [v1.1.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.1.0) | 2026-07 | Ink TUI、SSE、Docker、CI、一键安装 |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | LangGraph 重写：规划-执行、工具、分层记忆 |
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | 初版：验证 + MCP |

完整记录见 [CHANGELOG.md](CHANGELOG.md)。分版本说明：[docs/release-notes/](docs/release-notes/)。专家团：[docs/agent/README.md](docs/agent/README.md)。

## License

[MIT](LICENSE) © RxyCode contributors

觉得有用就 [点个 Star](https://github.com/xin-yi33/RxyCode)，问题和改进直接开 [Issue](https://github.com/xin-yi33/RxyCode/issues)。
