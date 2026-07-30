# scheduler/ - 定时任务模块

## 这个文件夹负责什么

解析 cron 表达式并在后台管理计划任务。

## 核心原理

计划任务持久化为 JSON，后台线程周期扫描到期任务，执行后根据 cron/interval 计算下一次运行时间。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Scheduled task system for RxyCode. | Scheduled task system for RxyCode. |
| `cron.py` | Cron 解析：解析 5 字段表达式和 shorthand。 | Cron expression parser supporting standard 5-field format. |
| `manager.py` | 管理器：在不同模块中承担统一调度/记忆 façade/后台任务管理。 | Task scheduler manager - runs scheduled tasks in background. |

## 文件详解

### `__init__.py`

- 写了什么：Scheduled task system for RxyCode.
- 功能是什么：Scheduled task system for RxyCode.
- 核心原理：计划任务持久化为 JSON，后台线程周期扫描到期任务，执行后根据 cron/interval 计算下一次运行时间。
- 代码规模：约 6 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# scheduler\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `cron.py`

- 写了什么：Cron 解析：解析 5 字段表达式和 shorthand。
- 功能是什么：Cron expression parser supporting standard 5-field format.
- 核心原理：计划任务持久化为 JSON，后台线程周期扫描到期任务，执行后根据 cron/interval 计算下一次运行时间。
- 代码规模：约 183 行。

关键对象/函数：

- 类 `CronExpression`：Parsed cron expression.；常用方法：`matches`、`next_run`
- 函数 `parse_cron(expr)`：Parse a cron expression string into a CronExpression.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.scheduler.cron import CronExpression

# 示例：根据真实业务传入依赖或配置
obj = CronExpression(...)
# result = obj.matches(...)
```

### `manager.py`

- 写了什么：管理器：在不同模块中承担统一调度/记忆 façade/后台任务管理。
- 功能是什么：Task scheduler manager - runs scheduled tasks in background.
- 核心原理：计划任务持久化为 JSON，后台线程周期扫描到期任务，执行后根据 cron/interval 计算下一次运行时间。
- 代码规模：约 237 行。

关键对象/函数：

- 类 `ScheduledTask`：A scheduled task definition.；常用方法：`to_dict`、`from_dict`
- 类 `TaskScheduler`：Background task scheduler using cron expressions.；常用方法：`set_callback`、`add_task`、`remove_task`、`get_task`、`list_tasks`、`enable_task`、`disable_task`、`start`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.scheduler.manager import ScheduledTask

# 示例：根据真实业务传入依赖或配置
obj = ScheduledTask(...)
# result = obj.to_dict(...)
```

## 典型协作关系

计划任务最终会调用 Agent 执行用户配置的任务。
