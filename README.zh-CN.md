<!-- README_SYNC: source=working-tree; updated=2026-09 -->
<div align="center">

[English](./README.md) · **简体中文**

# 🚀 RxyCode

**开源本地 AI 编程智能体。模型你挑，代码不出你的电脑。**

[![Version](https://img.shields.io/badge/version-1.2.11-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml/badge.svg)](https://github.com/xin-yi33/RxyCode/actions/workflows/ci.yml)
[![Stars](https://img.shields.io/github/stars/xin-yi33/RxyCode?style=social)](https://github.com/xin-yi33/RxyCode/stargazers)

<p>
  <img src="docs/assets/cli-demo.gif" alt="RxyCode 终端演示" width="800">
</p>

[⭐ 点 Star](https://github.com/xin-yi33/RxyCode) &nbsp;·&nbsp; [⚡ 快速开始与部署](#-快速开始与部署) &nbsp;·&nbsp; [🔑 核心亮点](#-核心亮点) &nbsp;·&nbsp; [🖥️ 怎么用](#️-怎么用) &nbsp;·&nbsp; [文档](docs/)

</div>

RxyCode 是一个跑在本地的编程 Agent。你给一个 OpenAI 兼容的 API Key（DeepSeek、通义千问、Kimi、Claude、GPT、GLM、豆包……随便哪家），它就能帮你拆任务、写代码、跑命令、搜网页，做完了还会自己验一遍。终端 TUI 开箱即用，桌面 GUI 可选装，MCP 和 Skill 想扩展就扩展。

> 💡 **想立刻试试？** 有 Python 环境直接免安装运行：  
> `uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.2.11" rxycode`  
> 完整安装、桌面客户端、Docker 容器化与 Node.js 前端构建见下文 [⚡ 快速开始与部署](#-快速开始与部署)。

---

## 🔑 核心亮点

### 👥 多智能体 & 专家团队

RxyCode 不只是单个 Agent 在干活。

**隔离子代理**：碰到复杂任务，RxyCode 会自动拆分出子代理。每个子代理有自己独立的会话、工具集、权限和 Token 预算，互不干扰。你可以用 `/children` 查看子代理树，用 `@agent` 提及特定代理委派任务。

**专家团队模式**：`/agents on` 打开后，你得到的不是一个 Agent，而是一个完整的开发团队。内置的 `software_dev` 团队有 10 个角色、7 个阶段：

```
产品经理 → 架构师 → 前端工程师 ∥ 后端工程师 → 测试工程师 → 机械验证 → 安全审计 ∥ 质量审计 ∥ 可维护性审计 → 文档
```

几个关键设计：
- **确定性 SOP 状态机**驱动阶段流转，不是 LLM 拍脑袋决定下一步该谁干。不像 CrewAI 的 20% 路由决策藏在 LLM 里没法调试，也不像 AutoGen 的开放式群聊烧 Token 不可控
- **前后端并行实现**，三视角审计（安全 / 质量 / 可维护性）也是并行的
- **机械验证门**：文件存在、能 parse、lint 通过、测试跑过——低层检查全过了才让 LLM 审计，审计结论绑 SHA-256。省钱，且可复现
- **四道成本闸门**（BudgetGuard）：Token 预算、墙钟时间、委派次数、咨询次数，任意一道触发就停下来返回部分结果。不会烧穿你的 API 额度
- **默认关着**。老实说，目前评测下来单代理在大多数任务上又快又省（团队模式 Token 约 3x，耗时约 2.5x），只有可拆分的大型结构化项目才值得开

你也可以自己定义团队——写个 YAML 定义角色、SOP 阶段和工具集，`validate_team` 校验通过就能用。

### 🧠 规划 → 执行 → 验证

复杂任务走 LangGraph 流水线，不是一次性丢给模型让它随便写点东西：

1. **目标规划**：拆解用户意图，建立 TaskTree（最多 4 层 64 节点）
2. **依赖调度**：按依赖关系调度子任务，独立的任务并行跑
3. **执行**：调用工具干活，每个子任务只看自己依赖链上的上下文，不会被无关信息污染
4. **验证**：先跑确定性检查（语法、diff、测试），再拿结果和原始需求对一遍。验不过就反思错误类型（规划问题 / 推理问题 / 工具问题），决定重试还是重新规划
5. **综合**：最终答案的每个断言都必须有对应的工具执行证据（文件 diff、命令输出），不能凭空编造

简单问题走快速路径 + 二级缓存（精确哈希 + 语义匹配），不绕弯子。

### 🛡️ 严格安全门控

每一次工具调用在执行前都会被分级：

| 等级 | 例子 | 处理 |
|------|------|------|
| READ | 读文件、grep、抓网页 | 直接放行 |
| WRITE | 写文件、编辑、Shell | 要审批（可配成自动） |
| DANGER | `rm -rf /`、`git push --force`、`format C:` | 必须明确批准 |

Shell 命令会被动态重新分级——普通 `bash` 是 WRITE，但里面出现 `rm -rf` 或 `curl | sh` 会自动升到 DANGER。写文件只能写项目目录和 `~/.RxyCode/output/`，别的路径直接拒绝。完整审计日志在 `~/.RxyCode/logs/audit.jsonl`，敏感信息自动脱敏。

还有个演练模式：`RXYCODE_DRY_RUN=1`，所有写操作只预览不执行。

### 🏠 本地运行，模型自选

Claude Code 绑 Claude 订阅，Codex 跑在 OpenAI 的服务器上。RxyCode 是 MIT 开源、跑在你自己机器上，代码不出本地。用什么模型你说了算——DeepSeek、千问、Kimi、豆包、硅基流动这些国内厂商原生支持，不用套壳、不用中转。

### 🔧 30+ 内置工具 & MCP 扩展

| 类别 | 工具 |
|------|------|
| 文件 | read, write, edit, patch, glob, grep, ls, view, open |
| Shell | bash（带超时、输出截获、风险自动分级） |
| Git | status, diff, commit, log 等 |
| 网络 | 搜索（DDGS 免费搜、不用 Key）、抓网页、下载文件 |
| 视觉 | 多模态 LLM 分析图片、截屏 |
| 代码 | 格式化、诊断、LSP（实验性） |
| 记忆 | 跨会话的持久化知识（add/search/list） |
| 子代理 | 隔离子代理、`@agent` 提及、任务委托 |
| MCP | 接任意 stdio MCP 服务器 |
| 工作流 | 沙箱子进程内多步脚本执行 |

不够用？接个 MCP Server：

```yaml
# ~/.RxyCode/config.yaml
mcpServers:
  postgres:
    type: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-postgres"]
    env:
      DATABASE_URL: "postgresql://..."
```

MCP 工具和内置工具走同一套安全门，挂了自动退避重连，不影响主流程。

### 🧠 分层记忆 & 代码库 RAG

不是每次对话都从零开始：
- **短期记忆**：最近 10 轮对话的滑动窗口
- **长期记忆**：超过阈值自动压缩成摘要持久存储
- **用户知识库**：`/memory add` 手动存的事实，跨会话可用
- **向量经验库**：过去成功的执行方案和错误日志，下次遇到类似任务会参考
- **代码库 RAG**：AST 级别的代码切块 + 向量搜索 + 基于 PageRank 的仓库地图。后台增量索引，文件一改就更新

---

## ⚡ 快速开始与部署

根据你的使用习惯，选择适合的安装或部署方式：

### 1. 极速免安装试用 (推荐)

只要本地有 Python 3.10+，无需全局安装任何文件，即开即用：

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.2.11" rxycode
```

### 2. 一键脚本安装 (CLI 推荐)

安装器会自动安装 `uv`（若缺失）、配置独立隔离环境，不污染系统全局 Python：

- **Windows (PowerShell)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.11/install.ps1 | iex"
  ```
- **macOS / Linux**:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.11/install.sh | sh
  ```

安装成功后，在任意终端输入 `rxycode` 即可启动。

### 3. Docker 容器化部署

适合希望在纯净沙箱环境运行，或需要后台常驻 API 服务的使用场景。

**步骤 1：克隆代码与配置环境变量**
```bash
git clone https://github.com/xin-yi33/RxyCode.git && cd RxyCode
cp .env.example .env
# 编辑 .env 文件填入你的 OPENAI_API_KEY 及随机生成的 RXYCODE_API_TOKEN
```

**步骤 2：启动服务**
- **方式 A：无头 API 服务模式（常驻后台）**
  ```bash
  docker compose up -d api
  ```
  启动后会在 8765 端口提供兼容的 HTTP / SSE 流式 API。
- **方式 B：交互式终端 TUI 模式（需要交互 TTY）**
  ```bash
  docker compose run --rm tui
  ```

**自定义单镜像构建运行：**
```bash
docker build -t rxycode:latest .
docker run -it --rm -v ~/.rxycode:/root/.rxycode --env-file .env rxycode:latest
```

### 4. Node.js 前端开发与构建

RxyCode 拥有独立的前端体系，核心协议通过 stdio JSON-RPC 与后端通信：

- **默认终端 OpenTUI（Bun + React 19）**：  
  代码位于 `frontend/opentui-app/`。CLI 安装器会自动处理 Bun 依赖；如需二次开发：
  ```bash
  cd frontend/opentui-app
  bun install
  bun run build
  ```
- **备用 Ink 终端（Node.js 20+ + React 18）**：  
  代码位于 `frontend/`。如果你的环境更适合标准 Node.js：
  ```bash
  cd frontend
  npm install
  npm run build
  # 运行指定切换为 Ink 引擎：
  RXYCODE_TUI=ink rxycode
  ```
- **桌面客户端 Desktop GUI（Electron 39 + React + Vite）**：  
  代码位于 `frontend/desktop-app/`：
  ```bash
  cd frontend/desktop-app
  npm install
  npm run dev       # 启动开发调试
  npm run build     # 打包生成安装包（Win / macOS / Linux）
  ```
  > 普通用户无需自行编译桌面端，可直接在 [v1.2.10 Release](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) 下载打包好的客户端，安装后终端运行 `rxycode gui` 即可。

### 5. Python 源码安装

适合二次开发与贡献者：

```bash
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -e .
rxycode
```

---

## 🤖 首次启动与模型配置

安装完成后，在终端运行 `rxycode`：

1. **首次向导**：如果尚未配置模型，会自动弹出 `/addmodel` 引导对话框。
2. **安全输入**：选择供应商预设，输入 API Key 时自动加密脱敏（Windows 使用 DPAPI，POSIX 使用 0600 凭证存储），不会明文保存。
3. **支持厂商预设**：

| 厂商 | 常用模型标识 | 适配特性 |
|------|-------------|---------|
| **DeepSeek** | `deepseek-v4`, `deepseek-v4-flash` | 原生 reasoning_content 解析与 thinking 档位控制 |
| **Moonshot (Kimi)** | `kimi-k3`, `kimi-k2.7-code` | 适配 prompt cache 与 reasoning_effort |
| **阿里云百炼（通义千问）** | `qwen3.7-max`, `qwen3.8-max-preview` | 显式断点缓存控制 |
| **火山方舟（豆包）** | `doubao-seed-2.1-turbo` | 火山引擎 Ark API 适配 |
| **智谱 (GLM)** | `glm-5.2` | GLM 原生流式协议 |
| **SiliconFlow 硅基流动** | 常见主流开源模型 | 高并发高速中转 |
| **OpenAI** | `gpt-4o`, `o1`, `o3` | 官方标准接口 |
| **Anthropic** | `claude-sonnet-4.5` | 显式断点 prompt cache 与 thinking blocks |
| **OpenRouter / Groq / Together** | 聚合或极速模型 | 全面兼容 OpenAI 格式 |

配置保存在 `~/.RxyCode/config.yaml` 中，随时可通过 `rxycode config list` 或终端内 `/models` 查看。

---

## 🖥️ 怎么用

### 终端交互 (默认 OpenTUI)

输入 `rxycode` 启动，直接用自然语言吩咐任务：

- `"把 auth 模块从 session 改成 JWT 鉴权"`
- `"检查当前项目里有没有 SQL 注入或敏感文件读取漏洞"`
- `"给 user 服务写一套包含增删改查的测试用例，用 pytest 跑通"`
- `"调研 Python 3.13 free-threaded 模式的改动并整理成文档"`

常用快捷键：

| 按键 | 功能 |
|------|------|
| `Tab` | 切换工作模式（Build 构建 / Plan 规划 / Compose 紧凑） |
| `Ctrl+P` | 调出全局命令面板 |
| `Ctrl+T` | 打开/折叠模型思考过程面板 |
| `Esc` | 中断当前任务或退出弹窗 |

<details>
<summary>常用斜杠命令</summary>

| 命令 | 作用 |
|------|------|
| `/build` | 规划→执行→验证（默认全自动模式） |
| `/plan` | 仅分析并输出执行计划，严禁擅自改动代码 |
| `/compose` | 紧凑编排模式 |
| `/addmodel` | 交互式添加模型提供商 |
| `/models` | 查看和快速切换当前模型 |
| `/agents on` | 开启多智能体专家团队模式 |
| `/team <任务>` | 直接向专家团队发起任务 |
| `/memory add/list/search` | 管理跨会话知识与事实 |
| `/children` `/child` `/parent` | 查看子代理树与层级切换 |
| `/language` | 切换界面语言（支持中文 / 英文） |
| `/help` | 查看所有指令与帮助 |
</details>

### 🖥️ 桌面客户端 (Desktop GUI)

安装桌面版后，在命令行执行 `rxycode gui` 启动。

<p align="center">
  <img src="docs/imgs/gui-shell.png" alt="RxyCode Desktop 桌面主界面" width="700">
</p>

- **Plan 计划卡片**：展示多步分解计划，提供“实施此计划”、“补充说明”、“跳过”等交互。
- **目标对话框 (Goal Dialog)**：常驻显示当前任务目标，随时调整方向。
- **Composer `+` 菜单**：一键关联本地文件/文件夹、切换项目工作区。
- **三档安全权限**：更改前询问 / 自动编辑 / 完全访问。

<details>
<summary>桌面端功能截图</summary>

<p align="center">
  <img src="docs/imgs/gui-plus-menu.png" alt="加号菜单" width="700">
</p>
<p align="center">
  <img src="docs/imgs/gui-goal-dialog.png" alt="目标对话框" width="700">
</p>
<p align="center">
  <img src="docs/imgs/gui-plan-card.png" alt="计划卡片" width="700">
</p>
</details>

### 无头 API 服务

如需将 RxyCode 作为后台服务供外部系统调用：

```bash
rxycode --api   # 启动 FastAPI HTTP + SSE 流式服务，默认端口 8765
```

---

## 🏗️ 架构设计

```
rxycode (OpenTUI) / rxycode gui (Desktop) / rxycode --api
                     │
                     ▼ (stdio JSON-RPC / HTTP SSE)
       appserver (会话进程隔离 / 假死检测 / 心跳 Watchdog)
                     │
                     ▼
         Session (无头门面，纯状态与事件发射)
                     │
                     ▼
                 AgentV2
  ┌─────────────────────────────────────────────────────────┐
  │  简单日常对话 → 快速路径 + 二级缓存 (精确 SHA-256 + 语义) │
  │                                                         │
  │  复杂编码任务 → LangGraph DAG 调度流水线:                 │
  │  [目标规划] → [任务拆解] → [并行执行] → [验证门] → [合成]  │
  │                                                         │
  │  多智能体架构:                                           │
  │  ├─ 隔离子代理 (独立沙箱、会话、上下文依赖链与预算)          │
  │  └─ 专家团队 (Coordinator + 确定性 SopMachine 状态机)     │
  │       pm → architect → coder(∥) → tester → verifier     │
  │          → 3-way audit(∥) → doc                         │
  │                                                         │
  │  分层基础设施:                                           │
  │  ├─ 记忆系统 (短期窗口 / 长期压缩 / 向量经验库)            │
  │  ├─ 代码库 RAG (AST 切块 / Numpy 向量库 / PageRank 拓扑图)│
  │  └─ 30+ 工具池 + 严格三级安全门控 + 崩溃幂等工具日志        │
  └─────────────────────────────────────────────────────────┘
```

---

## 📦 环境要求

| 依赖项 | 建议版本 | 说明 |
|---|---|---|
| **Python** | 3.10+ | 后端与核心 Agent 逻辑 |
| **Bun** | 最新 | 默认 OpenTUI 终端（一键安装脚本会自动拉取） |
| **Node.js** | 20+ | 仅在运行 Ink 终端回退或从源码调试桌面端时需要 |
| **API Key** | — | 任何兼容 OpenAI 格式的大模型提供商凭证 |

---

## 📋 版本演进

| 版本 | 发布时间 | 主要更新亮点 |
|---|---|---|
| [v1.2.11](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.11) | 2026-08 | 推出 10 角色 7 阶段 SOP 专家团队；提升 CLI 稳定性与 Windows 编码兼容；stdio 吞吐升至 8MB |
| [v1.2.10](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.10) | 2026-08 | 推出 Electron 桌面客户端 (`rxycode gui`)，集成 Plan 模式、Goal 弹窗与 Composer `+` 菜单 |
| [v1.2.9](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.9) | 2026-08 | 隔离子代理（Phase C）：支持 `@agent` 语法分派、Task 工具及 OpenTUI 子代理层级树 |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | 基于 LangGraph 全面重构规划执行管线、分层记忆与代码 RAG |
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | 首个公开发布版本，基础工具链与 MCP 原生集成 |

完整更新历史请参阅 [CHANGELOG.md](CHANGELOG.md)。

## 🤝 参与贡献

欢迎查阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解代码规范与分支流程。提交 Issue 或 Pull Request 共同完善项目！

## 📄 开源许可证

本项目基于 [MIT](LICENSE) 开源协议发布与维护。
