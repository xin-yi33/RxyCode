# utils/ - 通用工具模块

## 这个文件夹负责什么

提供 CLI/TUI、国际化、输入框、队列、跨平台 Shell、流式输出等基础能力。

## 核心原理

把跨模块复用能力集中在 utils，业务模块只依赖稳定接口，避免重复实现 UI、Shell 和队列逻辑。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `i18n.py` | Internationalization support for RxyCode. | Internationalization support for RxyCode. |
| `queue.py` | Task queue manager - persistent JSON-backed task queue. | Task queue manager - persistent JSON-backed task queue. |
| `shell.py` | 跨平台 Shell 执行抽象层。 | 跨平台 Shell 执行抽象层。 |
| `streaming.py` | Modern UI components for RxyCode - strict MiMo alignment. | Modern UI components for RxyCode - strict MiMo alignment. |
| `tui.py` | 提供后端输出事件适配器及 `get_tui()` / `set_tui()`。 | 为 Agent、工具与 API 传输层提供统一的非交互输出接口。 |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：把跨模块复用能力集中在 utils，业务模块只依赖稳定接口，避免重复实现 UI、Shell 和队列逻辑。
- 代码规模：约 0 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# utils\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `i18n.py`

- 写了什么：Internationalization support for RxyCode.
- 功能是什么：Internationalization support for RxyCode.
- 核心原理：把跨模块复用能力集中在 utils，业务模块只依赖稳定接口，避免重复实现 UI、Shell 和队列逻辑。
- 代码规模：约 276 行。

关键对象/函数：

- 类 `I18n`：Internationalization manager.；常用方法：`lang`、`set_lang`、`t`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.utils.i18n import I18n

# 示例：根据真实业务传入依赖或配置
obj = I18n(...)
# result = obj.lang(...)
```

### `queue.py`

- 写了什么：Task queue manager - persistent JSON-backed task queue.
- 功能是什么：Task queue manager - persistent JSON-backed task queue.
- 核心原理：把跨模块复用能力集中在 utils，业务模块只依赖稳定接口，避免重复实现 UI、Shell 和队列逻辑。
- 代码规模：约 108 行。

关键对象/函数：

- 类 `QueueManager`：Persistent task queue backed by JSON file.；常用方法：`add_task`、`run_task`、`run_all`、`list_tasks`、`clear`、`remove`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.utils.queue import QueueManager

# 示例：根据真实业务传入依赖或配置
obj = QueueManager(...)
# result = obj.add_task(...)
```

### `shell.py`

- 写了什么：跨平台 Shell 执行抽象层。
- 功能是什么：跨平台 Shell 执行抽象层。
- 核心原理：把跨模块复用能力集中在 utils，业务模块只依赖稳定接口，避免重复实现 UI、Shell 和队列逻辑。
- 代码规模：约 136 行。

关键对象/函数：

- 类 `ShellExecutor`；常用方法：`translate_command`、`execute`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.utils.shell import ShellExecutor

# 示例：根据真实业务传入依赖或配置
obj = ShellExecutor(...)
# result = obj.translate_command(...)
```

### `streaming.py`

- 写了什么：Modern UI components for RxyCode - strict MiMo alignment.
- 功能是什么：Modern UI components for RxyCode - strict MiMo alignment.
- 核心原理：把跨模块复用能力集中在 utils，业务模块只依赖稳定接口，避免重复实现 UI、Shell 和队列逻辑。
- 代码规模：约 350 行。

关键对象/函数：

- 类 `TokenStats`：Track token usage and system statistics.；常用方法：`add_real_usage`、`total_tokens`、`cache_hit_rate`、`context_percent`、`billing_amount`、`add_usage`、`should_warn_about_token_budget`、`get_context_warning`
- 函数 `print_step(num, total, desc)`：Print step indicator.
- 函数 `print_step_done(num, total, desc)`：Print step done indicator.
- 函数 `print_thought(elapsed)`：Print thought indicator with yellow color.
- 函数 `print_tool_call(name, args)`：Print tool call.
- 函数 `print_tool_result(result, status)`：Print tool result.
- 函数 `print_success(msg)`：Print success message.
- 函数 `print_error(msg)`：Print error message.
- 函数 `print_info(msg)`：Print info message.
- 函数 `print_warning(msg)`：Print warning.
- 函数 `print_goodbye()`：Print goodbye.
- 函数 `print_command_hint()`：Print command hints.
- 函数 `print_chat_history_header(title)`：Print chat history header.
- 函数 `print_chat_saved(name)`：Print chat saved message.
- 函数 `print_chat_loaded(name)`：Print chat loaded message.
- 函数 `print_chat_list(chats)`：Print chat list with clean formatting.
- 函数 `print_subagent_start(task)`：Print sub-agent start message.
- 函数 `print_subagent_complete(result)`：Print sub-agent complete message.
- 函数 `print_auto_resume_prompt(chats)`：Print auto-resume prompt with clean formatting.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats

# 示例：根据真实业务传入依赖或配置
obj = TokenStats(...)
# result = obj.add_real_usage(...)
```

### `tui.py`

- 写了什么：提供 `BackendOutputAdapter` 以及进程级 `get_tui()` / `set_tui()`。
- 功能是什么：为 Agent、工具和 API 传输层提供统一的非交互输出事件接口。
- 核心原理：交互界面只存在于 `frontend/` 的 Ink 应用；Python 后端仅维护稳定的事件接收协议。

关键对象/函数：

- 类 `BackendOutputAdapter`：无 API/SSE 接收器时使用的轻量输出适配器。
- 函数 `get_tui()`：获取当前进程的输出事件接收器。
- 函数 `set_tui(tui)`：安装 API/SSE 感知的输出事件接收器。

## 典型协作关系

被 CLI、工具和核心流程复用，避免业务模块重复造轮子。
