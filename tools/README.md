# tools/ - 工具模块

## 这个文件夹负责什么

Agent 可调用的环境能力集合：文件、Shell、Git、搜索、下载、视觉、MCP、任务队列、技能等。

## 核心原理

所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `agent_tool.py` | agent tool - Run sub-tasks with a child AI agent. | agent tool - Run sub-tasks with a child AI agent. |
| `bash.py` | 定义 BashInput、run_bash 等对象。 | 定义 BashInput、run_bash 等对象。 |
| `change_directory.py` | 定义 ChangeDirectoryInput、change_directory 等对象。 | 定义 ChangeDirectoryInput、change_directory 等对象。 |
| `datetime_tool.py` | System datetime tool. | System datetime tool. |
| `diagnostics.py` | diagnostics tool - Get LSP diagnostics for files. | diagnostics tool - Get LSP diagnostics for files. |
| `download_tool.py` | Download tool - Natural language skill and MCP download. | Download tool - Natural language skill and MCP download. |
| `edit.py` | 定义 EditInput、edit_file 等对象。 | 定义 EditInput、edit_file 等对象。 |
| `file_download.py` | File Download Tool - Download files from URLs to local filesystem. | File Download Tool - Download files from URLs to local filesystem. |
| `format_tool.py` | format tool - Auto-format code files. | format tool - Auto-format code files. |
| `git_tool.py` | 定义 GitInput、run_git 等对象。 | 定义 GitInput、run_git 等对象。 |
| `glob_tool.py` | 定义 GlobInput、glob_files 等对象。 | 定义 GlobInput、glob_files 等对象。 |
| `grep_tool.py` | 定义 GrepInput、grep_files 等对象。 | 定义 GrepInput、grep_files 等对象。 |
| `history_tool.py` | 定义 HistoryInput、search_history 等对象。 | 定义 HistoryInput、search_history 等对象。 |
| `installer.py` | Tool search and installation manager. | Tool search and installation manager. |
| `ls.py` | ls tool - List directory contents as a tree. | ls tool - List directory contents as a tree. |
| `mcp_manager.py` | MCP Manager - Add, remove, and manage MCP servers from CLI. | MCP Manager - Add, remove, and manage MCP servers from CLI. |
| `memory_tool.py` | 定义 MemoryInput、memory_operation 等对象。 | 定义 MemoryInput、memory_operation 等对象。 |
| `patch.py` | patch tool - Apply unified diff patches to files. | patch tool - Apply unified diff patches to files. |
| `question_tool.py` | 定义 Option、Question、QuestionInput、ask_questions 等对象。 | 定义 Option、Question、QuestionInput、ask_questions 等对象。 |
| `read.py` | 定义 ReadInput、read_file 等对象。 | 定义 ReadInput、read_file 等对象。 |
| `registry.py` | 定义 ToolRegistry 等对象。 | 定义 ToolRegistry 等对象。 |
| `skill_manager.py` | Skill Manager - Search, download, and manage skills from GitHub and other sources. | Skill Manager - Search, download, and manage skills from GitHub and other sources. |
| `skill_tool.py` | 定义 SkillInput、load_skill 等对象。 | 定义 SkillInput、load_skill 等对象。 |
| `task_tool.py` | 定义 TaskInput、manage_tasks 等对象。 | 定义 TaskInput、manage_tasks 等对象。 |
| `view.py` | view tool - View file contents with line numbers. | view tool - View file contents with line numbers. |
| `vision.py` | vision tool - Read/OCR images, capture screenshots, describe visuals. | vision tool - Read/OCR images, capture screenshots, describe visuals. |
| `webfetch.py` | fetch tool - Fetch content from URLs with format support. | fetch tool - Fetch content from URLs with format support. |
| `websearch.py` | Web search tool with retry and multi-engine fallback. | Web search tool with retry and multi-engine fallback. |
| `workflow_tool.py` | 定义 WorkflowInput、manage_workflow 等对象。 | 定义 WorkflowInput、manage_workflow 等对象。 |
| `write.py` | 定义 WriteInput、write_file 等对象。 | 定义 WriteInput、write_file 等对象。 |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 0 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# tools\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `agent_tool.py`

- 写了什么：agent tool - Run sub-tasks with a child AI agent.
- 功能是什么：agent tool - Run sub-tasks with a child AI agent.
- 核心原理：`StructuredTool` 同时提供同步兼容入口和原生 async coroutine；Agent 主链使用 async 路径，因此取消会直接传播给子 Agent，不创建后台线程或固定 300 秒 deadline。

关键对象/函数：

- 类 `AgentInput`
- 函数 `run_agent(prompt)`：无事件循环调用方的同步兼容入口。
- 协程 `run_agent_async(prompt)`：主链使用的可取消子 Agent 委派入口。

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.agent_tool import run_agent

result = run_agent(prompt=...)
```

异步调用方应使用 `await run_agent_async(prompt)`；不要在线程或已运行的事件循环中调用同步兼容入口。

### `bash.py`

- 写了什么：定义 BashInput、run_bash 等对象。
- 功能是什么：定义 BashInput、run_bash 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 33 行。

关键对象/函数：

- 类 `BashInput`
- 函数 `run_bash(command, description, workdir, timeout)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.bash import run_bash

result = run_bash(command=..., description=..., workdir=..., timeout=...)
```

### `change_directory.py`

- 写了什么：定义 ChangeDirectoryInput、change_directory 等对象。
- 功能是什么：定义 ChangeDirectoryInput、change_directory 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 29 行。

关键对象/函数：

- 类 `ChangeDirectoryInput`
- 函数 `change_directory(path)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.change_directory import change_directory

result = change_directory(path=...)
```

### `datetime_tool.py`

- 写了什么：System datetime tool.
- 功能是什么：System datetime tool.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 26 行。

关键对象/函数：

- 类 `DatetimeInput`
- 函数 `get_datetime(format)`：Get current system date and time.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.datetime_tool import get_datetime

result = get_datetime(format=...)
```

### `diagnostics.py`

- 写了什么：diagnostics tool - Get LSP diagnostics for files.
- 功能是什么：diagnostics tool - Get LSP diagnostics for files.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 102 行。

关键对象/函数：

- 类 `DiagnosticsInput`
- 函数 `run_diagnostics(filePath)`：Get LSP diagnostics for a file or all files.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.diagnostics import run_diagnostics

result = run_diagnostics(filePath=...)
```

### `download_tool.py`

- 写了什么：Download tool - Natural language skill and MCP download.
- 功能是什么：Download tool - Natural language skill and MCP download.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 61 行。

关键对象/函数：

- 类 `DownloadSkillInput`
- 类 `DownloadMCPInput`
- 函数 `download_skill(name)`：Download and install a skill by name from GitHub.
- 函数 `download_mcp(name, package)`：Download and configure an MCP server from npm.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.download_tool import download_skill

result = download_skill(name=...)
```

### `edit.py`

- 写了什么：定义 EditInput、edit_file 等对象。
- 功能是什么：定义 EditInput、edit_file 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 73 行。

关键对象/函数：

- 类 `EditInput`
- 函数 `edit_file(filePath, oldString, newString, replaceAll)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.edit import edit_file

result = edit_file(filePath=..., oldString=..., newString=..., replaceAll=...)
```

### `file_download.py`

- 写了什么：File Download Tool - Download files from URLs to local filesystem.
- 功能是什么：File Download Tool - Download files from URLs to local filesystem.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 148 行。

关键对象/函数：

- 类 `FileDownloadInput`：Input for file download tool.
- 函数 `download_file(url, save_path, filename)`：Download a file from URL to local filesystem.

`save_path` 为相对路径时，以当前 `session_id` 持久化的工作目录解析，不读取或
修改进程全局 cwd；未传时才落到 `~/.rxycode/output/`。成功结果中的
`Saved to:` 会在统一证据边界重新解析，只有文件真实存在才算成功，并记录
绝对路径、大小与 SHA-256，供 Validator 和最终 grounding 复验。

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.file_download import download_file

result = download_file(url=..., save_path=..., filename=...)
```

### `format_tool.py`

- 写了什么：format tool - Auto-format code files.
- 功能是什么：format tool - Auto-format code files.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 165 行。

关键对象/函数：

- 类 `FormatInput`
- 函数 `run_format(filePath, tool, checkOnly)`：Format a code file using the best available formatter.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.format_tool import run_format

result = run_format(filePath=..., tool=..., checkOnly=...)
```

### `git_tool.py`

- 写了什么：定义 GitInput、run_git 等对象。
- 功能是什么：定义 GitInput、run_git 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 153 行。

关键对象/函数：

- 类 `GitInput`
- 函数 `run_git(operation, path, args)`：Execute a structured Git operation.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.git_tool import run_git

result = run_git(operation=..., path=..., args=...)
```

### `glob_tool.py`

- 写了什么：定义 GlobInput、glob_files 等对象。
- 功能是什么：定义 GlobInput、glob_files 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 26 行。

关键对象/函数：

- 类 `GlobInput`
- 函数 `glob_files(pattern, path)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.glob_tool import glob_files

result = glob_files(pattern=..., path=...)
```

### `grep_tool.py`

- 写了什么：定义 GrepInput、grep_files 等对象。
- 功能是什么：定义 GrepInput、grep_files 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 64 行。

关键对象/函数：

- 类 `GrepInput`
- 函数 `grep_files(pattern, path, include)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.grep_tool import grep_files

result = grep_files(pattern=..., path=..., include=...)
```

### `history_tool.py`

- 写了什么：定义 HistoryInput、search_history 等对象。
- 功能是什么：定义 HistoryInput、search_history 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 94 行。

关键对象/函数：

- 类 `HistoryInput`
- 函数 `search_history(operation, query, limit)`

历史搜索只枚举全局记忆根（`memory/user`、`memory/projects/global`）和当前
`session_id` 的 `memory/sessions/<session_id>`；不会扫描其他 session，避免
并发会话间事实泄漏。

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.history_tool import search_history

result = search_history(operation=..., query=..., limit=...)
```

### `installer.py`

- 写了什么：Tool search and installation manager.
- 功能是什么：Tool search and installation manager.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 121 行。

关键对象/函数：

- 类 `ToolInstaller`：Manages tool search and installation.；常用方法：`is_package_installed`、`find_tool_package`、`install_package`、`search_and_install`、`get_install_suggestion`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.installer import ToolInstaller

# 示例：根据真实业务传入依赖或配置
obj = ToolInstaller(...)
# result = obj.is_package_installed(...)
```

### `ls.py`

- 写了什么：ls tool - List directory contents as a tree.
- 功能是什么：ls tool - List directory contents as a tree.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 80 行。

关键对象/函数：

- 类 `LsInput`
- 函数 `run_ls(path, ignore)`：List directory contents as a tree.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.ls import run_ls

result = run_ls(path=..., ignore=...)
```

### `mcp_manager.py`

- 写了什么：MCP Manager - Add, remove, and manage MCP servers from CLI.
- 功能是什么：MCP Manager - Add, remove, and manage MCP servers from CLI.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 141 行。

关键对象/函数：

- 函数 `get_mcp_config()`：Get current MCP configuration from config.yaml.
- 函数 `save_mcp_config(mcp_servers)`：Save MCP configuration to config.yaml.
- 函数 `add_mcp_server(name, command, args, env)`：Add an MCP server to the configuration.
- 函数 `remove_mcp_server(name)`：Remove an MCP server from the configuration.
- 函数 `list_mcp_servers()`：List all configured MCP servers.
- 函数 `install_mcp_from_npm(package_name, server_name)`：Install an MCP server from npm package.
- 函数 `install_mcp_from_pip(package_name, server_name)`：Install an MCP server from pip package.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.mcp_manager import get_mcp_config

result = get_mcp_config()
```

### `memory_tool.py`

- 写了什么：定义 MemoryInput、memory_operation 等对象。
- 功能是什么：定义 MemoryInput、memory_operation 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 147 行。

关键对象/函数：

- 类 `MemoryInput`
- 函数 `memory_operation(operation, query, scope, scope_id, limit)`：Memory tool supporting search, add, list, and remove operations.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.memory_tool import memory_operation

result = memory_operation(operation=..., query=..., scope=..., scope_id=..., limit=...)
```

### `patch.py`

- 写了什么：patch tool - Apply unified diff patches to files.
- 功能是什么：patch tool - Apply unified diff patches to files.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 122 行。

关键对象/函数：

- 类 `PatchInput`
- 函数 `run_patch(filePath, diff)`：Apply a unified diff patch to a file.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.patch import run_patch

result = run_patch(filePath=..., diff=...)
```

### `question_tool.py`

- 写了什么：定义 Option、Question、QuestionInput、ask_questions 等对象。
- 功能是什么：定义 Option、Question、QuestionInput、ask_questions 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 71 行。

关键对象/函数：

- 类 `Option`
- 类 `Question`
- 类 `QuestionInput`
- 函数 `ask_questions(questions)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.question_tool import ask_questions

result = ask_questions(questions=...)
```

### `read.py`

- 写了什么：定义 ReadInput、read_file 等对象。
- 功能是什么：定义 ReadInput、read_file 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 43 行。

关键对象/函数：

- 类 `ReadInput`
- 函数 `read_file(filePath, offset, limit)`

默认每次读取 800 行，并通过 `offset` 分页。800 是默认窗口而非 schema
强制硬上界；显式传入正数 `limit` 可以请求不同页大小。

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.read import read_file

result = read_file(filePath=..., offset=..., limit=...)
```

### `registry.py`

- 写了什么：定义 ToolRegistry 等对象。
- 功能是什么：定义 ToolRegistry 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 63 行。

关键对象/函数：

- 类 `ToolRegistry`；常用方法：`register`、`register_alias`、`get`、`get_all`、`get_names`、`get_descriptions`、`remove`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

# 示例：根据真实业务传入依赖或配置
obj = ToolRegistry(...)
# result = obj.register(...)
```

### `skill_manager.py`

- 写了什么：Skill Manager - Search, download, and manage skills from GitHub and other sources.
- 功能是什么：Skill Manager - Search, download, and manage skills from GitHub and other sources.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 273 行。

关键对象/函数：

- 函数 `get_skills_dir()`：Get the user skills directory.
- 函数 `list_installed_skills()`：List all installed skills.
- 函数 `search_github_skills(query)`：Search GitHub for skills matching the query.
- 函数 `download_skill_from_github(repo, path, skill_name)`：Download a skill from a GitHub repository.
- 函数 `install_skill_from_url(url, skill_name)`：Install a skill from a direct URL (raw file or zip).
- 函数 `remove_skill(skill_name)`：Remove an installed skill.
- 函数 `find_and_download_skill(query)`：Search for a skill and download the best match.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.skill_manager import get_skills_dir

result = get_skills_dir()
```

### `skill_tool.py`

- 写了什么：定义 SkillInput、load_skill 等对象。
- 功能是什么：定义 SkillInput、load_skill 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 41 行。

关键对象/函数：

- 类 `SkillInput`
- 函数 `load_skill(name)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.skill_tool import load_skill

result = load_skill(name=...)
```

### `task_tool.py`

- 写了什么：定义 TaskInput、manage_tasks 等对象。
- 功能是什么：定义 TaskInput、manage_tasks 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 101 行。

关键对象/函数：

- 类 `TaskInput`
- 函数 `manage_tasks(operation, id, summary, status, event_summary)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.task_tool import manage_tasks

result = manage_tasks(operation=..., id=..., summary=..., status=..., event_summary=...)
```

### `view.py`

- 写了什么：view tool - View file contents with line numbers.
- 功能是什么：view tool - View file contents with line numbers.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 53 行。

关键对象/函数：

- 类 `ViewInput`
- 函数 `run_view(filePath, offset, limit)`：View file contents with line numbers.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.view import run_view

result = run_view(filePath=..., offset=..., limit=...)
```

### `vision.py`

- 写了什么：vision tool - Read/OCR images, capture screenshots, describe visuals.
- 功能是什么：vision tool - Read/OCR images, capture screenshots, describe visuals.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 220 行。

关键对象/函数：

- 类 `VisionInput`
- 函数 `run_vision(operation, filePath, prompt)`：Run vision operations on images.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.vision import run_vision

result = run_vision(operation=..., filePath=..., prompt=...)
```

### `webfetch.py`

- 写了什么：fetch tool - Fetch content from URLs with format support.
- 功能是什么：fetch tool - Fetch content from URLs with format support.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 68 行。

关键对象/函数：

- 类 `FetchInput`
- 函数 `fetch_url(url, format, timeout)`：Fetch content from a URL with format conversion.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.webfetch import fetch_url

result = fetch_url(url=..., format=..., timeout=...)
```

### `websearch.py`

- 写了什么：Web search tool with retry and multi-engine fallback.
- 功能是什么：Web search tool with retry and multi-engine fallback.
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 156 行。

关键对象/函数：

- 类 `WebSearchInput`
- 函数 `search_web(query, numResults)`：Search the web with retry and multi-engine fallback.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.websearch import search_web

result = search_web(query=..., numResults=...)
```

### `workflow_tool.py`

- 写了什么：定义 WorkflowInput、manage_workflow 等对象。
- 功能是什么：定义 WorkflowInput、manage_workflow 等对象。
- 核心原理：后台脚本保留真实进程句柄，`cancel` 会终止并回收整棵进程树；`timeout_seconds` 是显式可选 deadline，默认 `0` 不固定停止长任务。异步 `wait` 可直接取消，不遗留等待线程。

关键对象/函数：

- 类 `WorkflowInput`
- 函数 `manage_workflow(operation, name, script, args, run_id, timeout_seconds)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.workflow_tool import manage_workflow

result = manage_workflow(
    operation=..., name=..., script=..., args=..., run_id=..., timeout_seconds=0
)
```

### `write.py`

- 写了什么：定义 WriteInput、write_file 等对象。
- 功能是什么：定义 WriteInput、write_file 等对象。
- 核心原理：所有工具统一为 LangChain StructuredTool：Pydantic 参数 schema + 描述 + 实现函数，便于 LLM 自动选择和调用。
- 代码规模：约 59 行。

关键对象/函数：

- 类 `WriteInput`
- 函数 `write_file(filePath, content)`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tools.write import write_file

result = write_file(filePath=..., content=...)
```

## 典型协作关系

被 Agent 注册并绑定给 LLM，部分工具依赖 config、utils、memory、mcp、lsp。
