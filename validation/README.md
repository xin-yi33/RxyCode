# validation/ - 验证与重规划模块

## 这个文件夹负责什么

验证任务结果是否满足要求，并在失败时生成补救任务。

## 核心原理

先在工具边界做确定性证据校验，再用结构化评分判断完整性、相关性和格式；
低于阈值时交给 RePlanner 进行二次拆解。声明或推断为 `write`/`danger`
的任务必须包含已执行且成功的 WRITE/DANGER `ToolEvidence`，仅靠 LLM 文本
或高分不能通过。最终输出还要经过 claim-to-evidence grounding：每条 claim
必须逐字来自已通过叶子结果或成功工具证据，产物的存在性、大小与 SHA-256
会在出答案前再次检查。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Validation layer: result validation and re-planning. | Validation layer: result validation and re-planning. |
| `re_planner.py` | 失败重规划：把失败任务拆成补救步骤。 | RePlanner: secondary decomposition of failed tasks. |
| `validator.py` | 确定性证据检查 + 三维结构化评分。 | Validator: deterministic evidence checks plus structured scoring. |
| `side_effects.py` | 判定任务是否需要副作用证据，并检查 WRITE/DANGER 证据。 | Side-effect evidence policy. |
| `final_output.py` | 最终 claim-to-evidence grounding 与产物复验。 | Deterministic final-output grounding. |

## 文件详解

### `__init__.py`

- 写了什么：Validation layer: result validation and re-planning.
- 功能是什么：Validation layer: result validation and re-planning.
- 核心原理：用结构化评分判断正确性、完整性和可用性；低于阈值时交给 RePlanner 进行二次拆解。
- 代码规模：约 6 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# validation\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `re_planner.py`

- 写了什么：失败重规划：把失败任务拆成补救步骤。
- 功能是什么：RePlanner: secondary decomposition of failed tasks.
- 核心原理：用结构化评分判断正确性、完整性和可用性；低于阈值时交给 RePlanner 进行二次拆解。
- 代码规模：约 120 行。

关键对象/函数：

- 类 `RePlanner`：Decomposes failed tasks into finer-grained sub-tasks.；常用方法：`replan`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.validation.re_planner import RePlanner

# 示例：根据真实业务传入依赖或配置
obj = RePlanner(...)
# result = obj.replan(...)
```

### `validator.py`

- 写了什么：结果验证：按正确性、完整性、可用性评分。
- 功能是什么：Validator: three-dimensional result validation.
- 核心原理：用结构化评分判断正确性、完整性和可用性；低于阈值时交给 RePlanner 进行二次拆解。
- 代码规模：约 46 行。

关键对象/函数：

- 类 `ValidationResult`
- 类 `Validator`；常用方法：`validate`

`validate(..., evidence, tools_hint, effect)` 先执行 fail-closed 的确定性检查。
失败的工具、缺失的副作用证据、未执行的打开动作或异常结束哨兵会直接失败，
不会调用 LLM 评分。`TaskEffect.AUTO` 保留旧计划兼容性，但工具提示、任务意图
或“已创建/已修改”等完成声明仍会触发副作用证据要求。

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.validation.validator import ValidationResult

# 示例：根据真实业务传入依赖或配置
obj = ValidationResult(...)
# result = obj.<method>(...)
```

## 典型协作关系

被 graph 在任务执行后调用，失败时衔接 re_planner。
