# recovery/ - 错误恢复模块

## 这个文件夹负责什么

处理执行异常、重试次数、失败状态和错误上下文。

## 核心原理

异常不直接中断主流程，而是转成状态更新；未超重试上限就重新排队，超过上限就标记失败。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Recovery layer: error handling and retry logic. | Recovery layer: error handling and retry logic. |
| `error_recovery.py` | 错误恢复：把异常转成可重试或失败的状态。 | ErrorRecovery: exception handling and retry logic. |

## 文件详解

### `__init__.py`

- 写了什么：Recovery layer: error handling and retry logic.
- 功能是什么：Recovery layer: error handling and retry logic.
- 核心原理：异常不直接中断主流程，而是转成状态更新；未超重试上限就重新排队，超过上限就标记失败。
- 代码规模：约 5 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# recovery\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `error_recovery.py`

- 写了什么：错误恢复：把异常转成可重试或失败的状态。
- 功能是什么：ErrorRecovery: exception handling and retry logic.
- 核心原理：异常不直接中断主流程，而是转成状态更新；未超重试上限就重新排队，超过上限就标记失败。
- 代码规模：约 55 行。

关键对象/函数：

- 类 `ErrorRecovery`：Handles execution errors with retry logic.；常用方法：`handle_error`、`get_error_summary`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorRecovery

# 示例：根据真实业务传入依赖或配置
obj = ErrorRecovery(...)
# result = obj.handle_error(...)
```

## 典型协作关系

被 core/graph.py 的 error_recovery_node 调用。
