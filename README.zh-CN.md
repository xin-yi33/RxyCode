<div align="center">

# RxyCode

**规划-执行型 AI 编程助手，带验证层与安全工具编排**

[![Version](https://img.shields.io/badge/version-1.2.2-blue.svg)](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20+-339933.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-2477%20passed-brightgreen.svg)](#测试)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

**[English](README.md)** | **[中文](README.zh-CN.md)**

</div>

<div align="center">
  <img src="docs/images/screenshot.png" alt="RxyCode 界面截图" width="800">
</div>

---

RxyCode 是一个基于 LangGraph 的通用 AI Agent，采用分层"规划-执行"架构。
它将复杂任务拆解为子任务，通过安全的工具编排器执行，验证结果后综合最终答案——
全部过程实时流式输出到 OpenTUI 终端界面（可用 Ink 回退）。

### 为什么选择 RxyCode？

- **防幻觉** — 专用验证器在报告成功前，会检查工具结果是否真正满足原始目标
- **规划与执行** — 分层任务拆解 + 依赖感知的并行执行，而非线性 ReAct 循环
- **默认安全** — 风险分级、写入白名单、审批对话框、完整审计日志
- **极速响应** — 三层缓存（精确哈希 + 语义相似 + Provider KV）、50ms token 批处理、简单查询快速路径
- **精美界面** — 默认 OpenTUI/React/TypeScript 前端：流式输出、ScrollBox 聊天、原生输入框、OpenCode 风格面板；一键安装会在缺少 Bun 时自动安装；Ink 可通过 `RXYCODE_TUI=ink` 回退
- **30+ 内置工具** — 文件操作、Shell、网页搜索/抓取、Git、RAG、MCP、LSP 等

## 快速开始

### 前置条件

| 要求 | 版本 | 说明 |
|------|------|------|
| Python | 3.10+ | 后端运行时 |
| Bun | 最新 | 一键安装在缺失时自动安装（OpenTUI） |
| Node.js | 20+ | 可选 Ink 回退（`RXYCODE_TUI=ink`） |
| OpenAI 兼容 API 密钥 | — | 任意提供商（OpenAI、DeepSeek 等） |

### 方式一：一键安装（推荐）

**Windows PowerShell：**
```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.2/install.ps1 | iex"
rxycode
```

**macOS / Linux：**
```bash
curl -fsSL https://raw.githubusercontent.com/xin-yi33/RxyCode/v1.2.2/install.sh | sh
rxycode
```

安装脚本会自动引导安装 `uv`（如果需要），创建隔离的工具环境，并安装 `v1.2.2` 版本。
无需手动 clone 仓库。上一版 `v1.1.0` 仍可通过对应 tag 安装。

### 方式二：一次性运行

```bash
uvx --from "git+https://github.com/xin-yi33/RxyCode.git@v1.2.2" rxycode
```

### 方式三：永久安装

```bash
uv tool install --force "git+https://github.com/xin-yi33/RxyCode.git@v1.2.2"
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
cp .env.example .env   # 设置 OPENAI_API_KEY 和 RXYCODE_API_TOKEN
docker compose up -d api       # API 服务器（仅本地回环）
docker compose run --rm tui    # 交互式 TUI（需要 TTY）
```

### 首次启动

1. 运行 `rxycode` — 即使没有配置模型，TUI 也会打开
2. 若本地尚未配置模型，TUI 会检测到空列表，在欢迎页显示提示并自动打开 `/addmodel` 向导（凭据输入有掩码保护）
3. 若已配置至少一个模型，则不显示额外提示，也不会自动弹出向导
4. 开始使用！直接用自然语言输入你的需求

## 架构

```
用户输入
    │
    ▼
AgentV2 (core/agent_v2.py)
    │
    ├── 简单查询  →  快速路径（单次 LLM 调用 + 缓存检查）
    ├── 多任务    →  子 Agent 并行
    ├── 编排      →  规划 + 构建
    └── 复杂任务  →  LangGraph 管道：
                           │
                目标规划器 → 拆解器 → 执行器 → 工具编排器
                                        → 证据 → 验证器
                                                → 综合器
```

### 流式管道

```
后端 (Python)                              前端 (TypeScript/OpenTUI)
─────────────────                         ──────────────────────────────
_raw_stream()                              chatApi.ts / App.tsx
  │                                          │
  ├── cache_control 注入                     fetch /chat/stream (SSE)
  │                                          │
  ├── OpenAI 异步流                          解析 SSE 事件：
  │   ├── reasoning_content → 推理            ├── progress/reasoning/plan/step
  │   ├── content token → 流式 token          ├── token → 实时助手流式输出
  │   └── tool_calls delta                    ├── tool_call/tool_result
  │                                           ├── approval → ApprovalDialog
  └── StreamTUI → asyncio.Queue → SSE         └── final/done → 终态
```

## 工作模式

| 模式 | 命令 | 行为 |
|------|------|------|
| 构建 | `/build` | 完整管道：规划 → 拆解 → 执行 → 验证 → 综合 |
| 规划 | `/plan` | 只读分析和规划，不修改文件 |
| 编排 | `/compose` | 规划 + 构建（简化管道） |

## 目录结构

| 目录 | 职责 |
|------|------|
| `core/` | AgentV2、LangGraph 图、状态、提示词、UsageTrackingLLM |
| `planning/` | 目标提炼器、任务拆解器 |
| `execution/` | 执行器、工具编排器 |
| `validation/` | 验证器、重规划器 |
| `synthesis/` | 输出综合器 |
| `frontend/opentui-app/` | **默认** OpenTUI/React 终端 UI（Bun + React 19） |
| `frontend/` | Ink/React 回退 UI（`RXYCODE_TUI=ink`） |
| `tools/` | 30+ 内置工具（read, write, edit, bash, grep, web, git 等） |
| `memory/` | 分层记忆（短期、长期、用户、搜索） |
| `cache/` | 三层缓存（精确 + 语义 + Provider KV） |
| `config/` | 配置管理（`~/.rxycode/config.yaml`） |
| `rag/` | 代码库向量搜索（分块、嵌入、余弦） |
| `scheduler/` | 定时任务（类 cron） |
| `recovery/` | 错误恢复与重试 |
| `mcp/` | MCP 服务器集成 |
| `lsp/` | LSP 集成（实验性） |
| `safety/` | 风险分级、审批、写入白名单、审计 |
| `evals/` | 评估框架（成功率、LLM-as-judge） |
| `tests/` | Python 测试套件（2319 个确定性测试） |

## 测试

### 前端（TypeScript）
```bash
cd frontend && npm test    # 28 文件 / 158 测试
```

### 后端（Python）
```bash
python -m pytest tests -m "not live and not pty and not serial" -n 2 --dist loadscope -q
python -m pytest tests -m "serial and not live and not pty" -n 0 -q
# 2319 个确定性测试通过
```

## 配置

配置文件位于 `~/.rxycode/config.yaml`：

```yaml
cache:
  enabled: true
  prompt_prefix_cache: true   # 开启 Provider 侧 KV 缓存
  ttl: 3600

models:
  - name: deepseek-v4-flash
    provider: openai
    api_key: <your-key>        # 存储在仓库外，不会被提交
    base_url: https://api.deepseek.com
```

在 TUI 中使用 `/addmodel` 打开引导式设置向导。

## 常用命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/addmodel` | 添加新模型 |
| `/models` | 列出所有模型 |
| `/model <name>` | 切换模型 |
| `/build` `/plan` `/compose` | 切换工作模式 |
| `/clear` | 清除对话上下文 |
| `/memory add/list/search` | 记忆管理 |
| `/queue add/run` | 任务队列 |
| `/cache` | 查看缓存统计 |
| `/language` | 切换语言 |
| `/thinking` | 切换思考面板 |

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Tab` | 切换工作模式 |
| `Ctrl+S` | 发送消息 |
| `Ctrl+X` | 取消当前操作 |
| `Ctrl+?` | 显示帮助 |
| `Ctrl+E` | 外部编辑器 |
| `Ctrl+C` | 退出程序 |

## 版本历史

| 版本 | 日期 | 要点 |
|------|------|------|
| [v0.3.3](https://github.com/xin-yi33/RxyCode/releases/tag/v0.3.3) | 2025-12 | 初版：ReAct + 防幻觉 + MCP 集成 |
| [v1.0.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.0.0) | 2026-06 | LangGraph 重写：规划-执行、24+ 工具、分层记忆 |
| [v1.1.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.1.0) | 2026-07 | Ink TUI、SSE 流式、Docker、CI/CD、一键安装 |
| [v1.2.0](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.0) | 2026-07 | 前端重构：默认 OpenTUI（Ink 回退）、设置面板对齐、Ctrl+C 防误退、Plan 提示、autoCompact |
| [v1.2.1](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.1) | 2026-07 | 打包修复：安装包内包含 OpenTUI 源码 |
| [v1.2.2](https://github.com/xin-yi33/RxyCode/releases/tag/v1.2.2) | 2026-07 | 自动安装 Bun 与 OpenTUI 依赖，默认界面无需手装 Bun |

完整变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## License

[MIT](LICENSE) © RxyCode contributors
