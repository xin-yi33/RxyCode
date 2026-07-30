# tests/test_validation/ - 验证测试模块

## 这个文件夹负责什么

测试 RePlanner 对失败任务的二次拆解。

## 核心原理

用 mock LLM 返回补救子任务，检查失败节点能否扩展为新的可执行任务。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `test_re_planner.py` | Tests for RePlanner: secondary decomposition of failed tasks. | Tests for RePlanner: secondary decomposition of failed tasks. |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：用 mock LLM 返回补救子任务，检查失败节点能否扩展为新的可执行任务。
- 代码规模：约 0 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# tests\test_validation\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `test_re_planner.py`

- 写了什么：Tests for RePlanner: secondary decomposition of failed tasks.
- 功能是什么：Tests for RePlanner: secondary decomposition of failed tasks.
- 核心原理：用 mock LLM 返回补救子任务，检查失败节点能否扩展为新的可执行任务。
- 代码规模：约 97 行。

关键对象/函数：

- 类 `TestRePlanner`；常用方法：`test_basic_replan`、`test_max_retries_cancels`、`test_replan_with_dependencies`、`test_no_sub_tasks_marks_pending`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tests.test_validation.test_re_planner import TestRePlanner

# 示例：根据真实业务传入依赖或配置
obj = TestRePlanner(...)
# result = obj.test_basic_replan(...)
```

## 典型协作关系

覆盖 validation/re_planner.py。
