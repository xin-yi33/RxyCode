# Phase B · 多 Agent 编排（Multi-Agent Orchestration）

> **在整条路线中的位置**：[`2026-07-31-EXECUTION-PLAN.md`](./2026-07-31-EXECUTION-PLAN.md) 的后继扩展，编号 Phase B。
> **前置条件**：主计划 Phase 0/1/2 + [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) **全部完成**。原因见 §0.3，这条前置比 Phase A 的更硬。
> **后继**：[`PHASE-C-MULTIMODAL-AGENT-COLLABORATION.md`](./PHASE-C-MULTIMODAL-AGENT-COLLABORATION.md)
>
> **一句话目标**：从"单个 AgentV2 + 图内任务并行"，变成"多个角色化 Agent，各自有独立的模型、工具集、记忆域，通过显式协议协作"。
>
> **执行模型**：Composer 2.5 为主力，Grok / Sonnet 5 辅助。分工见 §0.2。
> **基线日期**：2026-07-31　**预计工时**：6 周（1 名后端 + 0.5 名前端）
>
> ⚠️ **这是三个 Phase 里风险最高的一个。** 它不是加功能，是拆地基——要打破三组进程级全局单例。**每一张卡都必须能独立回滚。**

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | Composer 2.5 执行协议、分工、为什么前置这么硬 |
| [§1 现状真相](#1-现状真相实测证据) | 现在的"子代理"到底是什么，附 file:line |
| [§2 目标架构](#2-目标架构) | AgentSpec / AgentRuntime / 委派协议 |
| [§3 任务卡 B1–B11](#3-任务卡) | 逐个执行 |
| [§4 出口检查](#4-phase-b-出口检查) | 怎么算做完 |
| [§5 扩展手册](#5-扩展手册加一个新-agent-角色) | 以后加新角色怎么做 |

---

## §0 执行手册（必读）

### 0.1 Composer 2.5 专用执行协议

与 Phase A 相同的 7 步（LOCATE → READ → WRITE → LINT → TEST → CHECK → COMMIT），但**多两条 Phase B 专属要求**：

```
8. ISOLATE  每张卡做完，跑一次「隔离性测试」：
            python -m pytest tests/test_agents/test_isolation.py -q
            （B5 建立之后每张卡都要跑）

9. BASELINE 每张卡做完，跑一次评测基线比对：
            python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**为什么 Phase B 要额外这两步**：拆全局单例最典型的 bug 是"看起来能跑，但两个 Agent 悄悄共享了状态"。这种 bug 不会让测试变红，只会让行为变怪。隔离性测试就是专门抓它的。

### 0.2 三个模型的分工

| 模型 | 干什么 | 不要干什么 |
|---|---|---|
| **Composer 2.5** | 按任务卡实现、多文件同步改写（拆单例会涉及十几个文件）、补测试 | 决定要不要偏离本文档的架构 |
| **Grok** | 调研 LangGraph 的 `Send` API / subgraph 用法、其它开源项目（OpenHands、AutoGen、CrewAI）的多 Agent 协议设计取舍 | 直接改代码 |
| **Sonnet 5** | **重点审查 B2/B3 的 diff**（拆单例最容易漏改）、写文档（B11） | 长任务连续实现 |

**B2 强烈建议走"Composer 实现 → Sonnet 5 审查 → Composer 修"的完整回路**，因为它一次要改十几个文件。

### 0.3 为什么前置条件这么硬

| 前置 | 为什么绕不过 |
|---|---|
| 主计划 Phase 0 | 没有 lint 和 CI 矩阵，拆单例这种大范围改动的错误无法被自动发现 |
| 主计划 Phase 1 | 每张卡都要求"评测无回归"。没有可信基线，你无法证明拆单例没把行为改坏 |
| **主计划 Phase 2** | **最关键**。多 Agent 需要 (a) `core/session.py` 的 Session 抽象作为 Agent 的宿主，(b) `protocol/` 的类型化消息作为 Agent 间通信的载体。**跳过 Phase 2 直接做 Phase B，你会在 `agent_v2.py` 这个 3704 行的 God Object 里手工造一套 ad-hoc 通信机制，六个月后再推倒重来** |
| **Phase A** | 多 Agent 的核心卖点之一是"不同角色用不同模型"。没有 `ModelCapabilities`，你没法判断某个角色的模型是否支持 function calling，编排会在运行时随机炸 |

**自检命令**（四条都必须满足才能开始）：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .                              # Phase 0
Test-Path evals\baselines\latest-agent.json         # Phase 1 → True
Test-Path core\session.py, protocol\schema.json     # Phase 2 → True True
Test-Path core\providers\__init__.py                # Phase A → True
```

### 0.4 硬性规则

| # | 规则 | 原因 |
|---|---|---|
| MB1 | **单 Agent 路径的行为必须完全不变。** 多 Agent 是新增能力，不是替换。用户不开多 Agent 时，走的应该是与今天逐字节一致的路径 | 零回归 |
| MB2 | **不要在拆单例的同时改业务逻辑。** B2 是纯粹的"全局变量 → 依赖注入"，一行业务逻辑都不要动 | 否则 diff 无法 review |
| MB3 | **每个 Agent 的记忆域默认隔离。** 共享必须是显式的（通过黑板或委派返回值），不能是"碰巧用了同一个 session_id" | 现在的默认 `session_id="latest"` 就是这个坑 |
| MB4 | **不要用 LangGraph 的 `Send` API 造动态 Agent 生成**，除非 Grok 调研后明确证明它比显式委派更好。Send 的调试体验很差 | 可维护性 |
| MB5 | **不要让 Agent 之间直接互相 `await`。** 所有跨 Agent 调用走委派协议，有超时、有取消、有 trace | 否则会死锁 |
| MB6 | 一次一张卡，一张卡一个 commit，每张卡都能独立 revert | 风险控制 |

---

## §1 现状真相（实测证据）

**先说结论：现在的"多 Agent"是不存在的。** 代码里有四处遗留物在制造"已经有了"的错觉，实际上一处都不通。

### 1.1 `_run_with_subagents` 直接抛异常

```2905:2909:core/agent_v2.py
    async def _run_with_subagents(self, user_input: str) -> str:
        """使用子代理并行执行任务。"""
        raise RuntimeError(
            "legacy sub-agent execution is disabled; use the validated TaskTree graph"
        )
```

全仓库只有**定义处**出现这个名字，没有任何调用点。`_run_impl` 里有一段注释写着 "Sub-agent path"（约 `:3375-3382`），但实际从不进入。

### 1.2 `_should_use_subagents` 只是设了个标志位

```2882:2903:core/agent_v2.py
    def _should_use_subagents(self, user_input: str) -> bool:
        text_lower = user_input.lower()
        multi_task_patterns = [
            r"同时|并行|一起|分别|各自",
            r"at the same time|in parallel|simultaneously",
            r"多个|多个文件|多个任务",
            r"批量|batch",
        ]
        for pattern in multi_task_patterns:
            if re.search(pattern, text_lower):
                return True
        return False
```

返回 True 之后，唯一的效果是往 graph state 里写 `parallel_requested: True`（`core/agent_v2.py:3500`、compose 路径 `:2973`）。这是主计划 §1.5 说的"25 处关键词路由"中的一处。

### 1.3 `SubAgentV2` 是个空壳，零调用点

```3707:3715:core/agent_v2.py
class SubAgentV2:
    """Sub-agent for $ prefix commands (compatibility with old SubAgent)."""
    def __init__(self, parent: AgentV2, task: str):
        self._parent = parent
        self._task = task
    async def run(self) -> str:
        return await self._parent.run(self._task)
```

它只是把任务原样转发给父 Agent。全仓库无 `SubAgentV2(` 实例化。`$` 前缀命令只存在于 i18n 字符串（`utils/i18n.py:21,137`），没有对应的命令处理逻辑。

### 1.4 `agent_tool` 存在但没注册

`tools/agent_tool.py:15-23` 的 `run_agent_async` 会 `new` 一个全新 `AgentV2` 跑 compose 模式。但我实测 grep 过：

```
Select-String -Path core\agent_v2.py -Pattern "agent_tool|run_agent_async"
→ 无输出
```

`_register_tools()`（约 `:1479-1563`）里没有它。**LLM 根本调不到这个工具。**

### 1.5 `subagent_decompose` 模板定义了但没人用

| 项 | 状态 |
|---|---|
| 模板定义 | `core/prompts/templates.py:236-259` |
| 注册进 stage 列表 | `core/prompts/templates.py:340` |
| few-shot 示例 | `core/prompts/few_shot.py:90-104` |
| **生产代码调用** | **零**（实测 grep `core/` `execution/` `planning/` 均无） |

实际的任务分解由 `HierarchicalDecomposer`（`core/graph.py:330-349` → `planning/decomposer.py`）做，用的是 `decomposer` 模板。

### 1.6 现在真正在跑的是什么

**单个 AgentV2 + 一条静态 LangGraph 管线 + 图内任务级并行。**

```1171:1189:core/graph.py
    if ready:
        exec_cfg = cfg.get("execution", {})
        parallel_enabled = bool(
            exec_cfg.get("parallel_enabled", False)
            or state.get("parallel_requested", False)
        )
        max_parallel = max(1, int(exec_cfg.get("max_parallel", 3) or 3))
        if parallel_enabled and len(ready) > 1:
            dispatched = ready[:max_parallel]
```

并发实现在 `core/graph.py:613-626`（`asyncio.gather` + `Semaphore`）。**并行的是同一个 Agent 的 TaskTree 叶节点**，它们共享同一份 `_tool_orchestrator`、`_memory`、`session_id`。这不是多 Agent。

「Compose 模式」（`agent_v2.py:2911-3006`）也是同一个 Agent 的两个顺序阶段（plan prompt → build），不是两个 Agent。

### 1.7 三组全局单例——这才是真正的障碍

要让"专家 A 只有 read/grep，专家 B 能写文件"，必须能给每个 Agent 配独立的工具集和状态。以下三组进程级单例挡在路上：

| 单例 | 位置 | 后果 |
|---|---|---|
| `ToolRegistry` | `tools/registry.py:88` `registry = ToolRegistry()` | 工具表全进程共享，无法 per-agent 限定 |
| 两级缓存 | `cache/precise_cache.py:227-228`、`cache/semantic_cache.py:267-268` | 两个 Agent 会互相命中对方的缓存 |
| 熔断器 | `recovery/circuit_breaker.py:8-10`（注释明说 "every LLM entry point ... shares one breaker per process"） | 一个 Agent 触发熔断会连坐所有 Agent |

**已经是 per-instance 的**（好消息，不用改）：

| 资源 | 位置 |
|---|---|
| `ToolOrchestrator` | `core/agent_v2.py:797` |
| 编译后的 graph | `core/agent_v2.py:786-787` |
| `ModelRouter` | `core/agent_v2.py:687-701` |
| `MemoryManager` | `core/agent_v2.py:720`（但默认 `session_id="latest"`，见 `:675`，实际仍共享） |

另外 `api_server.py:577-578` 是 `_state["agent"] = Agent()` 的单例持有，Phase 2 的 Session 层应该已经改掉了；如果没有，B5 要处理。

### 1.8 已有的、可以复用的半成品

不要推倒重来，这些是好的：

| 现有能力 | 位置 | 在 Phase B 里的角色 |
|---|---|---|
| `ModelRole` 枚举 + `ModelRouter` | `core/governance.py:370-374`、`:409-487` | "不同角色用不同模型"已经有 60%，扩展成 per-agent 即可 |
| `PromptRegistry` 的 stage 维度 | `core/prompts/registry.py` | stage 已经是一种角色抽象，Agent 角色可以复用同一套注册机制 |
| `ToolOrchestrator.select_tools(hints)` | `execution/tool_orchestrator.py:324-358` | 任务级工具筛选已有，改造成 agent 级作用域 |
| `HookRegistry` | `core/agent_v2.py:703-710`、`core/graph.py:63-75` | 多 Agent 的生命周期观测挂点 |

---

## §2 目标架构

### 2.1 结构图

```
                    protocol/agents.py（Phase 2 的 protocol 包内）
                    ┌────────────────────────────────────┐
                    │  AgentSpec        角色定义（静态）   │
                    │  DelegateRequest  委派请求           │
                    │  DelegateResult   委派结果           │
                    │  BlackboardEntry  共享黑板条目       │
                    └────────────────┬───────────────────┘
                                     │
                    ┌────────────────▼───────────────────┐
                    │  core/agents/orchestrator.py        │
                    │   Orchestrator                      │
                    │    - 持有 AgentRuntime 池           │
                    │    - 路由委派请求                    │
                    │    - 管理黑板                        │
                    │    - 超时 / 取消 / 循环检测          │
                    └────────────────┬───────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │ AgentRuntime     │   │ AgentRuntime     │   │ AgentRuntime     │
   │  role=architect  │   │  role=coder      │   │  role=reviewer   │
   │  model=opus      │   │  model=deepseek  │   │  model=sonnet    │
   │  tools=[read,    │   │  tools=[read,    │   │  tools=[read,    │
   │         grep]    │   │    write, shell] │   │         grep]    │
   │  memory=ns:arch  │   │  memory=ns:code  │   │  memory=ns:rev   │
   │  cache=ns:arch   │   │  cache=ns:code   │   │  cache=ns:rev    │
   │  breaker=own     │   │  breaker=own     │   │  breaker=own     │
   └────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
            └──────────────────────┼──────────────────────┘
                                   ▼
                       core/session.py :: Session
                       （Phase 2 建立，是 Agent 的宿主）
                                   ▼
                       现有 graph / tools / memory / safety
```

### 2.2 四条不可违反的设计约束

| # | 约束 | 原因 |
|---|---|---|
| DB1 | **单 Agent 是"只有一个 AgentRuntime 的 Orchestrator"**，不是另一条代码路径 | 两条路径会立刻漂移，一年后单 Agent 路径就没人维护了 |
| DB2 | **Agent 之间只能通过 `DelegateRequest` / 黑板通信**，不能直接持有对方引用 | 直接引用 = 死锁 + 无法 trace + 无法超时 |
| DB3 | **每个 AgentRuntime 拥有独立的 memory namespace、cache namespace、circuit breaker**。共享必须显式声明 | §1.7 的三组单例就是反面教材 |
| DB4 | **委派深度有硬上限，默认 3 层，且必须检测环** | 不然一个 "coder 委派给 reviewer，reviewer 委派给 coder" 就能烧光你的 API 额度 |

### 2.3 文件布局（**不要改**）

```
protocol/
  agents.py                    # AgentSpec / DelegateRequest / DelegateResult / BlackboardEntry
core/
  agents/
    __init__.py                # 公开 API
    spec.py                    # AgentSpec 解析与校验
    runtime.py                 # AgentRuntime
    orchestrator.py            # Orchestrator
    blackboard.py              # 共享黑板
    roles/
      __init__.py              # 内置角色注册
      builtin.yaml             # 内置角色定义（architect/coder/reviewer/researcher）
tests/
  test_agents/
    __init__.py
    test_spec.py
    test_isolation.py          # 隔离性测试 —— B2 之后每张卡都要跑
    test_orchestrator.py
    test_delegation.py
    test_blackboard.py
```

---

## §3 任务卡

### B1 · 清理多 Agent 死代码

`P0` / 4h / 无依赖（可与 Phase A 并行做）

**背景**
§1.1–1.5 的五处遗留物在持续误导人和 AI 代理，让人以为多 Agent 已经存在。`docs/modules/core.md:36,43` 甚至还在描述这些不存在的行为。**在开始造真的之前，先把假的清干净**——否则你会在半途分不清哪些是遗留、哪些是自己新写的。

**涉及文件**

| 文件 | 锚点 | 处理 |
|---|---|---|
| `core/agent_v2.py` | `async def _run_with_subagents` | 删除整个方法 |
| `core/agent_v2.py` | `def _should_use_subagents` | **保留**，但改名 + 改注释（见步骤 2） |
| `core/agent_v2.py` | `class SubAgentV2` | 删除整个类 |
| `core/agent_v2.py` | `# Sub-agent path` 附近注释 | 删除误导性注释 |
| `tools/agent_tool.py` | 整个文件 | 删除（Phase B 会用全新设计取代） |
| `core/prompts/templates.py` | `SUBAGENT_DECOMPOSE_TEMPLATE` | **保留**，加注释说明现状（见步骤 4） |
| `docs/modules/core.md` | `SubAgentV2`、`_run_with_subagents` | 改成实际行为 |

**操作步骤**

1. 删除 `_run_with_subagents` 和 `SubAgentV2`。删之前**再确认一次**没有调用点：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
Select-String -Path *.py,core\*.py,tools\*.py,execution\*.py,tests\*.py,api_server.py -Pattern "_run_with_subagents|SubAgentV2" -Recurse |
  ForEach-Object { "$($_.Path -replace '.*RxyCode1_1_0\\',''):$($_.LineNumber): $($_.Line.Trim())" }
```

预期只有定义处 + 测试里的"断言它被禁用"那几条。测试里的断言也一并删（因为被断言的东西没了）。

2. `_should_use_subagents` **不要删**——它设置的 `parallel_requested` 标志是当前并行执行的真实入口。但名字是错的（它跟子代理毫无关系）。改名为 `_should_request_parallel_execution` 并改注释：

```python
    def _should_request_parallel_execution(self, user_input: str) -> bool:
        """启发式判断用户是否希望并行执行多个任务。

        命名历史：这个方法原名 _should_use_subagents，但它与子代理无关——
        它唯一的作用是往 graph state 写 parallel_requested 标志，触发
        core/graph.py:1171 的 TaskTree 叶节点并行。真正的多 Agent 编排见
        core/agents/（Phase B）。

        这是关键词路由（主计划 P6 要消除的 25 处之一），对非中英文输入无效。
        """
```

**用 Grep 找出所有调用点一并改名**（约 `:3500`、`:2973` 附近）。

3. 删除 `tools/agent_tool.py`。它从未被注册，删除没有任何运行时影响：

```powershell
git rm tools/agent_tool.py
Select-String -Path *.py,core\*.py,tools\*.py,tests\*.py -Pattern "agent_tool" -Recurse   # 期望：无输出
```

4. `SUBAGENT_DECOMPOSE_TEMPLATE` **保留**（Phase B 的 B8 会真正用上它），但加注释说清现状：

```python
# 状态：已定义、已注册，但生产代码尚未调用。
# 实际的任务分解走 decomposer 模板（planning/decomposer.py）。
# 本模板预留给 Phase B 的 Orchestrator 做 agent 级任务拆分，见
# docs/plans/opus5-plan/PHASE-B-MULTI-AGENT-ORCHESTRATION.md B8。
SUBAGENT_DECOMPOSE_TEMPLATE = """<ROLE>
```

5. 修正 `docs/modules/core.md`。用 Grep 找到描述 `SubAgentV2` 和 sub-agent delegation 的段落（约 `:36`、`:43`），改写为实际行为：

```markdown
### 并行执行

RxyCode 目前是**单 Agent + 图内任务并行**，不是多 Agent 架构。

用户输入命中并行关键词时（`_should_request_parallel_execution`），会往
graph state 写 `parallel_requested`；`core/graph.py:1171` 的 `route_next`
据此把多个 ready 的 TaskTree 叶节点一次性派发，由 `core/graph.py:613` 的
`asyncio.gather` + `Semaphore` 并发执行。

这些并行任务**共享同一个 Agent 的** ToolOrchestrator、MemoryManager 和
session_id，因此不是独立的 Agent。真正的多 Agent 编排见 Phase B。
```

6. 同步更新 `AGENTS.md` 里 "Multi-task -> Sub-agent delegation" 这一行（用 Grep 找）。

**验收命令**

```powershell
Select-String -Path *.py,core\*.py,tools\*.py,tests\*.py,api_server.py -Pattern "_run_with_subagents|SubAgentV2|agent_tool" -Recurse
# 期望：无输出
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 三处死代码已删，grep 无残留
- [ ] `_should_use_subagents` 已改名，所有调用点同步
- [ ] `SUBAGENT_DECOMPOSE_TEMPLATE` 保留且有状态注释
- [ ] `docs/modules/core.md` 和 `AGENTS.md` 描述与代码一致
- [ ] 全量测试绿，evals 无回归

**回滚**：`git revert <commit>`

**常见坑**
- 删 `SubAgentV2` 时注意 `__all__` 或 `__init__.py` 里可能有导出，一并删。
- 有些测试是"断言 `_run_with_subagents` 会抛异常"。那些测试随方法一起删，**不要**为了让它们过而保留死代码。

**Commit**
```
chore(agents): remove dead multi-agent scaffolding

_run_with_subagents raised unconditionally, SubAgentV2 only forwarded to
its parent and had zero call sites, and agent_tool was never registered
so the LLM could not reach it. All three made docs and readers believe
multi-agent support existed. Renames _should_use_subagents to reflect
what it actually does (set a parallel-execution flag).
```

---

### B2 · 拆掉三组全局单例

`P0` / 2 周 / 依赖 B1、主计划 Phase 2

**背景**
§1.7 的三组进程级单例是多 Agent 的真正障碍。这一卡**纯粹是"全局变量 → 依赖注入"，一行业务逻辑都不改**（规则 MB2）。

**这是 Phase B 最大的一张卡，涉及十几个文件。强烈建议拆成 3 个 commit（每组单例一个），并让 Sonnet 5 逐个审查。**

**涉及文件**

| 组 | 单例定义 | 使用点（用 Grep 找全） |
|---|---|---|
| 1 | `tools/registry.py:88` `registry = ToolRegistry()` | `core/agent_v2.py:1481` 等，grep `from tools.registry import registry` / `registry.register` / `registry.get` |
| 2 | `cache/precise_cache.py:227-228`、`cache/semantic_cache.py:267-268` | grep `precise_cache\.` / `semantic_cache\.` |
| 3 | `recovery/circuit_breaker.py:8-10` | grep `circuit_breaker` |

**操作步骤**

#### 第 1 组：ToolRegistry

1. **先摸清使用面**：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
Select-String -Path *.py,core\*.py,tools\*.py,execution\*.py,api_server.py,tests\*.py -Pattern "from.*tools\.registry import|tools\.registry\.|^from \.registry import|\bregistry\.(register|get|get_descriptions|all)\b" -Recurse |
  ForEach-Object { "$($_.Path -replace '.*RxyCode1_1_0\\',''):$($_.LineNumber): $($_.Line.Trim())" }
```

**把结果存成一张表**，这是你的改造清单。改完要逐条勾掉。

2. `tools/registry.py` 保留全局实例但标为"默认注册表"，同时暴露构造能力：

```python
class ToolRegistry:
    ...  # 类本身不动


#: 进程级默认注册表。
#:
#: 历史上这是唯一的注册表，所有工具都注册到这里，因此无法给不同 Agent 配
#: 不同工具集。Phase B 引入了 per-agent 注册表；本实例保留为默认值，
#: 供单 Agent 路径和未显式传注册表的调用方使用。
#:
#: 新代码请通过依赖注入接收 ToolRegistry，不要直接 import 这个全局。
default_registry = ToolRegistry()

#: 向后兼容别名。新代码不要用。
registry = default_registry
```

3. 让 `ToolOrchestrator` 接受注册表参数。找到 `execution/tool_orchestrator.py` 的 `__init__`，加：

```python
    def __init__(self, ..., tool_registry: "ToolRegistry | None" = None):
        from tools.registry import default_registry
        self._registry = tool_registry or default_registry
```

然后把该文件内所有直接用全局 `registry` 的地方改成 `self._registry`。

4. `AgentV2.__init__`（约 `:797`）构造 `ToolOrchestrator` 时可以传注册表；**Phase B 阶段先传 `None`（走默认）**，B4 才真正用上 per-agent 注册表。

5. **加隔离测试**（这一步不能省）—— 新建 `tests/test_agents/__init__.py` 和 `tests/test_agents/test_isolation.py`：

```python
"""Agent 间状态隔离测试。

这些测试是 Phase B 的安全网。拆全局单例时最典型的 bug 是"看起来能跑，但
两个 Agent 悄悄共享了状态"——它不会让别的测试变红，只会让行为变怪。
每张 Phase B 任务卡做完都要跑这个文件。
"""
from tools.registry import ToolRegistry


def test_two_registries_do_not_share_tools():
    a = ToolRegistry()
    b = ToolRegistry()

    from langchain_core.tools import StructuredTool
    dummy = StructuredTool.from_function(
        func=lambda: "ok", name="only_in_a", description="test tool",
    )
    a.register(dummy)

    assert a.get("only_in_a") is not None
    assert b.get("only_in_a") is None, (
        "ToolRegistry instances must not share state — per-agent tool "
        "scoping depends on this"
    )


def test_default_registry_is_not_polluted_by_new_instances():
    from tools.registry import default_registry
    before = set(default_registry.list_names())
    scratch = ToolRegistry()
    from langchain_core.tools import StructuredTool
    scratch.register(StructuredTool.from_function(
        func=lambda: "ok", name="scratch_only", description="test tool",
    ))
    assert set(default_registry.list_names()) == before
```

> 如果 `ToolRegistry` 没有 `list_names()`，用 Grep 看它实际有什么方法，用等价的。

#### 第 2 组：两级缓存

6. 同样的手法。`cache/precise_cache.py` 和 `cache/semantic_cache.py` 的全局实例改名为 `default_precise_cache` / `default_semantic_cache`，保留旧名作别名。

7. **关键**：缓存已经有 namespace 概念（`core/agent_v2.py:2098-2104` 的 `_application_cache_namespace()` 按模型+凭证分）。Phase B 需要**在 namespace 里加 agent 维度**。改造 `_application_cache_namespace`：

```python
    def _application_cache_namespace(self) -> str:
        """缓存命名空间。

        改造前只按 (模型, 凭证) 分，因此两个 Agent 用同一模型时会互相命中
        对方的缓存。多 Agent 下不同角色的 system prompt 和工具集不同，
        缓存必须按 agent 隔离。
        """
        base = ...  # 原有逻辑保持不变
        agent_ns = getattr(self, "_agent_namespace", None)
        return f"{base}|{agent_ns}" if agent_ns else base
```

`self._agent_namespace` 在 `__init__` 里默认设为 `None`（单 Agent 路径行为不变），B3 的 AgentRuntime 会给它赋值。

8. 隔离测试加：

```python
def test_cache_namespaces_isolate_agents():
    from cache.precise_cache import PreciseCache
    c = PreciseCache()
    c.set("sys", "query", "answer-A", namespace="agent:architect")
    assert c.get("sys", "query", namespace="agent:coder") is None
    assert c.get("sys", "query", namespace="agent:architect") == "answer-A"
```

> 方法名以实际实现为准，用 Read 确认 `PreciseCache` 的 `get`/`set` 签名。

#### 第 3 组：熔断器

9. `recovery/circuit_breaker.py:8-10` 的注释明说"每进程共享一个"。改造为按 key 分桶：

```python
"""LLM 调用熔断器。

改造前是进程级单例，所以一个 Agent 触发熔断会连坐所有 Agent。现在按
breaker key 分桶：单 Agent 路径用默认 key（行为不变），多 Agent 下每个
AgentRuntime 用自己的 key。
"""

_BREAKERS: dict[str, CircuitBreaker] = {}


def get_breaker(key: str = "default") -> CircuitBreaker:
    """取（或创建）指定 key 的熔断器。"""
    breaker = _BREAKERS.get(key)
    if breaker is None:
        breaker = CircuitBreaker()
        _BREAKERS[key] = breaker
    return breaker


def reset_all_breakers() -> None:
    """仅供测试使用。"""
    _BREAKERS.clear()
```

10. `UsageTrackingLLM`（`core/agent_v2.py:333` 起）里用熔断器的地方改为 `get_breaker(self._breaker_key)`，`_breaker_key` 默认 `"default"`。

11. 隔离测试加：

```python
def test_breakers_are_isolated_by_key():
    from recovery.circuit_breaker import get_breaker, reset_all_breakers
    reset_all_breakers()
    a = get_breaker("agent:architect")
    b = get_breaker("agent:coder")
    assert a is not b
    assert get_breaker("agent:architect") is a   # 同 key 复用
```

**验收命令**

```powershell
python -m pytest tests/test_agents/test_isolation.py -q
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
# 第 1 步的改造清单，逐条确认已处理
```

**完成判据**
- [ ] 三组单例都改成"默认实例 + 可注入"，旧名保留为别名
- [ ] 第 1 步的使用点清单**逐条勾掉**（贴在 PR 描述里）
- [ ] `tests/test_agents/test_isolation.py` 全绿
- [ ] 全量测试通过数**与改动前一致**
- [ ] evals 零回归
- [ ] **没有任何业务逻辑改动**（Sonnet 5 审查时重点看这条）

**回滚**：分 3 个 commit，可以单独 revert 任意一组

**常见坑**
- **最容易漏的是 `from tools.registry import registry` 这种 import 后直接用的写法**，grep 时容易只搜到 `registry.` 而漏掉 import 行。第 1 步的正则已经覆盖了两种，但还是要人工看一遍清单。
- 改缓存 namespace 时，如果不小心改变了单 Agent 路径的 namespace 值，**已有的缓存会全部失效**。这不会让测试变红，但会让 evals 变慢（缓存全 miss）。所以第 7 步的 `if agent_ns else base` 是关键——单 Agent 下必须返回与原来**完全一样**的字符串。

**Commit**（分 3 个）
```
refactor(tools): make ToolRegistry injectable instead of a process global
refactor(cache): add agent dimension to cache namespaces
refactor(recovery): key circuit breakers instead of one per process
```

---

### B3 · AgentSpec：角色定义

`P0` / 1 周 / 依赖 B2、主计划 Phase 2（protocol 包）

**背景**
定义"一个 Agent 角色是什么"。这是纯数据结构 + 校验，没有运行时行为，所以风险低。

**涉及文件**
- 新建 `protocol/agents.py`（放进 Phase 2 建立的 `protocol/` 包）
- 新建 `core/agents/__init__.py`、`core/agents/spec.py`
- 新建 `tests/test_agents/test_spec.py`

**操作步骤**

1. `protocol/agents.py`：

```python
"""多 Agent 协议类型。

放在 protocol/ 包内是为了让这些类型能通过 protocol/schema.py 导出成
JSON Schema，进而生成 TypeScript 类型——Desktop 和 TUI 需要展示"现在是
哪个 Agent 在说话"、"谁委派给了谁"。

改动这里的任何字段都要遵守 protocol 的版本规则，见
docs/plans/opus5-plan/2026-07-31-EXECUTION-PLAN.md §9.4。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    """一个 Agent 角色的静态定义。

    Spec 是不可变的模板；运行时实例是 AgentRuntime。
    """

    #: 角色标识，全局唯一，用作 memory / cache / breaker 的 namespace 前缀
    role: str

    #: 人类可读名称，用于 UI 展示
    display_name: str

    #: 该角色使用的模型 id。None 表示跟随会话默认模型。
    model: str | None = None

    #: 允许使用的工具名。None 表示"全部工具"（等同当前单 Agent 行为）。
    #: 空列表表示"不能用任何工具"（纯推理角色）。
    tools: list[str] | None = None

    #: prompt 注册表的 stage 名。该角色的 role prompt 从这里取。
    prompt_stage: str

    #: 是否允许该角色发起委派。叶子角色应设为 False，防止委派环。
    can_delegate: bool = False

    #: 允许委派给哪些角色。can_delegate=True 时生效，空表示可委派给任意角色。
    delegate_to: list[str] = Field(default_factory=list)

    #: 记忆域。"private" = 独占 namespace；"shared" = 与会话共享。
    memory_scope: Literal["private", "shared"] = "private"

    #: 单次运行的墙钟超时（秒）。
    timeout_s: float = 300.0

    #: 该角色的额外配置，透传给 AgentRuntime。
    extra: dict[str, Any] = Field(default_factory=dict)


class DelegateRequest(BaseModel):
    """一个 Agent 请求另一个 Agent 完成子任务。"""

    method: Literal["agents/delegate"] = "agents/delegate"
    session_id: str
    #: 发起方角色
    from_role: str
    #: 目标角色
    to_role: str
    #: 任务描述
    task: str
    #: 当前委派深度，由 Orchestrator 维护，客户端不要填
    depth: int = 0
    #: 供目标 Agent 参考的黑板条目 key 列表
    context_keys: list[str] = Field(default_factory=list)


class DelegateResult(BaseModel):
    """委派的返回结果。"""

    request_id: str
    from_role: str
    to_role: str
    ok: bool
    answer: str = ""
    error: str = ""
    #: 目标 Agent 实际调用过的工具，用于审计和评测
    tools_used: list[str] = Field(default_factory=list)
    duration_s: float = 0.0


class BlackboardEntry(BaseModel):
    """共享黑板上的一条记录。

    黑板是 Agent 间**唯一**的隐式共享通道（DelegateRequest 是显式通道）。
    刻意做成 append-only + 带作者，方便追溯"这个结论是谁写的"。
    """

    key: str
    value: str
    author_role: str
    created_at: float


class AgentEvent(BaseModel):
    """Agent 生命周期通知，推给客户端用于 UI 展示。"""

    method: Literal["event/agent"] = "event/agent"
    session_id: str
    role: str
    phase: Literal["started", "delegated", "completed", "failed"]
    detail: str = ""
```

2. `core/agents/spec.py`：加载与校验。**校验规则是重点**：

```python
"""AgentSpec 的加载与校验。

校验规则的存在是为了在**配置时**就拦住会导致运行时死循环或额度烧光的
配置错误，而不是等到线上跑炸。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from protocol.agents import AgentSpec


class AgentSpecError(ValueError):
    """AgentSpec 配置非法。"""


#: 委派深度硬上限。见 PHASE-B 文档设计约束 DB4。
MAX_DELEGATE_DEPTH = 3


def load_specs(path: Path) -> dict[str, AgentSpec]:
    """从 YAML 加载角色定义并做全局校验。"""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs: dict[str, AgentSpec] = {}

    for entry in raw.get("agents", []):
        spec = AgentSpec(**entry)
        if spec.role in specs:
            raise AgentSpecError(f"duplicate role {spec.role!r}")
        specs[spec.role] = spec

    _validate_delegation_graph(specs)
    return specs


def _validate_delegation_graph(specs: dict[str, AgentSpec]) -> None:
    """静态检查委派图：目标存在、无环、深度可达上限内。"""
    for spec in specs.values():
        if not spec.can_delegate and spec.delegate_to:
            raise AgentSpecError(
                f"role {spec.role!r} has delegate_to but can_delegate is False"
            )
        for target in spec.delegate_to:
            if target not in specs:
                raise AgentSpecError(
                    f"role {spec.role!r} delegates to unknown role {target!r}"
                )

    cycle = _find_cycle(specs)
    if cycle:
        raise AgentSpecError(
            "delegation cycle detected: " + " -> ".join(cycle)
        )


def _find_cycle(specs: dict[str, AgentSpec]) -> list[str] | None:
    """DFS 找委派环。返回环上的角色序列，无环返回 None。"""
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(specs, WHITE)
    stack: list[str] = []

    def visit(role: str) -> list[str] | None:
        color[role] = GREY
        stack.append(role)
        for target in specs[role].delegate_to:
            if color[target] == GREY:
                return stack[stack.index(target):] + [target]
            if color[target] == WHITE:
                found = visit(target)
                if found:
                    return found
        stack.pop()
        color[role] = BLACK
        return None

    for role in specs:
        if color[role] == WHITE:
            found = visit(role)
            if found:
                return found
    return None
```

3. `tests/test_agents/test_spec.py` 必须覆盖：合法配置加载、重复 role、委派目标不存在、`can_delegate=False` 但有 `delegate_to`、**两角色互相委派的环**、**三角环**、自委派环。

**验收命令**

```powershell
python -m pytest tests/test_agents/test_spec.py -q
python -m ruff check protocol/agents.py core/agents
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
python -m pytest tests/test_protocol_schema.py -q
```

**完成判据**
- [ ] `protocol/agents.py` 的类型已进 `schema.json`
- [ ] 环检测测试覆盖自环、二元环、三元环
- [ ] `python -m pytest tests/test_agents/test_isolation.py -q` 仍绿
- [ ] 前端类型已重新生成（`cd frontend\protocol-client; bun run generate`），且 `git diff --exit-code` 干净

---

### B4 · AgentRuntime：per-agent 隔离运行时

`P0` / 1.5 周 / 依赖 B2 B3

**背景**
把 AgentSpec 变成能跑的东西。这一卡是 Phase B 的核心，它把 B2 拆出来的三组可注入资源真正用起来。

**涉及文件**
- 新建 `core/agents/runtime.py`
- 修改 `core/session.py`（Phase 2 建立的）
- 扩充 `tests/test_agents/test_isolation.py`

**操作步骤**

1. `core/agents/runtime.py` 的核心结构：

```python
"""AgentRuntime：一个角色的运行实例。

每个 runtime 拥有：
  - 独立的 ToolRegistry（只含 spec.tools 里声明的工具）
  - 独立的 cache namespace
  - 独立的 circuit breaker key
  - 独立的 memory namespace（memory_scope="private" 时）
  - 自己的 LLM（按 spec.model 解析，走 Phase A 的 provider 层）

设计约束（见 PHASE-B 文档 §2.2）：
  DB2 —— runtime 之间不持有对方引用，只通过 Orchestrator 通信
  DB3 —— 默认全隔离，共享必须显式声明
"""

class AgentRuntime:
    def __init__(self, spec: AgentSpec, *, session: "Session", ...):
        self._spec = spec
        self._namespace = f"agent:{spec.role}"

        # 1) 工具作用域：从默认注册表挑出允许的工具，装进独立注册表
        self._registry = self._build_scoped_registry(spec.tools)

        # 2) 缓存 / 熔断 / 记忆 namespace
        self._cache_namespace = self._namespace
        self._breaker_key = self._namespace
        self._memory_namespace = (
            f"{session.id}:{spec.role}" if spec.memory_scope == "private"
            else session.id
        )

        # 3) LLM：按 spec.model 解析，走 Phase A 的 provider 层
        self._llm, self._provider, self._capabilities = self._build_llm(spec)

    @staticmethod
    def _build_scoped_registry(tool_names: list[str] | None) -> ToolRegistry:
        """按角色声明构造独立注册表。

        None  → 复制默认注册表的全部工具（等同单 Agent 行为）
        []    → 空注册表（纯推理角色，不能碰工具）
        [...] → 只放声明的工具；声明了不存在的工具名要**报错**而不是静默忽略
        """
```

2. **`_build_scoped_registry` 的错误处理是重点**：如果 spec 里写了 `tools: [read_file, wrtie_file]`（拼错），必须在构造时抛异常，**不能静默忽略**。静默忽略的后果是"这个 agent 莫名其妙不会写文件"，极难排查。

3. 让 `Session`（Phase 2 建立）能持有多个 runtime。**单 Agent 路径 = 只有一个 role="default" 的 runtime**（约束 DB1）。

4. `tests/test_agents/test_isolation.py` 扩充到覆盖：

```python
def test_runtimes_have_separate_tool_registries():
    """architect 只有只读工具，coder 有写工具，互不可见。"""

def test_runtimes_have_separate_cache_namespaces():
    """同一个 prompt 在两个 runtime 下不会互相命中缓存。"""

def test_runtimes_have_separate_breakers():
    """architect 触发熔断不影响 coder。"""

def test_private_memory_scope_does_not_leak():
    """architect 写入的记忆，coder 读不到。"""

def test_shared_memory_scope_does_leak_intentionally():
    """memory_scope='shared' 时确实共享 —— 这是显式声明的行为。"""

def test_unknown_tool_name_in_spec_raises():
    """spec 里写了不存在的工具名必须报错，不能静默忽略。"""

def test_empty_tool_list_yields_empty_registry():
    """tools: [] 的纯推理角色确实拿不到任何工具。"""

def test_single_agent_path_is_byte_identical():
    """只有一个 default runtime 时，行为与 Phase B 之前一致。"""
```

**验收命令**

```powershell
python -m pytest tests/test_agents -q
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 8 个隔离测试全绿
- [ ] 单 Agent 路径 evals **零回归**（这是 DB1 的验证）
- [ ] spec 里的错误工具名会在构造时报错
- [ ] `AgentRuntime` 不持有任何其它 runtime 的引用（Sonnet 5 审查这条）

---

### B5 · Orchestrator 与委派协议

`P0` / 1.5 周 / 依赖 B4

**背景**
让 Agent 能互相委派。这一卡的风险点全在**失控保护**上：深度、环、超时、取消。

**操作步骤**

1. `core/agents/orchestrator.py` 的职责：
   - 持有 runtime 池（按 role 索引）
   - 接收 `DelegateRequest`，做四重校验后路由
   - 维护委派栈（用于环检测和 trace）
   - 发 `AgentEvent` 通知给客户端

2. **四重校验，缺一不可**：

```python
    async def delegate(self, req: DelegateRequest) -> DelegateResult:
        # 1) 发起方有权委派吗
        if not self._specs[req.from_role].can_delegate:
            return self._reject(req, "role is not allowed to delegate")

        # 2) 目标在白名单里吗
        allowed = self._specs[req.from_role].delegate_to
        if allowed and req.to_role not in allowed:
            return self._reject(req, f"{req.from_role} may not delegate to {req.to_role}")

        # 3) 深度没超吗
        if req.depth >= MAX_DELEGATE_DEPTH:
            return self._reject(req, f"delegation depth limit {MAX_DELEGATE_DEPTH} reached")

        # 4) 运行时环检测（静态检测在 B3 做过，但动态路径仍可能成环）
        if req.to_role in self._active_stack:
            return self._reject(
                req, "delegation cycle: " + " -> ".join(self._active_stack + [req.to_role])
            )
```

> **注意第 4 条**：B3 的静态检测查的是 spec 里声明的 `delegate_to` 图。但如果某个角色的 `delegate_to` 是空列表（表示"可委派给任意角色"），静态图就查不出环，必须靠运行时栈。

3. **超时与取消**：每次委派用 `asyncio.wait_for(..., timeout=spec.timeout_s)` 包住。超时后必须**真正取消**目标 runtime 的执行，不能只是放弃等待（否则孤儿任务会继续烧 token）。

4. **`_reject` 返回 `DelegateResult(ok=False, error=...)`，不抛异常。** 委派失败是正常业务情况，发起方 Agent 应该能读到错误信息并自己决定怎么办。

5. 单 Agent 路径：Orchestrator 里只有一个 role="default" 的 runtime，`delegate` 永远不会被调用。

6. 测试 `tests/test_agents/test_delegation.py` 必须覆盖：
   - 正常委派往返
   - 四重校验各自的拒绝路径
   - 深度到 3 层正常、第 4 层被拒
   - 运行时环（A→B→A）被拒
   - 超时后目标任务确实被取消（用一个会睡很久的 mock runtime 验证）
   - 委派失败时发起方收到的是 `ok=False` 而不是异常

**完成判据**
- [ ] 四重校验都有测试
- [ ] 超时取消的测试能证明**目标任务真的停了**（不只是调用方放弃等待）
- [ ] `AgentEvent` 会推给客户端
- [ ] 单 Agent 路径 evals 零回归

---

### B6 · 共享黑板

`P1` / 4d / 依赖 B5

**背景**
委派是同步的请求-响应。有些协作需要异步共享（比如 researcher 先把调研结论写下，coder 和 reviewer 都能读）。黑板补这个场景。

**操作步骤**

1. `core/agents/blackboard.py`：append-only、带作者、per-session。
2. **不要做成通用 KV**。刻意限制：
   - 只能 `put(key, value, author_role)` 和 `get(key)` / `list_keys()`
   - **不能删除、不能覆盖**（同 key 再 put 是追加新版本，读取拿最新）
   - 每条带 `author_role` 和时间戳
3. 理由写进 docstring：可追溯性。多 Agent 系统最难调试的问题是"这个错误结论是谁写进去的"，append-only + 作者标记直接解决。
4. 大小上限：单 session 黑板总字节数上限（默认 1 MB），超了拒绝写入并返回明确错误。
5. `DelegateRequest.context_keys` 让发起方指定目标能看到哪些黑板条目——**默认不是全部可见**。

**完成判据**
- [ ] append-only 语义有测试（覆盖同 key 多次写入）
- [ ] 大小上限有测试
- [ ] `context_keys` 的可见性控制有测试

---

### B7 · 内置角色包

`P1` / 4d / 依赖 B4 B5 B6

**背景**
提供开箱可用的四个角色。**这一卡的价值在于把前面的抽象验证一遍**——如果四个角色配不出来，说明 AgentSpec 的设计有问题。

**操作步骤**

1. `core/agents/roles/builtin.yaml`：

```yaml
# 内置 Agent 角色。
#
# 设计原则：
#   - 能写文件的角色越少越好（只有 coder）
#   - 只读角色不能委派（避免委派链变长）
#   - 每个角色的 prompt_stage 必须在 core/prompts 里存在
agents:
  - role: architect
    display_name: 架构师
    prompt_stage: agent_architect
    tools: [read_file, grep, list_dir, codebase_search]
    can_delegate: true
    delegate_to: [researcher, coder, reviewer]
    memory_scope: private
    timeout_s: 300

  - role: researcher
    display_name: 调研员
    prompt_stage: agent_researcher
    tools: [read_file, grep, codebase_search, web_search]
    can_delegate: false
    memory_scope: private
    timeout_s: 240

  - role: coder
    display_name: 编码员
    prompt_stage: agent_coder
    tools: null          # null = 全部工具（含写入和 shell）
    can_delegate: false
    memory_scope: private
    timeout_s: 600

  - role: reviewer
    display_name: 审查员
    prompt_stage: agent_reviewer
    tools: [read_file, grep, list_dir, codebase_search]
    can_delegate: false
    memory_scope: private
    timeout_s: 300
```

2. 在 `core/prompts/templates.py` 里加对应的四个 stage 模板。**这时才真正用上 B1 保留的 `SUBAGENT_DECOMPOSE_TEMPLATE`**——architect 用它来拆任务并决定委派给谁。

3. **注意工具名要与实际注册的工具名一致**。用这条命令核对：

```powershell
python -c "from tools.registry import default_registry; print(sorted(default_registry.list_names()))"
```

YAML 里写的每个名字都必须在这个列表里，否则 B4 的构造校验会报错（这是**期望**的行为）。

4. 加一个端到端测试：用 mock LLM 跑一轮 architect → coder → reviewer 的完整委派链。

**完成判据**
- [ ] 四个角色能加载且通过 B3 的静态校验
- [ ] 四个 prompt stage 都存在
- [ ] YAML 里的工具名全部有效
- [ ] 端到端委派链测试通过

---

### B8 · 多 Agent 观测

`P1` / 4d / 依赖 B5

**背景**
多 Agent 最大的运维难题是"不知道刚才发生了什么"。现有的 `core/tracing.py` 有 span 收集和 JSONL 落盘，扩展它即可。

**操作步骤**

1. 给 span 加 `agent_role` 和 `delegation_depth` 字段。
2. 委派本身作为一个 span，父子关系反映委派链。
3. 加一个 CLI：`python -m core.tracing replay --session <id> --show-agents`，输出委派树：

```
session abc123
└─ architect (12.3s, 4.2k tokens)
   ├─ researcher (8.1s, 2.1k tokens)  "查一下这个库的 API"
   ├─ coder (45.2s, 18.7k tokens)     "按方案实现"
   │  └─ [tool] write_file × 3
   └─ reviewer (9.8s, 3.4k tokens)    "审查改动"
      └─ 结论: 2 处问题
```

4. `AgentEvent` 推给前端，OpenTUI/Desktop 能显示"现在是哪个角色在工作"。

**完成判据**
- [ ] trace 里能看出委派链
- [ ] replay CLI 可用
- [ ] 前端能显示当前角色

---

### B9 · 多 Agent 评测

`P1` / 5d / 依赖 B7，依赖主计划 Phase 1

**背景**
必须能回答"多 Agent 到底有没有比单 Agent 强"。主计划 H2 已经建了 `--backend` 框架，H3 建了 `tool_used` 检查，现在加 Agent 维度。

**操作步骤**

1. `evals/cli.py` 加 `--agents single|multi`。
2. 新增两种 check：`agent_used`（断言某个角色参与了）、`delegation_depth_max`（断言委派没失控）。
3. 报告输出三方对比：

```
Backend            Pass rate   Avg tokens   Avg duration   Avg delegations
raw-llm              42%           1,240         3.1s              —
agent (single)       68%           9,870        41.7s              —
agent (multi)        ??%          ??,???        ??.?s             ?.?
```

4. **诚实面对结果。** 多 Agent 很可能在简单任务上更慢更贵且不更准。如果矩阵显示这一点，**写进文档**，并把多 Agent 设为"复杂任务才启用"而不是默认开。

**完成判据**
- [ ] 三方对比矩阵已产出并提交
- [ ] 结论写进 `docs/modules/agents.md`，包括"什么时候不该用多 Agent"
- [ ] 基于结果决定默认开关状态

---

### B10 · 客户端接入

`P1` / 5d / 依赖 B5 B8，依赖主计划 Phase 2（protocol-client）

**操作步骤**

1. `frontend/protocol-client` 重新生成类型（含 `AgentEvent`、`DelegateRequest`）。
2. OpenTUI 显示当前角色 + 委派链（简化版，一行文字即可）。
3. 用户可以在设置里开关多 Agent 模式、看角色配置。
4. **不做**角色的图形化编辑器——那是 Phase 3 之后的事。

---

### B11 · 文档

`P1` / 4d / 依赖 B1–B10

**操作步骤**

1. 新建 `docs/modules/agents.md`，必须包含：
   - 四条设计约束（§2.2）及理由
   - `AgentSpec` 每个字段的语义
   - 委派的四重校验规则
   - **加一个新角色的完整步骤**（照抄本文件 §5）
   - **B9 的评测结论，包括什么场景不该用多 Agent**
2. 更新 `docs/modules/core.md`、`docs/modules/tools.md`（per-agent 注册表）、`docs/modules/cache.md`（namespace 加了 agent 维度）、`docs/modules/memory.md`（memory_scope）、`docs/modules/recovery.md`（breaker key）。
3. 更新 `AGENTS.md` 的架构图。
4. 更新主计划的 Phase 表。

---

## §4 Phase B 出口检查

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=900
python -m pytest tests/test_agents -q
python -m evals.cli run --backend agent --agents single --compare-baseline evals\baselines\latest-agent.json
python -m evals.cli run --backend agent --agents multi --save-baseline
Select-String -Path *.py,core\*.py,tools\*.py -Pattern "_run_with_subagents|SubAgentV2|agent_tool" -Recurse
```

**Phase B 完成的定义：**
- 前 5 条命令全绿，**单 Agent 路径零回归**
- 最后一条无输出（死代码已清）
- 四个内置角色可用，端到端委派链跑得通
- 多 Agent 与单 Agent 的评测矩阵已产出，**结论写进了文档（包括负面结论）**
- `docs/modules/agents.md` 可独立指导加新角色

---

## §5 扩展手册：加一个新 Agent 角色

> Phase B 之后的长期操作流程。

**第 1 步 · 想清楚这个角色的边界**

回答三个问题，答不上来就不要加：
1. 它需要哪些工具？（能不能只给只读工具？）
2. 它需要委派吗？（尽量设 `can_delegate: false`，委派链越短越好）
3. 它的记忆要不要与别人共享？（默认 `private`，除非有明确理由）

**第 2 步 · 加 prompt stage**

在 `core/prompts/templates.py` 加 `agent_<role>` 模板，在 `few_shot.py` 加至少 1 个示例。

**第 3 步 · 加 AgentSpec**

`core/agents/roles/builtin.yaml`（内置）或用户配置文件（自定义）。

**第 4 步 · 核对工具名**

```powershell
python -c "from tools.registry import default_registry; print(sorted(default_registry.list_names()))"
```

YAML 里的每个工具名都必须在这个列表里。

**第 5 步 · 校验委派图**

```powershell
python -c "from pathlib import Path; from core.agents.spec import load_specs; print(sorted(load_specs(Path('core/agents/roles/builtin.yaml'))))"
```

有环或有未知目标会直接报错。

**第 6 步 · 加隔离测试**

在 `tests/test_agents/test_isolation.py` 加一条，断言新角色的工具集确实受限。

**第 7 步 · 跑评测**

```powershell
python -m evals.cli run --backend agent --agents multi --save-baseline
```

对比加角色前后的通过率和 token 消耗。**如果加了角色反而更差，就不要加。**

**第 8 步 · 更新文档**

`docs/modules/agents.md` 的角色列表。

---

## §6 与 Phase C 的接口

Phase B 为多模态预留了这些接缝，**实现时不要破坏**：

| 预留 | 给 Phase C 用 | 约束 |
|---|---|---|
| `AgentSpec.extra` | 声明"这个角色需要 vision 能力" | Phase C 会加 `requires_vision: true`，Orchestrator 要据此校验模型 |
| `BlackboardEntry.value: str` | Phase C 需要放图像引用 | **Phase C 会把它拓宽成 content block**，所以现在不要在别处假设它一定是纯文本 |
| `AgentRuntime` 的 LLM 解析走 provider 层 | `ModelCapabilities.supports_vision` | 角色要求 vision 但模型不支持时，必须在**构造时**报错 |
| `AgentEvent` 的 `detail: str` | 多模态角色的产出摘要 | 同上，可能需要拓宽 |
