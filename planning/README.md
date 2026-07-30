# planning/ - 规划模块

## 这个文件夹负责什么

把用户输入变成结构化目标，再拆成可执行任务树。

## 核心原理

先用结构化输出提炼目标，再递归拆解子任务，保留任务依赖和副作用声明，
直到任务可以交给执行层。每个 `SubTask`/`TaskNode` 都携带
`TaskEffect`：`read`、`write`、`danger` 或兼容旧计划的默认 `auto`。
`read` 会把执行器可选工具收窄到 READ；`write`/`danger` 会让验证链要求
真实 WRITE/DANGER 工具证据；`auto` 则根据工具提示、任务意图和完成声明
保守推断，不能用来绕过证据要求。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Planning layer: GoalPlanner and HierarchicalDecomposer. | Planning layer: GoalPlanner and HierarchicalDecomposer. |
| `decomposer.py` | 任务拆解：把目标递归拆成 TaskTree。 | HierarchicalDecomposer: recursive task tree decomposition. |
| `goal_planner.py` | 目标提炼：从自然语言输入提取目标、约束和成功标准。 | GoalPlanner: top-level goal extraction from user input. |

## 文件详解

### `__init__.py`

- 写了什么：Planning layer: GoalPlanner and HierarchicalDecomposer.
- 功能是什么：Planning layer: GoalPlanner and HierarchicalDecomposer.
- 核心原理：先用结构化输出提炼目标，再递归拆解子任务，保留任务依赖，直到任务可以交给执行层。
- 代码规模：约 6 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# planning\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `decomposer.py`

- 写了什么：任务拆解：把目标递归拆成 TaskTree。
- 功能是什么：HierarchicalDecomposer: recursive task tree decomposition.
- 核心原理：先用结构化输出提炼目标，再递归拆解子任务，保留任务依赖，直到任务可以交给执行层。
- 代码规模：约 72 行。

关键对象/函数：

- 类 `SubTask`
- 类 `SubTaskList`
- 类 `HierarchicalDecomposer`；常用方法：`decompose`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.planning.decomposer import SubTask

# 示例：根据真实业务传入依赖或配置
obj = SubTask(...)
# result = obj.<method>(...)
```

### `goal_planner.py`

- 写了什么：目标提炼：从自然语言输入提取目标、约束和成功标准。
- 功能是什么：GoalPlanner: top-level goal extraction from user input.
- 核心原理：先用结构化输出提炼目标，再递归拆解子任务，保留任务依赖，直到任务可以交给执行层。
- 代码规模：约 51 行。

关键对象/函数：

- 类 `GoalResult`：Structured output from the GoalPlanner LLM call.
- 类 `GoalPlanner`：Extracts the top-level goal from user input.；常用方法：`plan`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.planning.goal_planner import GoalResult

# 示例：根据真实业务传入依赖或配置
obj = GoalResult(...)
# result = obj.<method>(...)
```

## 典型协作关系

被 core/graph.py 的 goal_planner_node 和 decomposer_node 调用。
