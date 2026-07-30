# execution/ - 执行模块

## 这个文件夹负责什么

负责把任务节点调度出来、选择工具并完成单个任务执行。

## 核心原理

调度与执行分离：scheduler 只判断依赖和状态，executor 负责 ReAct 执行，tool_orchestrator 负责工具注册和筛选。

运行边界由 `execution` 配置统一提供：单次工具调用默认墙钟上限为
`tool_timeout_seconds=1800`，任务总上限为 `task_max_time_seconds=7200`。
`task_stall_timeout_seconds=0` 只表示默认不因“静默 600 秒”而误杀仍在工作的
任务，并不关闭工具或任务总时限。READ 工具只对瞬态失败自动重试；
WRITE/DANGER 工具在执行边界记录证据，并受审批、审计和副作用日志约束。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Execution layer: scheduler, executor, and tool orchestrator. | Execution layer: scheduler, executor, and tool orchestrator. |
| `executor.py` | 单任务执行器：用 ReAct 风格循环执行一个任务。 | Executor: single-task execution with ReAct loop. |
| `scheduler.py` | TaskScheduler: DAG-based task scheduling (deterministic, no LLM). | TaskScheduler: DAG-based task scheduling (deterministic, no LLM). |
| `tool_orchestrator.py` | 工具编排器：注册、批量注册、按任务选择工具。 | ToolOrchestrator: intelligent tool selection and registration. |

## 文件详解

### `__init__.py`

- 写了什么：Execution layer: scheduler, executor, and tool orchestrator.
- 功能是什么：Execution layer: scheduler, executor, and tool orchestrator.
- 核心原理：调度与执行分离：scheduler 只判断依赖和状态，executor 负责 ReAct 执行，tool_orchestrator 负责工具注册和筛选。
- 代码规模：约 7 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# execution\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `executor.py`

- 写了什么：单任务执行器：用 ReAct 风格循环执行一个任务。
- 功能是什么：Executor: single-task execution with ReAct loop.
- 核心原理：调度与执行分离：scheduler 只判断依赖和状态，executor 负责 ReAct 执行，tool_orchestrator 负责工具注册和筛选。
- 代码规模：约 34 行。

关键对象/函数：

- 类 `Executor`；常用方法：`execute`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.execution.executor import Executor

# 示例：根据真实业务传入依赖或配置
obj = Executor(...)
# result = obj.execute(...)
```

### `scheduler.py`

- 写了什么：TaskScheduler: DAG-based task scheduling (deterministic, no LLM).
- 功能是什么：TaskScheduler: DAG-based task scheduling (deterministic, no LLM).
- 核心原理：调度与执行分离：scheduler 只判断依赖和状态，executor 负责 ReAct 执行，tool_orchestrator 负责工具注册和筛选。
- 代码规模：约 79 行。

关键对象/函数：

- 类 `TaskScheduler`：Deterministic DAG scheduler over a TaskTree.；常用方法：`get_ready_tasks`、`get_parallel_groups`、`build_dag`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.execution.scheduler import TaskScheduler

# 示例：根据真实业务传入依赖或配置
obj = TaskScheduler(...)
# result = obj.get_ready_tasks(...)
```

### `tool_orchestrator.py`

- 写了什么：工具编排器：注册、批量注册、按任务选择工具。
- 功能是什么：ToolOrchestrator: intelligent tool selection and registration.
- 核心原理：调度与执行分离：scheduler 只判断依赖和状态，executor 负责 ReAct 执行，tool_orchestrator 负责工具注册和筛选。
- 代码规模：约 58 行。

关键对象/函数：

- 类 `ToolOrchestrator`：Registry and selector for agent tools.；常用方法：`register`、`register_many`、`get`、`get_all`、`select_tools`、`list_names`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

# 示例：根据真实业务传入依赖或配置
obj = ToolOrchestrator(...)
# result = obj.register(...)
```

## 典型协作关系

被 core/graph.py 调用，依赖 tools/ 提供环境操作能力。
