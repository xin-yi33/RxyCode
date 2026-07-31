# RxyCode v2 架构设计文档

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 RxyCode 从自定义 Plan-Execute 架构重构为基于 LangGraph 的 Hierarchical Plan-and-Execute 分层任务编排系统。

**Architecture:** 基于 LangGraph StateGraph 构建分层任务树，支持父子任务嵌套、DAG 调度、失败重拆解、上下文压缩、结果校验与聚合输出。核心创新点是 Reviewer + 二次分层拆解机制。

**Tech Stack:** Python 3.13+, LangGraph, LangChain, FastAPI, Redis (state), ChromaDB/Qdrant (vector memory), Pydantic v2

---

## 一、整体架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Layer                            │
│              /chat  /task/{id}  /status  /health                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ GoalPlanner │  │ Hierarchical │  │  Output Synthesizer    │ │
│  │  (顶层规划)  │→ │ Decomposer   │  │  (结果聚合)             │ │
│  └──────┬──────┘  │ (分层拆解)    │  └────────────────────────┘ │
│         │         └──────┬───────┘                              │
│         ▼                ▼                                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   TaskTree (任务树)                        │  │
│  │  Goal → Task1 → [SubTask1.1, SubTask1.2]                 │  │
│  │       → Task2 → [SubTask2.1, SubTask2.2, SubTask2.3]     │  │
│  │       → Task3 → [SubTask3.1]                              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                          │                                      │
│         ┌────────────────┼────────────────┐                    │
│         ▼                ▼                ▼                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐            │
│  │  Scheduler  │  │   Executor  │  │  Validator  │            │
│  │ (DAG 调度)   │  │ (单步执行)   │  │ (结果校验)   │            │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘            │
│         │                │                │                    │
│         ▼                ▼                ▼                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Memory System (全局记忆)                      │  │
│  │  ShortTerm (Redis) + LongTerm (VectorDB + SQLite)         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ Tool Orch.   │  │ Error Recov. │  │ Context Compressor   │ │
│  │ (工具编排)    │  │ (异常恢复)    │  │ (上下文压缩 258k)     │ │
│  └──────────────┘  └──────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、核心数据结构

### 2.1 TaskNode (任务节点)

```python
class TaskStatus(str, Enum):
    PENDING = "pending"           # 待执行
    WAITING = "waiting"           # 等待依赖完成
    RUNNING = "running"           # 执行中
    PASSED = "passed"             # 校验通过
    FAILED = "failed"             # 校验失败
    RE_PLANNING = "re_planning"   # 二次拆解中
    CANCELLED = "cancelled"       # 已取消

class TaskNode(BaseModel):
    id: str                              # UUID
    title: str                           # 任务标题
    description: str                     # 任务描述
    requirement: str                     # 验收标准 (给 Validator 用)
    status: TaskStatus = TaskStatus.PENDING
    parent_id: Optional[str] = None      # 父任务 ID
    children_ids: list[str] = []         # 子任务 ID 列表
    dependent_tasks: list[str] = []      # 依赖的任务 ID (DAG)
    depth: int = 0                       # 层级深度 (0=顶层)
    result: Optional[str] = None         # 执行结果
    validation_result: Optional[dict] = None  # 校验结果
    error_history: list[str] = []        # 错误历史
    retry_count: int = 0                 # 重试次数
    max_retries: int = 3                 # 最大重试次数
    tools_hint: list[str] = []           # 建议使用的工具
    created_at: datetime
    updated_at: datetime
```

### 2.2 TaskTree (任务树)

```python
class TaskTree(BaseModel):
    goal_id: str                         # 顶层目标节点 ID
    nodes: dict[str, TaskNode]           # id → TaskNode 映射
    constraints: list[str] = []          # 全局约束条件
    output_format: str = "markdown"      # 最终输出格式
    
    def get_root(self) -> TaskNode: ...
    def get_children(self, node_id: str) -> list[TaskNode]: ...
    def get_leaf_nodes(self) -> list[TaskNode]: ...
    def get_pending_leaves(self) -> list[TaskNode]: ...
    def get_failed_nodes(self) -> list[TaskNode]: ...
    def add_node(self, node: TaskNode): ...
    def update_node(self, node_id: str, **kwargs): ...
    def is_complete(self) -> bool: ...   # 所有叶子节点都 PASSED
    def to_dag(self) -> dict: ...        # 导出 DAG 结构
```

---

## 三、LangGraph 主图设计

### 3.1 全局 State

```python
class AgentState(TypedDict):
    # 输入
    user_input: str
    session_id: str
    
    # 任务树
    task_tree: TaskTree
    
    # 记忆
    memory_context: str           # 当前上下文摘要
    conversation_history: list[dict]  # 对话历史
    
    # 执行状态
    current_task_id: Optional[str]
    execution_results: Annotated[list[dict], operator.add]
    
    # 输出
    final_response: Optional[str]
    
    # 控制流
    phase: str  # "planning" | "executing" | "validating" | "synthesizing" | "done"
    error: Optional[str]
```

### 3.2 主图节点

```python
from langgraph.graph import StateGraph, START, END

workflow = StateGraph(AgentState)

# Phase 1: 规划
workflow.add_node("goal_planner", goal_planner_node)
workflow.add_node("decomposer", hierarchical_decomposer_node)

# Phase 2: 执行 (调度逻辑用 conditional_edges 实现，不单独建 node)
workflow.add_node("executor", executor_node)

# Phase 3: 校验
workflow.add_node("validator", validator_node)
workflow.add_node("re_planner", re_planner_node)

# Phase 4: 合成
workflow.add_node("synthesizer", output_synthesizer_node)

# 辅助
workflow.add_node("compressor", context_compressor_node)
workflow.add_node("error_recovery", error_recovery_node)
```

### 3.3 图的边和条件路由

调度逻辑不作为独立 node，而是用 `conditional_edges` 在图的路由层实现。
好处: 减少一次 LLM 状态传递开销，调度决策是纯确定性的（遍历 TaskTree），不需要 node 函数。

```python
# 入口
workflow.add_edge(START, "goal_planner")

# 规划阶段
workflow.add_edge("goal_planner", "decomposer")

# 拆解完成后，用 conditional_edges 直接路由到下一步
# (代替原来的 decomposer → scheduler → conditional_edges 两跳)
workflow.add_conditional_edges(
    "decomposer",
    route_next,   # 调度逻辑内嵌在路由函数中
    {
        "execute": "executor",
        "compress": "compressor",
        "synthesize": "synthesizer",
        "error": "error_recovery",
    }
)

# 执行完成后进入校验
workflow.add_edge("executor", "validator")

# 校验器决定下一步
workflow.add_conditional_edges(
    "validator",
    route_after_validator,
    {
        "execute": "executor",       # 校验通过，调度下一个任务
        "re_plan": "re_planner",     # 不通过，触发二次拆解
        "synthesize": "synthesizer", # 所有任务完成
        "compress": "compressor",    # 上下文过大
        "error": "error_recovery",   # 严重错误
    }
)

# 二次拆解后，用 conditional_edges 路由到下一步
workflow.add_conditional_edges(
    "re_planner",
    route_next,
    {
        "execute": "executor",
        "compress": "compressor",
        "synthesize": "synthesizer",
        "error": "error_recovery",
    }
)

# 压缩后回到路由
workflow.add_conditional_edges(
    "compressor",
    route_next,
    {
        "execute": "executor",
        "synthesize": "synthesizer",
        "error": "error_recovery",
    }
)

# 错误恢复后回到路由
workflow.add_conditional_edges(
    "error_recovery",
    route_next,
    {
        "execute": "executor",
        "synthesize": "synthesizer",
        "error": END,  # 不可恢复错误，终止
    }
)

# 合成完成
workflow.add_edge("synthesizer", END)

app = workflow.compile()
```

**路由函数 (纯确定性，无 LLM 调用):**

```python
def route_next(state: AgentState) -> str:
    """调度决策: 纯确定性遍历 TaskTree，选择下一步动作。
    
    优先级:
    1. 所有叶子节点 PASSED/CANCELLED → synthesize
    2. 上下文超过 258k → compress
    3. 有就绪任务 → execute
    4. 循环依赖/全部阻塞 → error
    """
    tree = state["task_tree"]
    
    # 检查是否全部完成
    if tree.is_complete():
        return "synthesize"
    
    # 检查上下文大小
    memory_ctx = state.get("memory_context", "")
    if len(memory_ctx) > 258000:
        return "compress"
    
    # 查找就绪任务
    ready = _get_ready_tasks(tree)
    if ready:
        # 将就绪任务写入 state
        next_task = ready[0]
        next_task.status = TaskStatus.RUNNING
        state["current_task_id"] = next_task.id
        return "execute"
    
    return "error"


def route_after_validator(state: AgentState) -> str:
    """校验后路由: 根据校验结果决定下一步"""
    tree = state["task_tree"]
    task = tree.nodes.get(state.get("current_task_id"))
    
    if not task:
        return "error"
    
    if task.status == TaskStatus.PASSED:
        # 校验通过，调度下一个
        return route_next(state)
    elif task.status == TaskStatus.FAILED:
        if task.retry_count < task.max_retries:
            return "re_plan"
        else:
            # 超过重试次数，标记取消，继续其他任务
            task.status = TaskStatus.CANCELLED
            return route_next(state)
    else:
        return "error"


def _get_ready_tasks(tree: TaskTree) -> list[TaskNode]:
    """获取所有依赖已满足的叶子任务 (确定性逻辑)"""
    ready = []
    for node in tree.get_pending_leaves():
        deps_met = True
        for dep_id in node.dependent_tasks:
            dep_node = tree.nodes.get(dep_id)
            if not dep_node:
                continue  # 依赖节点不存在，跳过
            if dep_node.status == TaskStatus.PASSED:
                continue  # 依赖已满足
            if dep_node.status == TaskStatus.CANCELLED:
                # 依赖被取消 → 当前任务也标记取消
                node.status = TaskStatus.CANCELLED
                deps_met = False
                break
            # 依赖未完成 (PENDING/RUNNING/FAILED/RE_PLANNING)
            deps_met = False
            break
        if deps_met and node.status == TaskStatus.PENDING:
            ready.append(node)
    
    # 优先级: 深度浅的优先，同深度按创建时间
    ready.sort(key=lambda n: (n.depth, n.created_at))
    return ready
```

---

## 四、各模块详细设计

### 4.1 Planning Layer (规划层)

#### GoalPlanner (顶层规划)

**职责:** 接收用户输入，提炼总目标、约束条件、输出要求。

```python
async def goal_planner_node(state: AgentState) -> dict:
    """顶层规划: 用户输入 → 目标 + 约束 + 输出要求"""
    
    memory = await memory_system.get_context(state["session_id"])
    
    prompt = f"""分析用户需求，提取：
1. 核心目标 (goal): 一句话描述最终要达成什么
2. 约束条件 (constraints): 限制条件、技术栈、风格要求等
3. 输出要求 (output_format): 最终交付物的格式和结构

用户输入: {state['user_input']}
历史上下文: {memory}

输出 JSON 格式。"""
    
    result = await llm.ainvoke(prompt)
    parsed = GoalResult.model_validate_json(result)
    
    # 创建顶层目标节点
    root = TaskNode(
        id=str(uuid4()),
        title=parsed.goal,
        description=state["user_input"],
        requirement=parsed.goal,
        depth=0,
    )
    
    tree = TaskTree(
        goal_id=root.id,
        nodes={root.id: root},
        constraints=parsed.constraints,
        output_format=parsed.output_format,
    )
    
    return {
        "task_tree": tree,
        "phase": "planning",
        "memory_context": memory,
    }
```

#### HierarchicalDecomposer (分层拆解)

**职责:** 将目标递归拆解为可执行的叶子任务。

```python
async def hierarchical_decomposer_node(state: AgentState) -> dict:
    """分层拆解: 目标 → 多级子任务树"""
    
    tree = state["task_tree"]
    memory = state["memory_context"]
    
    # 从根节点开始递归拆解
    await _decompose_recursive(tree, tree.get_root(), memory, max_depth=4)
    
    return {"task_tree": tree, "phase": "executing"}


async def _decompose_recursive(tree: TaskTree, node: TaskNode, 
                                memory: str, max_depth: int):
    """递归拆解直到叶子节点可执行"""
    
    if node.depth >= max_depth:
        return  # 达到最大深度，不再拆解
    
    prompt = f"""你是一个任务拆解专家。将以下任务拆解为 2-5 个可独立执行的子任务。

任务: {node.title}
描述: {node.description}
约束: {tree.constraints}
上下文: {memory}

每个子任务输出:
- title: 子任务标题
- description: 具体要做什么
- requirement: 验收标准 (给校验器用)
- tools_hint: 建议使用的工具
- depends_on_index: 依赖的其他子任务在同一列表中的索引 (空=无依赖, 如 [0,2] 表示依赖第1和第3个子任务)

判断是否需要继续拆解的规则:
- 如果子任务可以在 1-2 次工具调用内完成 → 不需要再拆
- 如果子任务涉及多文件操作、复杂推理、多步骤流程 → 继续拆

输出 JSON 数组。"""
    
    result = await llm.ainvoke(prompt)
    sub_tasks = SubTaskList.model_validate_json(result)
    
    # 先创建所有子节点，收集 id 映射
    created_children: list[TaskNode] = []
    for st in sub_tasks.tasks:
        child = TaskNode(
            id=str(uuid4()),
            title=st.title,
            description=st.description,
            requirement=st.requirement,
            parent_id=node.id,
            depth=node.depth + 1,
            tools_hint=st.tools_hint,
        )
        tree.add_node(child)
        node.children_ids.append(child.id)
        created_children.append(child)
    
    # 用索引解析依赖关系 (LLM 输出的是同批次内的索引，不是 title)
    for i, st in enumerate(sub_tasks.tasks):
        for dep_index in st.depends_on_index:
            if 0 <= dep_index < len(created_children) and dep_index != i:
                created_children[i].dependent_tasks.append(
                    created_children[dep_index].id
                )
    
    # 递归拆解子任务
    for child in created_children:
        await _decompose_recursive(tree, child, memory, max_depth)
```

### 4.2 Scheduler (调度模块)

**职责:** 基于 TaskTree 的依赖关系构建 DAG，管理执行队列。

**注意:** 调度逻辑已从独立 node 移到 `route_next` / `route_after_validator` 路由函数中。
以下 `TaskScheduler` 是被路由函数调用的纯工具类，不再作为 LangGraph 节点。

```python
class TaskScheduler:
    """基于 DAG 的任务调度器 (纯确定性逻辑，无 LLM 调用)"""
    
    def __init__(self, tree: TaskTree):
        self.tree = tree
    
    def build_dag(self) -> dict:
        """解析任务树，构建 DAG (仅叶子节点参与)"""
        dag = {}
        for node_id, node in self.tree.nodes.items():
            if not node.children_ids:  # 只有叶子节点参与调度
                dag[node_id] = node.dependent_tasks
        return dag
    
    def get_ready_tasks(self) -> list[TaskNode]:
        """获取所有依赖已满足的叶子任务"""
        ready = []
        for node in self.tree.get_pending_leaves():
            deps_met = True
            for dep_id in node.dependent_tasks:
                dep_node = self.tree.nodes.get(dep_id)
                if not dep_node:
                    continue
                if dep_node.status == TaskStatus.PASSED:
                    continue
                if dep_node.status == TaskStatus.CANCELLED:
                    # 依赖被取消 → 当前任务也标记取消 (级联取消)
                    node.status = TaskStatus.CANCELLED
                    deps_met = False
                    break
                # PENDING/RUNNING/FAILED/RE_PLANNING → 依赖未满足
                deps_met = False
                break
            if deps_met and node.status == TaskStatus.PENDING:
                ready.append(node)
        
        ready.sort(key=lambda n: (n.depth, n.created_at))
        return ready
    
    def get_parallel_groups(self) -> list[list[TaskNode]]:
        """将就绪任务按依赖层级分组，同组可并行"""
        ready = self.get_ready_tasks()
        groups = {}
        for task in ready:
            dep_level = max(
                (self.tree.nodes[d].depth for d in task.dependent_tasks),
                default=-1
            )
            groups.setdefault(dep_level, []).append(task)
        return list(groups.values())
```

### 4.3 Executor (单步执行器)

**职责:** 执行单个子任务，集成工具调用，有独立上下文。

```python
async def executor_node(state: AgentState) -> dict:
    """执行单个子任务"""
    
    tree = state["task_tree"]
    task = tree.nodes[state["current_task_id"]]
    
    # 构建任务上下文 (从 Memory System 获取)
    task_context = await memory_system.get_task_context(
        session_id=state["session_id"],
        task_id=task.id,
        parent_id=task.parent_id,
    )
    
    # 选择工具 (根据 tools_hint)
    available_tools = tool_orchestrator.select_tools(task.tools_hint)
    
    # 执行 (ReAct 循环，单任务内)
    prompt = f"""执行以下任务:

任务: {task.title}
描述: {task.description}
上下文: {task_context}
可用工具: {[t.name for t in available_tools]}

使用工具完成任务，完成后输出结果。"""
    
    agent = create_react_agent(llm, available_tools)
    result = await agent.ainvoke({"messages": [("user", prompt)]})
    
    task_result = result["messages"][-1].content
    task.result = task_result
    
    # 三态记忆策略：不在 Executor 写入记忆
    # 只有 Validator 通过后才写入对话记忆
    # 失败结果写入 error log (memory.log_error)
    
    return {
        "task_tree": tree,
        "execution_results": [{"task_id": task.id, "result": task_result}],
    }
```

**三态记忆写入策略:**
```
Executor 产出 result → 只存 task.result (临时，不进记忆)
    ↓
Validator 校验
    ├─ PASSED → memory.store_execution()  ✓ 写入对话记忆
    ├─ FAILED → memory.log_error()        → 只写 error log
    └─ CANCELLED → memory.log_error()     → 只写 error log
```

**原因:** 未验证的结果不应污染对话记忆。错误结果写入 `~/.rxycode/memory/sessions/<id>/errors.log`，不影响后续 LLM 调用的上下文。

### 4.4 Validator (结果校验器)

**职责:** 独立校验每个子任务的执行结果。

```python
class ValidationResult(BaseModel):
    passed: bool
    completeness_score: float    # 0-1, 完整性
    relevance_score: float       # 0-1, 相关性
    format_score: float          # 0-1, 格式合规
    issues: list[str]            # 具体问题列表
    suggestion: str              # 改进建议


async def validator_node(state: AgentState) -> dict:
    """校验执行结果"""
    
    tree = state["task_tree"]
    task = tree.nodes[state["current_task_id"]]
    
    prompt = f"""校验以下任务执行结果是否达标。

任务: {task.title}
描述: {task.description}
验收标准: {task.requirement}
执行结果: {task.result}

从三个维度评分 (0-1):
1. 完整性: 结果是否覆盖所有需求
2. 相关性: 是否偏离当前任务描述
3. 格式: 是否符合指定格式

输出 JSON。"""
    
    result = await llm.ainvoke(prompt)
    validation = ValidationResult.model_validate_json(result)
    
    task.validation_result = validation.model_dump()
    
    if validation.passed:
        task.status = TaskStatus.PASSED
        return {"phase": "executing"}  # 回到调度器
    else:
        task.status = TaskStatus.FAILED
        task.error_history.append(validation.suggestion)
        return {"phase": "validating"}  # 触发二次拆解
```

### 4.5 Re-Planner (二次分层拆解)

**核心模块:** 对校验失败的任务进行更细粒度的拆解。

```python
async def re_planner_node(state: AgentState) -> dict:
    """二次拆解: 将失败任务拆解为更细粒度的子任务"""
    
    tree = state["task_tree"]
    failed_task = tree.nodes[state["current_task_id"]]
    
    # 检查重试次数
    if failed_task.retry_count >= failed_task.max_retries:
        failed_task.status = TaskStatus.CANCELLED
        return {"phase": "executing"}  # 跳过，回调度器
    
    failed_task.retry_count += 1
    failed_task.status = TaskStatus.RE_PLANNING
    
    prompt = f"""以下任务执行失败，需要拆解为更细粒度的子任务。

原任务: {failed_task.title}
原描述: {failed_task.description}
验收标准: {failed_task.requirement}
失败原因: {failed_task.validation_result}
错误历史: {failed_task.error_history}
上次执行结果: {failed_task.result}

将这个任务拆解为 2-4 个更小的、更具体的子任务。
每个子任务要:
1. 更具体、更可执行
2. 有明确的验收标准
3. 考虑之前的失败原因

输出 JSON 数组。"""
    
    result = await llm.ainvoke(prompt)
    sub_tasks = SubTaskList.model_validate_json(result)
    
    for st in sub_tasks.tasks:
        child = TaskNode(
            id=str(uuid4()),
            title=st.title,
            description=st.description,
            requirement=st.requirement,
            parent_id=failed_task.id,
            depth=failed_task.depth + 1,
            tools_hint=st.tools_hint,
        )
        tree.add_node(child)
        failed_task.children_ids.append(child.id)
    
    return {"task_tree": tree, "phase": "executing"}
```

### 4.6 Memory System (记忆系统)

```python
class MemorySystem:
    """混合记忆: Redis (短期) + VectorDB (长期) + SQLite (结构化)"""
    
    def __init__(self):
        self.short_term = RedisMemory()       # 对话窗口、执行状态
        self.long_term = VectorMemory()       # 向量检索 (ChromaDB/Qdrant)
        self.structured = SQLiteMemory()      # 任务树、执行历史、配置
    
    async def get_context(self, session_id: str) -> str:
        """获取会话上下文 (短期 + 长期检索)"""
        recent = await self.short_term.get_recent(session_id, limit=10)
        relevant = await self.long_term.search(session_id, query="", top_k=5)
        return format_context(recent, relevant)
    
    async def get_task_context(self, session_id: str, 
                                task_id: str, parent_id: str) -> str:
        """获取任务执行上下文 (父任务结果 + 兄弟任务结果)"""
        parent_result = ""
        if parent_id:
            parent = await self.structured.get_task(parent_id)
            parent_result = parent.result or ""
        
        siblings = await self.structured.get_sibling_results(task_id)
        
        return f"父任务结果: {parent_result}\n兄弟任务结果: {siblings}"
    
    async def store_execution(self, session_id: str, 
                               task_id: str, result: str):
        """存储已验证的执行结果到对话记忆
        
        只有 Validator PASSED 后才调用此方法。
        未验证的结果不应写入对话记忆。
        """
        await self.short_term.append(session_id, f"[Task {task_id}]: {result}")
        await self.long_term.index(session_id, task_id, result)
        await self.structured.update_task_result(task_id, result)
    
    async def log_error(self, session_id: str,
                        task_id: str, error: str):
        """记录错误到 error log (不进对话记忆)
        
        错误写入 ~/.rxycode/memory/sessions/<id>/errors.log
        不污染后续 LLM 调用的对话上下文。
        """
        self.long_term.append_error_log(task_id, error)
    
    async def compress_if_needed(self, session_id: str, 
                                  threshold: int = 258000):
        """上下文压缩 (三级 Codex-style 压缩)
        
        Tier 1: 无损截断 (零 LLM)
        Tier 2: 规则精简 (零 LLM)
        Tier 3: LLM 增量摘要 (1 次 LLM)
        """
        token_count = await self.short_term.get_token_count(session_id)
        if token_count > threshold:
            history = await self.short_term.get_all(session_id)
            compressed = await self._compress(history)
            await self.short_term.replace_all(session_id, compressed)
            await self.long_term.index_compressed(session_id, compressed)
```

### 4.7 Context Compressor (上下文压缩)

**实现文件:** `memory/compressor.py`

**压缩策略 (Codex-style 三级压缩):**

| Tier | 触发条件 | 操作 | LLM 开销 |
|------|---------|------|----------|
| **Tier 1** | 总 token > 窗口 90% | 工具输出中段截断 (>10k token 保留头尾丢中间) + 助手旧回复只留前两句 | 零 |
| **Tier 2** | Tier 1 后仍超限 | 划定保护区 (20k token 最近消息不动)，更早消息替换为占位符，原始文本移入 long-term | 零 |
| **Tier 3** | Tier 1+2 后仍超限 | 提取增量 delta → LLM 生成 handoff 摘要 → 只保留 摘要+保护区 | 1 次 LLM |

**关键设计:**
- Token 用 **tiktoken** 计数 (cl100k_base)，不用 `len(str)`
- Tier 3 增量合并：保存 `_last_handoff`，下次只总结新增 delta，不重复总结全部历史
- `compress_sync()` 给 `add_interaction()` 用（只跑 Tier 1/2，零 LLM）
- `compress_async()` 给 `compressor_node` 用（完整三级）
- 触发阈值：90% of 258k token window (~232k tokens)

```python
async def compressor_node(state: AgentState) -> dict:
    """上下文压缩: 当 token 超过 90% 阈值时触发"""
    memory: MemoryManager = state["_memory"]
    memory_ctx = await memory.compress_if_needed(state["session_id"])
    return {"memory_context": memory_ctx}
```

**路由阈值 (route_next):**
```python
# ~3 chars/token 估算
estimated_tokens = len(memory_ctx) // 3
if estimated_tokens > 232_000:  # 90% of 258k
    return "compress"
```

### 4.8 Error Recovery (错误恢复)

```python
async def error_recovery_node(state: AgentState) -> dict:
    """错误恢复: 处理异常情况"""
    
    error = state.get("error", "")
    tree = state["task_tree"]
    current_id = state.get("current_task_id")
    
    if current_id:
        task = tree.nodes.get(current_id)
        if task:
            if task.retry_count < task.max_retries:
                # 重试当前任务
                task.retry_count += 1
                task.status = TaskStatus.PENDING
                task.error_history.append(error)
                return {"phase": "executing", "error": None}
            else:
                # 标记为取消，继续其他任务
                task.status = TaskStatus.CANCELLED
                return {"phase": "executing", "error": None, "current_task_id": None}
    
    return {"phase": "executing", "error": None}
```

### 4.9 Output Synthesizer (结果聚合)

```python
async def synthesizer_node(state: AgentState) -> dict:
    """结果聚合: 遍历 TaskTree，整合所有结果"""
    
    tree = state["task_tree"]
    memory = state["memory_context"]
    
    # 收集所有叶子节点结果
    leaf_results = []
    for node in tree.get_leaf_nodes():
        if node.status == TaskStatus.PASSED:
            leaf_results.append({
                "title": node.title,
                "depth": node.depth,
                "result": node.result,
                "parent_id": node.parent_id,
            })
    
    prompt = f"""将以下分层任务结果整合为最终交付内容。

用户原始需求: {state['user_input']}
全局约束: {tree.constraints}
输出格式: {tree.output_format}

各子任务结果:
{json.dumps(leaf_results, ensure_ascii=False, indent=2)}

整合要求:
1. 按任务层级结构组织内容
2. 统一输出格式和风格
3. 去除重复、冗余内容
4. 保证逻辑连贯
5. 使用 Markdown 格式，适当使用标题层级"""
    
    result = await llm.ainvoke(prompt)
    
    # 写入记忆
    await memory_system.store_execution(
        session_id=state["session_id"],
        task_id=tree.goal_id,
        result=result,
    )
    
    return {
        "final_response": result,
        "phase": "done",
    }
```

### 4.10 Tool Orchestration (工具编排)

```python
class ToolOrchestrator:
    """智能工具选择和编排"""
    
    def __init__(self):
        self.registry: dict[str, StructuredTool] = {}
        self._register_defaults()
    
    def _register_defaults(self):
        """注册默认工具集 (复用 RxyCode 的 24 个工具)"""
        from .tools import (
            read_tool, write_tool, edit_tool, bash_tool,
            grep_tool, glob_tool, ls_tool, view_tool,
            webfetch_tool, websearch_tool, git_tool,
            datetime_tool, memory_tool, vision_tool,
        )
        for t in [read_tool, write_tool, edit_tool, bash_tool,
                  grep_tool, glob_tool, ls_tool, view_tool,
                  webfetch_tool, websearch_tool, git_tool,
                  datetime_tool, memory_tool, vision_tool]:
            self.registry[t.name] = t
    
    def select_tools(self, hints: list[str]) -> list[StructuredTool]:
        """根据 hints 选择相关工具"""
        if not hints:
            return list(self.registry.values())
        
        selected = []
        for hint in hints:
            hint_lower = hint.lower()
            for name, tool in self.registry.items():
                if hint_lower in name.lower() or hint_lower in tool.description.lower():
                    selected.append(tool)
        
        return selected if selected else list(self.registry.values())
```

---

## 五、项目目录结构

```
rxycode-v2/
├── pyproject.toml
├── requirements.txt
├── README.md
│
├── rxycode/
│   ├── __init__.py
│   ├── __main__.py              # CLI 入口
│   │
│   ├── core/                    # 核心架构
│   │   ├── __init__.py
│   │   ├── state.py             # AgentState, TaskNode, TaskTree
│   │   ├── graph.py             # LangGraph 主图定义
│   │   └── config.py            # 配置管理
│   │
│   ├── planning/                # 规划层
│   │   ├── __init__.py
│   │   ├── goal_planner.py      # GoalPlanner
│   │   └── decomposer.py        # HierarchicalDecomposer
│   │
│   ├── execution/               # 执行层
│   │   ├── __init__.py
│   │   ├── executor.py          # 单步执行器
│   │   ├── scheduler.py         # TaskScheduler 工具类 (被 graph.py 路由函数调用)
│   │   └── tool_orchestrator.py # 工具编排
│   │
│   ├── validation/              # 校验层
│   │   ├── __init__.py
│   │   ├── validator.py         # 结果校验器
│   │   └── re_planner.py        # 二次拆解
│   │
│   ├── memory/                  # 记忆系统
│   │   ├── __init__.py
│   │   ├── manager.py           # MemorySystem 统一接口
│   │   ├── short_term.py        # Redis 短期记忆
│   │   ├── long_term.py         # VectorDB 长期记忆
│   │   ├── structured.py        # SQLite 结构化存储
│   │   └── compressor.py        # 上下文压缩
│   │
│   ├── synthesis/               # 合成层
│   │   ├── __init__.py
│   │   └── synthesizer.py       # OutputSynthesizer
│   │
│   ├── recovery/                # 恢复层
│   │   ├── __init__.py
│   │   └── error_recovery.py    # ErrorRecovery
│   │
│   ├── tools/                   # 工具层 (复用 RxyCode)
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   ├── read.py
│   │   ├── write.py
│   │   ├── edit.py
│   │   ├── bash.py
│   │   ├── grep_tool.py
│   │   ├── glob_tool.py
│   │   ├── ls.py
│   │   ├── view.py
│   │   ├── webfetch.py
│   │   ├── websearch.py
│   │   ├── git_tool.py
│   │   ├── datetime_tool.py
│   │   ├── memory_tool.py
│   │   └── vision.py
│   │
│   ├── api/                     # FastAPI 层
│   │   ├── __init__.py
│   │   ├── server.py
│   │   ├── routes.py
│   │   └── models.py            # Pydantic 请求/响应模型
│   │
│   └── tui/                     # 终端 UI (复用 Ink TUI)
│       └── ...
│
├── tests/
│   ├── test_state.py
│   ├── test_graph.py
│   ├── test_planning/
│   ├── test_execution/
│   ├── test_validation/
│   ├── test_memory/
│   └── test_synthesis/
│
└── docs/
    └── plans/
        └── 2026-07-02-rxycode-v2-architecture.md  (本文档)
```

---

## 六、依赖关系

```toml
[project]
dependencies = [
    "langgraph>=0.2.0",
    "langchain>=0.3.0",
    "langchain-openai>=0.2.0",
    "langchain-core>=0.3.0",
    "fastapi>=0.109.0",
    "uvicorn>=0.27.0",
    "pydantic>=2.0.0",
    "redis>=5.0.0",
    "chromadb>=0.4.0",        # 或 qdrant-client
    "aiosqlite>=0.20.0",
    "tiktoken>=0.7.0",
    "httpx>=0.27.0",
    "rich>=13.0",
    "click>=8.0",
]
```

---

## 七、与 RxyCode v1 的对比

| 维度 | RxyCode v1 | RxyCode v2 |
|------|-----------|-----------|
| 编排框架 | 自定义 async 函数 | LangGraph StateGraph |
| 任务结构 | 扁平步骤列表 | 分层任务树 (父子嵌套) |
| 规划 | 一次 LLM 调用生成步骤 | GoalPlanner + HierarchicalDecomposer |
| 执行 | 顺序遍历步骤 | DAG 调度 via conditional_edges (并行 + 串行) |
| 校验 | 简单 VERIFIED/UNVERIFIED | 三维度评分 (完整/相关/格式) |
| 失败处理 | 简单 retry hint | 二次分层拆解 (核心创新) |
| 记忆 | deque + 文件 | Redis + VectorDB + SQLite 混合 |
| 上下文 | 简单截断 | 三级压缩 (热/温/冷区) |
| 输出 | LLM 直接生成 | OutputSynthesizer 结构化聚合 |
| 接口 | CLI only | CLI + FastAPI |
| 状态管理 | 内存变量 | Redis 持久化 |

---

## 八、实施阶段

### Phase 1: 基础设施 (Day 1-2)
- [ ] 项目骨架搭建 (pyproject.toml, 目录结构)
- [ ] core/state.py - TaskNode, TaskTree 数据结构
- [ ] core/config.py - 配置管理
- [ ] tests/test_state.py

### Phase 2: 记忆系统 (Day 3-4)
- [ ] memory/manager.py - MemorySystem 统一接口
- [ ] memory/short_term.py - Redis 实现
- [ ] memory/long_term.py - ChromaDB 实现
- [ ] memory/structured.py - SQLite 实现
- [ ] memory/compressor.py - 上下文压缩
- [ ] tests/test_memory/

### Phase 3: 规划层 (Day 5-6)
- [ ] planning/goal_planner.py
- [ ] planning/decomposer.py
- [ ] tests/test_planning/

### Phase 4: 执行层 (Day 7-8)
- [ ] execution/scheduler.py - DAG 调度
- [ ] execution/executor.py - 单步执行器
- [ ] execution/tool_orchestrator.py
- [ ] tests/test_execution/

### Phase 5: 校验层 (Day 9-10)
- [ ] validation/validator.py
- [ ] validation/re_planner.py
- [ ] tests/test_validation/

### Phase 6: 合成层 (Day 11)
- [ ] synthesis/synthesizer.py
- [ ] tests/test_synthesis/

### Phase 7: 主图集成 (Day 12-13)
- [ ] core/graph.py - LangGraph 主图
- [ ] 集成测试
- [ ] recovery/error_recovery.py

### Phase 8: API + TUI (Day 14-15)
- [ ] api/server.py + routes.py
- [ ] tui/ 集成
- [ ] 端到端测试

---

## 九、变更记录

### 2026-07-02 v1.1 (调度优化)
1. **调度逻辑从 node 改为 conditional_edges**: `scheduler_node` 移除，调度决策内嵌到 `route_next()` 路由函数中。减少一次状态传递开销，调度是纯确定性逻辑不需要 LLM。
2. **依赖匹配用 ID 而不是 title**: `decomposer` 输出改为 `depends_on_index` (同批次索引)，在创建子节点后通过索引解析为 UUID。避免 title 重复/模糊匹配问题。
3. **CANCELLED 级联取消**: `get_ready_tasks()` 中，当依赖节点为 CANCELLED 时，当前任务自动标记 CANCELLED。`route_after_validator` 中超过重试次数的任务标记 CANCELLED 后继续调度其他任务。

### 2026-07-04 v1.2 (记忆系统 + 压缩器 + 智能路由)
1. **三级上下文压缩器 (Codex-style)**: 新增 `memory/compressor.py`，实现三级压缩：
   - Tier 1: 无损截断 (零 LLM) — 工具输出中段截断、助手旧回复精简
   - Tier 2: 规则精简 (零 LLM) — 保护区 (20k token) + 占位符替换
   - Tier 3: LLM 增量摘要 — 只总结新增 delta，不重复总结全部历史
   - Token 用 tiktoken (cl100k_base) 计数，不用 len(str)
2. **三态记忆写入策略**: 
   - Executor 不再写入记忆 (只存 task.result)
   - Validator PASSED 后才写入对话记忆 (memory.store_execution)
   - FAILED/ERROR 写入 error log (memory.log_error)，不污染对话上下文
   - 错误日志: `~/.rxycode/memory/sessions/<id>/errors.log`
3. **智能查询路由 (_is_simple_query)**: 
   - 修复英文 pattern 大小写问题 (CI/CD → ci/cd)
   - 新增中文关键词匹配 (分步/重构/搭建/创建 + 整个/全部/完整)
   - 简单查询走快速单次 LLM 路径，复杂任务走完整 LangGraph 管线
4. **前端命令补全**: 新增 7 条斜杠命令到 AVAILABLE_COMMANDS:
   - `/find-skill`, `/addskill`, `/list-skills`, `/remove-skill`
   - `/addmcp`, `/list-mcp`, `/remove-mcp`
5. **版本号更新**: 从 v0.3.x 升级到 v1.0.0 (11 处)
