# RxyCode MCP 服务器套件

> 基于 RxyCode v0.3.2 用户研究报告构建的 4 个 MCP 服务器，系统性修复 P0-P2 级问题。

## 问题修复总览

| 用户报告问题 | 优先级 | MCP 服务器 | 核心工具 |
|------------|--------|-----------|---------|
| 幻觉性成功 — Agent 谎报任务完成 | P0 | `rxycode-verify` | `verify_file_created`, `verify_test_passed` |
| 工具执行不可靠 — 超时/语法混淆 | P0 | `rxycode-shell` | `write_file_safely`, `execute_shell`, `translate_command` |
| 路径错误 — 用进程身份推断路径 | P0 | `rxycode-shell` | `detect_environment`, `resolve_user_path` |
| 项目结构幻觉 — 虚构不存在的目录 | P1 | `codebase-explorer` | `scan_project_tree`, `verify_path_exists` |
| 错误信息不透明 — 工具调用显示 unknown | P2 | `task-progress` | `log_tool_call`, `get_all_tool_calls` |
| 缺乏进度反馈 — 长时间无指示 | P2 | `task-progress` | `start_task`, `update_progress`, `get_task_status` |

## 架构

```
RxyCode Agent (MCP Client)
    │
    ├── rxycode-verify (验证层)     ← 拦截幻觉性成功 [P0-1]
    │     所有成功声明必须经此验证
    │
    ├── rxycode-shell (执行层)      ← 可靠执行 + 环境感知 [P0-2, P0-3]
    │     超时/重试/降级 + Shell 抽象
    │
    ├── codebase-explorer (事实锚定) ← 消除结构幻觉 [P1-2]
    │     先探测后描述，绝不推测
    │
    └── task-progress (可观测层)    ← 透明执行 [P2-2, P2-3]
          结构化事件流 + 进度反馈
```

## 安装

```bash
# 1. 创建虚拟环境（推荐）
python -m venv .venv

# 2. 激活环境
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

## 运行单个服务器

每个 MCP 服务器可独立运行（stdio 传输）：

```bash
# 验证层
python rxycode_verify_mcp.py

# 执行层
python rxycode_shell_mcp.py

# 代码库探测
python codebase_explorer_mcp.py

# 任务进度追踪
python task_progress_mcp.py
```

## RxyCode 集成配置

在 RxyCode 的 MCP 配置文件中添加以下内容（参考 `config/mcp_config.json`）：

```json
{
  "mcpServers": {
    "rxycode-verify": {
      "command": "python",
      "args": ["rxycode_verify_mcp.py"],
      "cwd": "/path/to/rxycode-mcp"
    },
    "rxycode-shell": {
      "command": "python",
      "args": ["rxycode_shell_mcp.py"],
      "cwd": "/path/to/rxycode-mcp"
    },
    "codebase-explorer": {
      "command": "python",
      "args": ["codebase_explorer_mcp.py"],
      "cwd": "/path/to/rxycode-mcp"
    },
    "task-progress": {
      "command": "python",
      "args": ["task_progress_mcp.py"],
      "cwd": "/path/to/rxycode-mcp"
    }
  }
}
```

## 验证策略（关键）

配置文件中的 `verificationPolicy` 定义了强制验证规则：

| Agent 声称 | 必须调用的验证工具 | 验证失败时 |
|-----------|------------------|-----------|
| 「已创建文件 X」 | `verify_file_created` | 修正为「文件创建失败」 |
| 「测试通过」 | `verify_test_passed` | 修正为「测试未通过」 |
| 「命令执行成功」 | `verify_command_executed` | 修正为「命令执行失败」 |
| 描述项目结构 | `fact_check_paths` | 禁止描述不存在的路径 |

## 工具清单（27 个工具）

### rxycode-verify（8 个工具）
- `verify_file_exists(path)` — 验证文件存在性
- `verify_file_content(path, expected_patterns)` — 验证文件内容
- `verify_file_created(path, expected_patterns)` — 组合验证（存在+内容）
- `verify_command_executed(command, timeout)` — 实际重新执行验证
- `verify_test_passed(test_command, timeout)` — 实际运行测试验证
- `fact_check_paths(paths)` — 批量路径核查
- `compute_file_hash(path)` — 计算文件哈希
- `list_directory_real(path)` — 列出真实目录内容

### rxycode-shell（6 个工具）
- `detect_environment()` — 探测真实环境（OS/用户/路径/Shell）
- `resolve_user_path(path_type)` — 解析用户特殊目录路径
- `execute_shell(command, timeout, max_retries)` — 可靠命令执行
- `translate_command(command, from_shell, to_shell)` — Shell 语法翻译
- `write_file_safely(path, content, timeout)` — 安全写入（15s 超时）
- `read_file_safely(path, timeout)` — 安全读取（5s 超时）

### codebase-explorer（6 个工具）
- `scan_project_tree(root, max_depth)` — 扫描真实文件树
- `detect_project_type(root)` — 检测项目类型
- `list_real_files(pattern, root)` — 列出匹配的真实文件
- `verify_path_exists(path)` — 验证路径存在性
- `search_codebase(query, root)` — 搜索真实文件内容
- `get_file_summary(path)` — 获取文件摘要

### task-progress（7 个工具）
- `start_task(description, steps)` — 注册任务
- `update_progress(task_id, step_index, status)` — 更新进度
- `log_tool_call(task_id, tool_name, input, output)` — 记录工具调用
- `get_task_status(task_id)` — 查询任务状态
- `get_execution_log(task_id)` — 获取执行日志
- `get_all_tool_calls(task_id)` — 获取工具调用汇总
- `list_active_tasks()` — 列出活跃任务

## 运行测试

```bash
python tests/test_mcp_servers.py
```

预期输出：49/49 测试通过。

## 使用示例

### 场景：创建计算器模块（原 P0-1 失败场景）

**修复前**（Agent 谎报成功）：
```
用户: 创建 calculator.py 和 test_calculator.py
Agent: 已完成！calculator.py 包含加减乘除，测试全部通过。
实际: 文件不存在，测试未运行。
```

**修复后**（使用 MCP 验证管道）：
```
1. Agent 调用 write_file_safely("calculator.py", content)
   → {success: true, content_verified: true}

2. Agent 调用 verify_file_created("calculator.py", ["def add", "def subtract"])
   → {verified: true, evidence: "文件存在且包含全部期望模式"}

3. Agent 调用 verify_test_passed("pytest test_calculator.py")
   → {verified: true, evidence: "2 passed"}

4. Agent 向用户报告：calculator.py 已创建并验证，2 项测试通过。
```

如果步骤 2 验证失败：
```
verify_file_created → {verified: false, correction: "文件不存在，请勿声称已创建"}
Agent 修正回复：文件创建失败，正在重试...
```

### 场景：路径解析（原 P0-3 失败场景）

**修复前**：Agent 推断路径 `C:\Users\RxyCode\Desktop`（进程身份）

**修复后**：
```
detect_environment() → {real_username: "Administrator", desktop: "C:\Users\Administrator\Desktop"}
resolve_user_path("desktop") → {resolved_path: "C:\Users\Administrator\Desktop"}
```

### 场景：项目结构探索（原 P1-2 幻觉场景）

**修复前**：Agent 虚构 Minecraft-Unity 目录

**修复后**：
```
scan_project_tree(".") → {tree: [真实文件列表]}
verify_path_exists("Minecraft-Unity") → {exists: false, warning: "此路径不存在"}
Agent 只能描述真实存在的文件。
```

## 文件结构

```
rxycode-mcp/
├── rxycode_verify_mcp.py       # 验证层 MCP (8 tools)
├── rxycode_shell_mcp.py        # 执行层 MCP (6 tools)
├── codebase_explorer_mcp.py    # 代码库探测 MCP (6 tools)
├── task_progress_mcp.py        # 任务进度 MCP (7 tools)
├── requirements.txt
├── README.md
├── config/
│   └── mcp_config.json         # MCP 客户端配置
└── tests/
    └── test_mcp_servers.py     # 测试套件 (49 tests)
```
