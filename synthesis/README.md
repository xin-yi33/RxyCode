# synthesis/ - 结果综合模块

## 这个文件夹负责什么

把多个叶子任务结果整理成最终回答。

## 核心原理

收集任务树叶子节点输出，再让 LLM 按用户原始需求组织成连贯、可交付的文本。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Synthesis layer: output aggregation and formatting. | Synthesis layer: output aggregation and formatting. |
| `synthesizer.py` | 输出综合：把多个任务结果整理成最终答案。 | OutputSynthesizer: aggregate all leaf task results into a final answer. |

## 文件详解

### `__init__.py`

- 写了什么：Synthesis layer: output aggregation and formatting.
- 功能是什么：Synthesis layer: output aggregation and formatting.
- 核心原理：收集任务树叶子节点输出，再让 LLM 按用户原始需求组织成连贯、可交付的文本。
- 代码规模：约 5 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# synthesis\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `synthesizer.py`

- 写了什么：输出综合：把多个任务结果整理成最终答案。
- 功能是什么：OutputSynthesizer: aggregate all leaf task results into a final answer.
- 核心原理：收集任务树叶子节点输出，再让 LLM 按用户原始需求组织成连贯、可交付的文本。
- 代码规模：约 43 行。

关键对象/函数：

- 类 `OutputSynthesizer`；常用方法：`synthesize`、`collect_results`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.synthesis.synthesizer import OutputSynthesizer

# 示例：根据真实业务传入依赖或配置
obj = OutputSynthesizer(...)
# result = obj.synthesize(...)
```

## 典型协作关系

位于 graph 末端，把任务结果变成用户可读答案。
