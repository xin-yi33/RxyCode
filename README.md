<p align="center">
  <h1 align="center">RxyCode</h1>
  <p align="center"><strong>AI-Powered Coding Agent with Verification Layer</strong></p>
  <p align="center">
    <em>基于 ReAct + 反幻觉验证层 的智能编程助手</em>
  </p>
</p>

<p align="center">
  <a href="#english">English</a> | <a href="#中文">中文</a>
</p>

---

<a name="english"></a>

## 🇬🇧 English

### Overview

RxyCode is a Python-based AI coding agent that uses a **ReAct (Reasoning + Acting) architecture** enhanced with a custom **Verification Layer** to prevent hallucinated success reports. It features a modular tool system, environment-aware path resolution, and MCP (Model Context Protocol) integration.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    RxyCode Agent                         │
├─────────────┬─────────────┬──────────────┬──────────────┤
│  Session    │  Execution  │ Verification │ Environment  │
│  Manager    │  Engine     │ Layer        │ Detector     │
├─────────────┼─────────────┼──────────────┼──────────────┤
│ Context     │ Timeout/    │ Claim        │ OS/Shell/    │
│ Isolation   │ Retry/      │ Extraction   │ Path         │
│ & History   │ Degradation │ & Correction │ Resolution   │
│ Compression │             │              │              │
├─────────────┴─────────────┴──────────────┴──────────────┤
│                    Tool Registry                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  Write   │  │   Read   │  │   Bash   │  ...          │
│  │  Tool    │  │   Tool   │  │   Tool   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
├─────────────────────────────────────────────────────────┤
│              Shell Abstraction Layer                     │
│         (PowerShell / CMD / Bash / Zsh)                  │
└─────────────────────────────────────────────────────────┘
         ↕
┌─────────────────────────────────────────────────────────┐
│                  MCP Integration Layer                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │   Shell MCP  │ │  Verify MCP  │ │ Task Progress│    │
│  └──────────────┘ └──────────────┘ └──────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Core Mechanism: ReAct + Verification

RxyCode follows the **ReAct pattern** (Reason → Act → Observe → Repeat) but adds a critical **Verification Layer** that independently checks every success claim before returning to the user.

#### ReAct Loop

```
User: "Create hello.py with a hello world function"
  ↓
[Reason] Agent thinks: I need to use the write tool to create this file
  ↓
[Act] Agent calls: write(path="hello.py", content="def hello():...")
  ↓
[Observe] Tool returns: "File written: hello.py (45 bytes)"
  ↓
[Verify] Verification Layer checks: Does hello.py actually exist? → YES ✓
  ↓
[Respond] "Created hello.py with a hello world function [Verified]"
```

#### Verification Layer (Anti-Hallucination)

The Verification Layer solves the critical problem where agents claim success without actually completing tasks:

| Component | Function |
|-----------|----------|
| **ClaimExtractor** | Parses agent responses to find success claims ("file created", "test passed") |
| **Verifier** | Independently checks each claim using actual tool results |
| **ReportCorrector** | Rewrites false claims with accurate failure descriptions |

Example:
```
Agent says:    "I have successfully created hello.py and run the tests"
Verification:  ✓ hello.py exists (verified via filesystem)
Verification:  ✗ No test output found (no pytest markers in evidence)
Corrected:     "hello.py created. ⚠️ Tests were not actually run."
```

### Key Features

- **ReAct Architecture**: Structured reasoning → action → observation loop
- **Anti-Hallucination Verification**: Independent claim verification before user delivery
- **Tool Timeout/Retry/Degradation**: 15s write / 5s read / 60s bash with automatic retry and graceful degradation
- **Environment Awareness**: Auto-detects OS, shell, paths without hardcoding
- **Context Isolation**: Per-request context to prevent cross-task contamination
- **History Compression**: Automatic summarization to stay within token limits
- **MCP Integration**: Extensible via Model Context Protocol servers

### Project Structure

```
RxyCode/
├── rxycode_backend/          # Core agent backend
│   ├── core/                 # Cross-cutting concerns
│   │   ├── environment.py    # OS/shell/path detection
│   │   ├── execution.py      # Tool execution engine (timeout/retry/degrade)
│   │   ├── session.py        # Context management & history compression
│   │   ├── shell.py          # Shell abstraction (PS/CMD/Bash)
│   │   └── verification.py   # Anti-hallucination verification layer
│   ├── tools/                # Tool implementations
│   │   ├── base.py           # Tool protocol & registry
│   │   ├── bash_tool.py      # Shell command execution
│   │   ├── read_tool.py      # File reading
│   │   └── write_tool.py     # File writing
│   └── tests/                # Test suite
│       ├── test_p01_hallucination.py
│       ├── test_p02a_timeout.py
│       ├── test_p02b_shell_syntax.py
│       ├── test_p03_path_error.py
│       └── test_p11_context_leak.py
├── rxycode-mcp/              # MCP server integrations
│   ├── codebase_explorer_mcp.py
│   ├── rxycode_shell_mcp.py
│   ├── rxycode_verify_mcp.py
│   ├── task_progress_mcp.py
│   └── config/mcp_config.json
├── test_parse_tool_call.py   # Tool call parsing tests
├── test_rxycode.py           # Integration tests
└── README.md
```

### Quick Start

#### Prerequisites

- Python 3.13+
- API key for an LLM provider (DeepSeek, OpenAI, etc.)

#### Installation

```bash
# Clone the repository
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode

# Install dependencies
pip install -r requirements.txt
```

#### Configuration (Windows)

```powershell
# PowerShell
$env:RXYCODE_API_KEY="your-api-key-here"

# CMD
set RXYCODE_API_KEY=your-api-key-here
```

Or create config file at `~/.rxycode/config.yaml`

#### Running

```bash
# Start API server
python -m rxycode_backend --api --api-port 18765

# Test with curl
curl -X POST http://127.0.0.1:18765/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, introduce yourself"}'
```

#### Running Tests

```bash
# Run all tests
python -m pytest rxycode_backend/tests/ -v

# Run specific test
python test_parse_tool_call.py
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Send a message to the agent |
| `/command` | POST | Execute a slash command |
| `/status` | GET | Check server health |

### Tool System

Tools are registered via `ToolRegistry` and executed through `ExecutionEngine` with automatic timeout/retry/degradation:

| Tool | Timeout | Description |
|------|---------|-------------|
| `write` | 15s | Create/overwrite files with path resolution |
| `read` | 5s | Read file contents with encoding detection |
| `bash` | 60s | Execute shell commands via abstraction layer |

### License

MIT

---

<a name="中文"></a>

## 🇨🇳 中文

### 概述

RxyCode 是一个基于 Python 的 AI 编程助手，采用 **ReAct（推理+行动）架构**，并增强了自定义的**验证层**来防止幻觉性成功报告。具有模块化工具系统、环境感知路径解析和 MCP（模型上下文协议）集成。

### 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    RxyCode 智能体                         │
├─────────────┬─────────────┬──────────────┬──────────────┤
│  会话管理器  │  执行引擎    │  验证层       │  环境探测器   │
├─────────────┼─────────────┼──────────────┼──────────────┤
│ 上下文隔离   │ 超时/重试/   │ 声明提取      │ OS/Shell/    │
│ 历史压缩     │ 降级机制     │ 独立验证      │ 路径解析     │
│             │             │ 修正报告      │              │
├─────────────┴─────────────┴──────────────┴──────────────┤
│                    工具注册表                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │  Write   │  │   Read   │  │   Bash   │  ...          │
│  │  写入工具 │  │  读取工具 │  │  命令工具 │              │
│  └──────────┘  └──────────┘  └──────────┘              │
├─────────────────────────────────────────────────────────┤
│              Shell 抽象层                                │
│         (PowerShell / CMD / Bash / Zsh)                  │
└─────────────────────────────────────────────────────────┘
         ↕
┌─────────────────────────────────────────────────────────┐
│                  MCP 集成层                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │   Shell MCP  │ │  Verify MCP  │ │ Task Progress│    │
│  └──────────────┘ └──────────────┘ └──────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 核心机制：ReAct + 验证层

RxyCode 遵循 **ReAct 模式**（推理 → 行动 → 观察 → 重复），但增加了关键的**验证层**，在返回给用户之前独立检查每一个成功声明。

#### ReAct 循环

```
用户: "创建一个 hello.py，包含 hello world 函数"
  ↓
[推理] Agent 思考: 需要使用 write 工具创建文件
  ↓
[行动] Agent 调用: write(path="hello.py", content="def hello():...")
  ↓
[观察] 工具返回: "文件已写入: hello.py (45 字节)"
  ↓
[验证] 验证层检查: hello.py 是否真的存在？ → 是 ✓
  ↓
[响应] "已创建 hello.py [验证通过]"
```

#### 验证层（反幻觉机制）

验证层解决了 Agent 虚假报告成功的关键问题：

| 组件 | 功能 |
|------|------|
| **ClaimExtractor（声明提取器）** | 解析 Agent 回复，找到成功声明（"文件已创建"、"测试通过"） |
| **Verifier（验证器）** | 使用实际工具结果独立验证每个声明 |
| **ReportCorrector（报告修正器）** | 用准确的失败描述重写虚假声明 |

示例：
```
Agent 说:     "我已成功创建 hello.py 并运行了测试"
验证结果:     ✓ hello.py 存在（通过文件系统验证）
验证结果:     ✗ 未找到测试输出（证据中无 pytest 特征）
修正后:       "hello.py 已创建。⚠️ 测试未实际运行。"
```

### 核心特性

- **ReAct 架构**：结构化的 推理→行动→观察 循环
- **反幻觉验证**：在交付给用户之前独立验证声明
- **工具超时/重试/降级**：write 15s / read 5s / bash 60s，自动重试并优雅降级
- **环境感知**：自动检测 OS、Shell、路径，无需硬编码
- **上下文隔离**：按请求隔离上下文，防止跨任务污染
- **历史压缩**：自动摘要以保持在 token 限制内
- **MCP 集成**：通过模型上下文协议服务器可扩展

### 项目结构

```
RxyCode/
├── rxycode_backend/          # 核心 Agent 后端
│   ├── core/                 # 横切关注点
│   │   ├── environment.py    # OS/Shell/路径检测
│   │   ├── execution.py      # 工具执行引擎（超时/重试/降级）
│   │   ├── session.py        # 上下文管理与历史压缩
│   │   ├── shell.py          # Shell 抽象层（PS/CMD/Bash）
│   │   └── verification.py   # 反幻觉验证层
│   ├── tools/                # 工具实现
│   │   ├── base.py           # 工具协议与注册表
│   │   ├── bash_tool.py      # Shell 命令执行
│   │   ├── read_tool.py      # 文件读取
│   │   └── write_tool.py     # 文件写入
│   └── tests/                # 测试套件
│       ├── test_p01_hallucination.py
│       ├── test_p02a_timeout.py
│       ├── test_p02b_shell_syntax.py
│       ├── test_p03_path_error.py
│       └── test_p11_context_leak.py
├── rxycode-mcp/              # MCP 服务器集成
│   ├── codebase_explorer_mcp.py
│   ├── rxycode_shell_mcp.py
│   ├── rxycode_verify_mcp.py
│   ├── task_progress_mcp.py
│   └── config/mcp_config.json
├── test_parse_tool_call.py   # 工具调用解析测试
├── test_rxycode.py           # 集成测试
└── README.md
```

### 快速上手

#### 前置要求

- Python 3.13+
- LLM 提供商的 API Key（DeepSeek、OpenAI 等）

#### 安装

```bash
# 克隆仓库
git clone https://github.com/xin-yi33/RxyCode.git
cd RxyCode

# 安装依赖
pip install -r requirements.txt
```

#### 配置 (Windows)

```powershell
# PowerShell
$env:RXYCODE_API_KEY="your-api-key-here"

# CMD
set RXYCODE_API_KEY=your-api-key-here
```

或在 `~/.rxycode/config.yaml` 中创建配置文件

#### 运行

```bash
# 启动 API 服务器
python -m rxycode_backend --api --api-port 18765

# 使用 curl 测试
curl -X POST http://127.0.0.1:18765/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好，请介绍一下你自己"}'
```

#### 运行测试

```bash
# 运行所有测试
python -m pytest rxycode_backend/tests/ -v

# 运行特定测试
python test_parse_tool_call.py
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat` | POST | 向 Agent 发送消息 |
| `/command` | POST | 执行斜杠命令 |
| `/status` | GET | 检查服务器健康状态 |

### 工具系统

工具通过 `ToolRegistry` 注册，通过 `ExecutionEngine` 执行，自动处理超时/重试/降级：

| 工具 | 超时 | 说明 |
|------|------|------|
| `write` | 15s | 创建/覆写文件，支持路径解析 |
| `read` | 5s | 读取文件内容，支持编码检测 |
| `bash` | 60s | 通过抽象层执行 Shell 命令 |

### 许可证

MIT

---

> **该项目为测试版，欢迎大家踊跃提问。**
>
> *This project is in beta. Questions and feedback are welcome!*
