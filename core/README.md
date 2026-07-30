# core/ - 核心 Agent 模块

## 这个文件夹负责什么

定义 AgentV2、LangGraph 主流程、状态结构、系统提示词和 v2 配置，是项目的控制中枢。

## 核心原理

Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。

## Python 文件总览

| 文件 | 写了什么 | 功能是什么 |
|---|---|---|
| `__init__.py` | Core architecture: state definitions, graph, and configuration. | Core architecture: state definitions, graph, and configuration. |
| `agent_v2.py` | Agent 主实现：模型、工具、记忆、缓存、文件 fast path、下载意图和 LangGraph 全流程。 | Agent v2: drop-in replacement for the old Agent class. |
| `config.py` | Configuration management for RxyCode v2. | Configuration management for RxyCode v2. |
| `governance.py` | Provider/model 限流、角色模型路由和敏感动作决策契约。 | Runtime governance primitives. |
| `graph.py` | LangGraph 主图：定义规划、拆解、执行、验证、重规划、压缩、恢复、综合节点。 | LangGraph main graph: the full Hierarchical Plan-and-Execute pipeline. |
| `prompts.py` | 提示词构建：稳定系统提示词和用户消息格式。 | Shared system prompt for DeepSeek context caching. |
| `state.py` | 状态模型：TaskStatus、TaskNode、TaskTree、AgentState。 | Core data structures: TaskNode, TaskTree, and AgentState. |

## 文件详解

### `__init__.py`

- 写了什么：Core architecture: state definitions, graph, and configuration.
- 功能是什么：Core architecture: state definitions, graph, and configuration.
- 核心原理：Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。
- 代码规模：约 5 行。

关键对象/函数：

- 无公开类/函数；通常用于包初始化、导入聚合或占位。

实现方式示例代码：

```python
# core\__init__.py 没有独立调用入口，通常通过导入所在包触发。
```

### `agent_v2.py`

- 写了什么：Agent 主实现：模型、工具、记忆、缓存、文件 fast path、下载意图和 LangGraph 全流程。
- 功能是什么：Agent v2: drop-in replacement for the old Agent class.
- 核心原理：Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。
- 代码规模：约 1332 行。

关键对象/函数：

- 类 `UsageTrackingLLM`：Wrapper that auto-records token usage on every LLM call.；常用方法：`ainvoke`、`astream`、`bind_tools`、`with_structured_output`、`_apply_cache_control`
  - `_apply_cache_control(messages)`：在首条 SystemMessage 上注入 `cache_control: {"type": "ephemeral"}`，激活 DeepSeek/OpenAI provider 侧 KV cache。在 `ainvoke`/`astream`/`_raw_stream` 三个入口均调用，确保流式和非流式路径都命中缓存。
  - `_to_openai_messages(messages)`：将 LangChain 消息转为 OpenAI dict，**保留 `cache_control` 字段**，使流式路径（绕过 LangChain）也能命中 provider 缓存。
  - 每次调用先保留一个 request 单位、估算 input token 和配置的 output
    reservation；`ainvoke`、包装流和 raw stream 都在各自 `finally` 对每个
    grant 恰好结算一次。provider/stream 错误、取消和 breaker-open
    都不会泄漏 reservation。request 单位不退款，未使用的 output reservation
    退回 token bucket，超出预留的真实/观测 token 则成为后续调用的 debt。
- 函数 `_record_usage(resp, messages=None)`：从 LLM 响应中提取 token 用量并记录到 `token_stats`。支持三种来源：LangChain `usage_metadata`（非流式）、原始 OpenAI `chunk.usage`（流式，P2 修复后支持 DeepSeek `prompt_cache_hit_tokens` 和 OpenAI `prompt_tokens_details.cached_tokens`）、tiktoken 估算（兜底）。
- 类 `AgentV2`：LangGraph-based agent, drop-in compatible with the old Agent class.；常用方法：`run`
  - `_raw_stream(messages, tools=None)`：绕过 LangChain 直接调用 OpenAI async client 的流式接口，保留 `reasoning_content`（LangChain 会吞掉此字段）。P2 修复后在此方法内调用 `_apply_cache_control` 确保流式路径也注入缓存断点。
  - `_refresh_mcp_tools()`：按服务器配置指纹增量刷新；不相关的健康 client
    保持不变，失败服务器按 5 秒起步、指数增长、300 秒封顶的退避重试。
    `runtime_status().mcp` 公开聚合的 `backoff_servers` 和
    `next_retry_seconds`，并保留 `host_process` / `safe_allowlist_plus_explicit`
    信任边界，不返回配置指纹或进程参数。

限流状态保存在每个 `AgentV2` 的进程内存中，并按 provider/model 隔离；锁只
保证同一共享 Agent 跨事件循环的并发安全，不提供跨 Agent、跨进程或跨主机的
分布式配额协调。

- 类 `SubAgentV2`：Sub-agent for $ prefix commands (compatibility with old SubAgent).；常用方法：`run`

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

# 示例：根据真实业务传入依赖或配置
obj = UsageTrackingLLM(...)
# result = obj.ainvoke(...)
```

### `config.py`

- 写了什么：Configuration management for RxyCode v2.
- 功能是什么：Configuration management for RxyCode v2.
- 核心原理：Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。
- 代码规模：约 119 行。

关键对象/函数：

- 类 `LLMConfig`：Configuration for an LLM provider.
- 类 `MemoryConfig`：Configuration for the memory system.
- 类 `ExecutorConfig`：Configuration for the executor.
- 类 `AppConfig`：Top-level application configuration.
- 函数 `get_config_dir()`：Return the user-level config directory, creating it if needed.
- 函数 `get_data_dir(cfg)`：Return the data directory, creating it if needed.
- 函数 `get_config_path()`
- 函数 `load_config(path)`：Load config from YAML file, falling back to defaults.
- 函数 `save_config(cfg, path)`：Persist config to YAML file.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.core.config import LLMConfig

# 示例：根据真实业务传入依赖或配置
obj = LLMConfig(...)
# result = obj.<method>(...)
```

### `graph.py`

- 写了什么：LangGraph 主图：定义规划、拆解、执行、验证、重规划、压缩、恢复、综合节点。
- 功能是什么：LangGraph main graph: the full Hierarchical Plan-and-Execute pipeline.
- 核心原理：Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。
- 代码规模：约 497 行。

关键对象/函数：

- 异步函数 `goal_planner_node(state)`：Phase 1: Extract the top-level goal from user input.
- 异步函数 `decomposer_node(state)`：Phase 1b: Decompose the goal into a task tree.
- 异步函数 `executor_node(state)`：Phase 2: Execute the current task.
- 异步函数 `validator_node(state)`：Phase 3: Validate the execution result.
- 异步函数 `re_planner_node(state)`：Phase 3b: Re-plan a failed task.
- 异步函数 `compressor_node(state)`：Compress context if it exceeds the threshold.
- 异步函数 `error_recovery_node(state)`：Handle execution errors.
- 异步函数 `synthesizer_node(state)`：Phase 4: Synthesize all results into the final output.
- 函数 `route_next(state)`：Main scheduling router: decide what to do next.
- 函数 `route_after_validator(state)`：Router after validation: pass → next task, fail → re-plan or cancel.
- 函数 `build_graph()`：Build and return the compiled LangGraph.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.core.graph import goal_planner_node

result = goal_planner_node(state=...)
```

### `prompts.py`

- 写了什么：提示词构建：稳定系统提示词和用户消息格式。
- 功能是什么：Shared system prompt for DeepSeek context caching.
- 核心原理：Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。
- 代码规模：约 58 行。

关键对象/函数：

- 函数 `get_system_prompt()`：Return the unified system prompt.  Always identical for all calls.
- 函数 `build_user_message(role_instruction, user_content, memory_context)`：Build a user message with role instruction + content + optional context.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.core.prompts import get_system_prompt

result = get_system_prompt()
```

### `state.py`

- 写了什么：状态模型：TaskStatus、TaskEffect、TaskNode、TaskTree、AgentState。
- 功能是什么：Core data structures: TaskNode, TaskTree, and AgentState.
- 核心原理：Plan-and-Execute 闭环：目标提炼、任务拆解、调度执行、结果验证、失败重规划、上下文压缩、最终综合。简单请求走 fast path，复杂请求走图流程。
- 代码规模：约 201 行。

关键对象/函数：

- 类 `TaskStatus`：Lifecycle status of a task node.
- 类 `TaskEffect`：任务声明的最大副作用类别：`read`、`write`、`danger`，
  以及兼容旧 checkpoint/计划的 `auto`。该字段会进入执行工具筛选和验证证据判定。
- 类 `TaskNode`：A single task node that can be nested into a tree.；常用方法：`touch`
- 类 `TaskTree`：A tree of TaskNodes rooted at a single goal node.；常用方法：`get_root`、`get_children`、`get_leaf_nodes`、`get_pending_leaves`、`get_failed_nodes`、`find_by_title`、`add_node`、`update_node`
- 类 `AgentState`：Global state shared by every node in the LangGraph.

实现方式示例代码：

```python
from RxyCode.RxyCode1_1_0.core.state import TaskStatus

# 示例：根据真实业务传入依赖或配置
obj = TaskStatus(...)
# result = obj.<method>(...)
```

## 典型协作关系

向上服务 main.py/api_server.py，向下编排 planning、execution、validation、memory、cache、tools。
