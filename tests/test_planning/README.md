# tests/test_planning/ - 规划测试模块

## 这个文件夹负责什么

测试 HierarchicalDecomposer 的任务拆解行为。

## 核心原理

用 mock LLM 返回固定结构化子任务，检查生成的任务树是否正确。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | 包初始化文件，标记该目录为 Python 包并承载导出入口。 | 包初始化文件，标记该目录为 Python 包并承载导出入口。 |
| `test_decomposer.py` | Tests for the HierarchicalDecomposer (with mock LLM). | Tests for the HierarchicalDecomposer (with mock LLM). |

## 文件详解

### `__init__.py`

- 写了什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 功能是什么：包初始化文件，标记该目录为 Python 包并承载导出入口。
- 核心原理：用 mock LLM 返回固定结构化子任务，检查生成的任务树是否正确。
- 代码规模：约 0 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# tests\test_planning\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `test_decomposer.py`

- 写了什么：Tests for the HierarchicalDecomposer (with mock LLM).
- 功能是什么：Tests for the HierarchicalDecomposer (with mock LLM).
- 核心原理：用 mock LLM 返回固定结构化子任务，检查生成的任务树是否正确。
- 代码规模：约 130 行。

关键对象/函数：

- 类 `TestHierarchicalDecomposer`；常用方法：`test_basic_decomposition`、`test_dependency_resolution`、`test_no_decomposition_needed`、`test_max_depth_respected`、`test_dag_export`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.tests.test_planning.test_decomposer import TestHierarchicalDecomposer

# 示例：根据真实业务传入依赖或配置
obj = TestHierarchicalDecomposer(...)
# result = obj.test_basic_decomposition(...)
```

## 典型协作关系

覆盖 planning/decomposer.py。
