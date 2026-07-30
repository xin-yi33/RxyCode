# history/ - 历史追踪模块

## 这个文件夹负责什么

记录文件修改前后的内容、时间、原因和 diff，支持查看历史与撤销。

## 核心原理

每次改动都保存 ChangeRecord 快照，后续可按文件回放、比较或回滚。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | File change tracking module. | File change tracking module. |
| `tracker.py` | 文件变更追踪：保存修改前后快照、diff 和撤销信息。 | 文件变更追踪：保存修改前后快照、diff 和撤销信息。 |

## 文件详解

### `__init__.py`

- 写了什么：File change tracking module.
- 功能是什么：File change tracking module.
- 核心原理：每次改动都保存 ChangeRecord 快照，后续可按文件回放、比较或回滚。
- 代码规模：约 5 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# history\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `tracker.py`

- 写了什么：文件变更追踪：保存修改前后快照、diff 和撤销信息。
- 功能是什么：文件变更追踪：保存修改前后快照、diff 和撤销信息。
- 核心原理：每次改动都保存 ChangeRecord 快照，后续可按文件回放、比较或回滚。
- 代码规模：约 147 行。

关键对象/函数：

- 类 `ChangeRecord`：Record of a file change.
- 类 `FileTracker`：Tracks file changes within a session.；常用方法：`record_read`、`record_write`、`record_edit`、`get_changes`、`get_changes_for_file`、`get_diff_summary`、`get_last_diff`、`clear`
- 函数 `get_file_tracker()`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.history.tracker import ChangeRecord

# 示例：根据真实业务传入依赖或配置
obj = ChangeRecord(...)
# result = obj.<method>(...)
```

## 典型协作关系

通常被写文件/编辑文件工具调用，用于记录改动和回滚。
