# tests/test_execution/ - 执行测试模块

## 这个文件夹负责什么

测试 TaskScheduler 的 DAG 调度、依赖判断和取消级联。

## 核心原理

构造小型 TaskTree，不调用真实模型，只断言任务状态变化。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `test_scheduler.py` | Tests for TaskScheduler: DAG scheduling and CANCELLED cascade. | Tests for TaskScheduler: DAG scheduling and CANCELLED cascade. |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：构造小型 TaskTree，不调用真实模型，只断言任务状态变化。
- 代码规模：约 0 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# tests\test_execution\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `test_scheduler.py`

- 写了什么：Tests for TaskScheduler: DAG scheduling and CANCELLED cascade.
- 功能是什么：Tests for TaskScheduler: DAG scheduling and CANCELLED cascade.
- 核心原理：构造小型 TaskTree，不调用真实模型，只断言任务状态变化。
- 代码规模：约 129 行。

关键对象/函数：

- 类 `TestTaskScheduler`；常用方法：`test_ready_tasks_no_deps`、`test_ready_tasks_with_deps`、`test_cancelled_cascade`、`test_cancelled_does_not_affect_independent`、`test_failed_dep_blocks`、`test_parallel_groups`、`test_dag_export`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tests.test_execution.test_scheduler import TestTaskScheduler

# 示例：根据真实业务传入依赖或配置
obj = TestTaskScheduler(...)
# result = obj.test_ready_tasks_no_deps(...)
```

## 典型协作关系

覆盖 execution/scheduler.py。
