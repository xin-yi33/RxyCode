# Phase B · 多 Agent 专家团编排（Expert Team Orchestration）

> **在整条路线中的位置**：[`2026-07-31-EXECUTION-PLAN.md`](./2026-07-31-EXECUTION-PLAN.md) 的后继扩展，编号 Phase B。
> **前置条件**：主计划 Phase 0/1/2 + [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) 全部完成。
> **后继**：[`PHASE-C-MULTI-MODEL-COLLABORATION.md`](./PHASE-C-MULTI-MODEL-COLLABORATION.md)
>
> **一句话目标**：把"一个 Agent 干所有事"变成"一个团长带一支专家团"——团长不干活只调度，成员各有角色、工具集、记忆域，所有跨成员通信经团长中转，全程有 SOP 约束、有机械验证门、有成本熔断。
>
> **执行模型**：Composer 2.5 为主力，Grok / Sonnet 5 辅助。分工见 §0.2。
> **修订**：2026-07-31 第 2 版（基于 GitHub 深度调研重写，见 §2）
> **预计工时**：8 周（1 名后端 + 0.5 名前端）
>
> ⚠️ **这是整条路线风险最高的一段。** 它既要拆地基（三组全局单例），又要建一套新的协调层——而协调层本身就是多 Agent 系统最大的失败来源（§2.5 有实测数据）。**每一张卡都必须能独立回滚。**

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | 执行协议、模型分工、硬性规则 |
| [§1 现状真相](#1-现状真相实测证据) | 现在的"子代理"到底是什么 |
| [§2 调研：抄谁、抄什么](#2-调研抄谁抄什么) | **本次重写的核心依据**，GitHub 实测数据 + 各框架取舍 |
| [§3 目标架构](#3-目标架构) | 专家团、团长、SOP 状态机、难度路由 |
| [§4 任务卡 B1–B15](#4-任务卡) | 逐个执行 |
| [§5 出口检查](#5-phase-b-出口检查) | 怎么算做完 |
| [§6 扩展手册](#6-扩展手册) | 加角色、加专家团、加 SOP |
| [§7 与后续 Phase 的接口](#7-与后续-phase-的接口) | Phase C/D/E 的预留 |

---

## §0 执行手册（必读）

### 0.1 执行协议

与 Phase A 相同的 7 步（LOCATE → READ → WRITE → LINT → TEST → CHECK → COMMIT），加 Phase B 专属的三条：

```
8.  ISOLATE   跑隔离性测试（B2 之后每张卡都要跑）
              python -m pytest tests/test_agents/test_isolation.py -q

9.  BASELINE  跑评测基线比对，单 Agent 路径分数不许掉
              python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json

10. BUDGET    跑成本护栏测试（B9 之后每张卡都要跑）
              python -m pytest tests/test_agents/test_budget_guard.py -q
```

**为什么要第 8 步**：拆全局单例最典型的 bug 是"看起来能跑，但两个 Agent 悄悄共享了状态"——不会让测试变红，只会让行为变怪。

**为什么要第 10 步**：Anthropic 实测多 Agent 消耗 **15 倍 token**，而且他们公开承认自己的架构**没有熔断**，一个失控的子代理能让单次查询再翻 10 倍（§2.5）。成本护栏在本项目是**功能的一部分**，不是可选优化。

### 0.2 三个模型的分工

| 模型 | 干什么 | 不要干什么 |
|---|---|---|
| **Composer 2.5** | 按任务卡实现。B2 拆单例、B4 运行时、B7 邮箱都是多文件机械改写，它擅长 | 决定要不要偏离本文档的架构决策（§3.2 的七条已经定死） |
| **Grok** | 读 §2 列出的开源项目源码，回答具体实现问题（例如"AgentMux 的状态机文件协议长什么样"）。**不直接改代码** | 重新做框架选型——§2 已经选完了 |
| **Sonnet 5** | 重点审 B2（拆单例）和 B7（消息中转）的 diff，这两张最容易漏改。写文档（B15） | 长任务连续实现 |

### 0.3 前置自检

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .                              # 主计划 Phase 0
Test-Path evals\baselines\latest-agent.json         # 主计划 Phase 1 → True
Test-Path core\session.py, protocol\schema.json     # 主计划 Phase 2 → True True
Test-Path core\providers\__init__.py                # Phase A → True
```

四条全满足才开始。**最需要防的误判是跳过主计划 Phase 2**——没有 `Session` 和 `protocol/`，你会在 3704 行的 `agent_v2.py` 里手工造一套 ad-hoc 通信机制。

### 0.4 硬性规则

| # | 规则 | 依据 |
|---|---|---|
| MB1 | **单 Agent 路径行为逐字节不变。** 多 Agent 是新增能力，默认关闭 | Anthropic：编码任务本就不太适合多 Agent（§2.5） |
| MB2 | **拆单例时一行业务逻辑都不改** | 否则 diff 无法 review |
| MB3 | **所有跨成员通信必须经团长中转**，成员之间不得直连 | WorkBuddy 与 AgentMux 的一致做法（§2.3） |
| MB4 | **SOP 阶段转移用确定性状态机，不用 LLM 自由路由** | CrewAI hierarchical 的 LLM 路由 20% 会做出无法调试的决策（§2.2） |
| MB5 | **LLM 审计之前必须先过机械验证门** | karajan / local-ai-agent-orchestrator 的做法，省钱且更可靠（§2.4） |
| MB6 | **成员不得再创建子团队**，委派深度硬上限 3 层 | Anthropic：递归 spawn 能让成本再翻 10 倍（§2.5） |
| MB7 | **每次运行有 token 预算、时长上限、委派次数上限，超了就停** | 同上 |
| MB8 | 一张卡一个 commit，可独立 revert | 风险控制 |

---

## §1 现状真相（实测证据）

**现在的"多 Agent"是不存在的。** 四处遗留物在制造"已经有了"的错觉，一处都不通。

### 1.1 五处死代码

| 遗留物 | 位置 | 实际状态 |
|---|---|---|
| `_run_with_subagents` | `core/agent_v2.py:2905-2909` | **无条件抛 RuntimeError**，零调用点 |
| `_should_use_subagents` | `core/agent_v2.py:2882-2903` | 中英文关键词匹配，唯一作用是设 `parallel_requested` 标志 |
| `SubAgentV2` | `core/agent_v2.py:3707-3715` | 只把任务转发给父 Agent，**零实例化** |
| `agent_tool` | `tools/agent_tool.py:15-23` | 会 new 一个 AgentV2，但**从未注册**，LLM 调不到 |
| `subagent_decompose` 模板 | `core/prompts/templates.py:236-259`、`:340` | 已定义已注册，**生产代码零调用** |

```2905:2909:core/agent_v2.py
    async def _run_with_subagents(self, user_input: str) -> str:
        """使用子代理并行执行任务。"""
        raise RuntimeError(
            "legacy sub-agent execution is disabled; use the validated TaskTree graph"
        )
```

`docs/modules/core.md:36,43` 还在描述这些不存在的行为。

### 1.2 现在真正在跑的

**单个 AgentV2 + 一条静态 LangGraph 管线 + 图内任务并行。**

```1171:1183:core/graph.py
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

并发在 `core/graph.py:613-626`（`asyncio.gather` + `Semaphore`）。并行的是**同一个 Agent 的 TaskTree 叶节点**，共享同一份 `_tool_orchestrator`、`_memory`、`session_id`。这不是多 Agent。

Compose 模式（`agent_v2.py:2911-3006`）也是同一个 Agent 的两个顺序阶段。

### 1.3 三组全局单例——真正的障碍

| 单例 | 位置 | 后果 |
|---|---|---|
| `ToolRegistry` | `tools/registry.py:88` | 工具表全进程共享，无法 per-agent 限定 |
| 两级缓存 | `cache/precise_cache.py:227-228`、`cache/semantic_cache.py:267-268` | 两个 Agent 互相命中对方缓存 |
| 熔断器 | `recovery/circuit_breaker.py:8-10`（注释明说每进程共享） | 一个 Agent 熔断连坐全体 |

### 1.4 已经是 per-instance 的（好消息，不用改）

| 资源 | 位置 |
|---|---|
| `ToolOrchestrator` | `core/agent_v2.py:797` |
| 编译后的 graph | `core/agent_v2.py:786-787` |
| `ModelRouter` | `core/agent_v2.py:687-701` |
| `MemoryManager` | `core/agent_v2.py:720`（但默认 `session_id="latest"`，见 `:675`，实际仍共享） |

### 1.5 可复用的半成品

| 现有能力 | 位置 | 在 Phase B 的角色 |
|---|---|---|
| `ModelRole` + `ModelRouter` | `core/governance.py:370-374`、`:409-487` | "不同角色不同模型"已有 60% |
| `PromptRegistry` 的 stage 维度 | `core/prompts/registry.py` | 角色 prompt 直接复用这套注册机制 |
| `ToolOrchestrator.select_tools` | `execution/tool_orchestrator.py:324-358` | 改造成 agent 级作用域 |
| `HookRegistry` | `core/agent_v2.py:703-710`、`core/graph.py:63-75` | 多 Agent 生命周期观测挂点 |
| **LangGraph 已在用** | `core/graph.py` 10 个节点 | **决定了我们用 supervisor 模式而非引入 CrewAI**（§2.2） |

---

## §2 调研：抄谁、抄什么

> **这一章是本文档第 2 版重写的依据。** 你的设想（团长传话人、专家分工、多模型协作）在开源界都有成熟实现，不需要从零发明。以下是 2026-07-31 的实测调研。

### 2.1 候选框架实测数据

| 项目 | Star（2026-07-31） | 最近推送 | 范式 |
|---|---|---|---|
| All-Hands-AI/OpenHands | 82,643 | 2026-07-31 | 通用 Agent 平台 |
| FoundationAgents/MetaGPT | 69,605 | 2026-01-21 | SOP 软件公司 |
| microsoft/autogen | 60,125 | 2026-04-15 | 会话式 GroupChat |
| crewAIInc/crewAI | 56,417 | 2026-07-31 | 角色/任务/Crew |
| langchain-ai/langgraph | 38,553 | 2026-07-31 | 有状态图 |
| OpenBMB/ChatDev | 33,871 | 2026-07-24 | 软件公司对话 |
| openai/openai-agents-python | 28,309 | 2026-07-31 | handoff |
| ag2ai/ag2 | 4,819 | 2026-07-31 | AutoGen 分叉 |
| langgraph-supervisor-py | 1,635 | 2026-07-15 | supervisor 封装 |
| markuswondrak/AgentMux | 34 | 2026-05-17 | **多模型 CLI 编排** |
| gabewillen/atmux | 19 | 2026-05-21 | tmux 多 Agent |

> Star 数**不等于**参考价值。AgentMux 只有 34 star，但它的架构与你的设想吻合度最高（§2.4）。

**刷新命令**：

```powershell
$repos = @("FoundationAgents/MetaGPT","microsoft/autogen","crewAIInc/crewAI","langchain-ai/langgraph","markuswondrak/AgentMux")
foreach ($r in $repos) { $d = Invoke-RestMethod "https://api.github.com/repos/$r" -Headers @{ "User-Agent"="rxycode" }; "{0,-40} {1,8}" -f $r, $d.stargazers_count }
```

### 2.2 编排范式对比与我们的选择

| 范式 | 代表 | 转移由谁决定 | 已知问题 |
|---|---|---|---|
| **有状态图（supervisor）** | LangGraph | 显式条件边，确定性 | 前期建图成本高 |
| **角色/任务/Crew** | CrewAI | `Process.hierarchical` 用 manager LLM 动态派活 | **"80% 时候很漂亮，另外 20% 做出莫名其妙的路由决策，而且极难调试，因为推理过程隐含在 LLM 响应里"** |
| **会话式群聊** | AutoGen / AG2 | `GroupChatManager` 选下一个发言人 | 非确定性，开放式场景才有优势 |
| **确定性流水线** | AgentMux | 文件驱动的状态机，"Agents don't freelance" | 灵活性低（但这正是我们要的） |

**决策 1：用 LangGraph supervisor + AgentMux 式确定性 SOP，不引入 CrewAI / AutoGen。**

三条理由：
1. **RxyCode 已经在用 LangGraph**（`core/graph.py` 10 个节点、checkpointing、conditional edges 全都有）。引入第二个编排框架等于维护两套心智模型。
2. 调研中反复出现的一句建议：*"如果你已经知道每一步该由哪个 agent 执行，就不要用 CrewAI 的 hierarchical 或 AutoGen 的 SelectorGroupChat——两者都用 LLM 路由，增加延迟、成本和不确定性。"* 软件开发 SOP 恰恰是"知道每一步该谁做"的场景。
3. LangGraph 被普遍评为 production standard（checkpointing、time-travel debugging、human-in-the-loop 原生支持）。

**但 CrewAI 的角色抽象值得抄**：`Agent(role, goal, backstory)` + `Task(expected_output)` 这套心智模型映射业务流程非常自然，我们的 `AgentSpec` 照抄这个形状。

### 2.3 团长（Master）模式——你的设想已被验证

你描述的"master 是传话人"，两个成熟系统的做法**完全一致**：

**腾讯 WorkBuddy 专家团**（调度-执行 / Orchestrator-Worker）：
> 团长/主理人**不直接干活，只管调度**：拆需求、配成员、看进度、收产出。
> 四项机制：① 建立团队（**只能由主理人执行**）② 调度成员（按 SOP 阶段拉入，下发独立任务）③ **消息中转——所有跨成员的信息流必须经主理人中转** ④ 任务预检（派发前做能力匹配）
> 成本：专家团积分消耗是单专家的 **3–5 倍**。

**AgentMux**（多模型 CLI 编排）：
> 确定性状态机 PM → Architect → Plan → Code → Review → Done。
> **"Agents coordinate through a shared file protocol — they never talk to each other directly. The orchestrator decides what happens next and injects the appropriate prompt into the right pane."**

**对照组 · 腾讯 CodeBuddy Agent Teams** 走了另一条路：team-lead + teammates，**成员之间可以直接通信**，用户也能绕过 lead 直接跟任意成员对话。它明确区分于 sub-agent："子代理在单一会话内运行、只能把结果报告给主代理；Agent Teams 成员之间可以直接通信。"

**决策 2：采用 WorkBuddy / AgentMux 的"必经团长中转"，不采用 CodeBuddy 的成员直连。**

理由：可追溯（每条消息都有经手记录）、可限流（团长是唯一收费站）、可 trace（委派树是真的树而不是图）、防死锁（成员之间无环等待）。

**你要的"coder 发现问题找 architect 沟通"照样能实现**——只是走团长转发。语义完全一样，但多了管控点。这在 §4 的 B7 里叫 `ConsultRequest`。

### 2.4 多模型协作——AgentMux 是最贴近你设想的实现

你说的"opus5 做架构、grok 写代码、gpt 做测试审计"，AgentMux 的配置文件长这样：

```yaml
version: 2
defaults:
  provider: claude
  model: sonnet
roles:
  architect:
    model: opus
  coder:
    provider: codex
  reviewer:
    model: sonnet
```

它支持的角色：`product-manager`（可选首阶段）、`architect`（规划与重规划）、`coder`（实现与修复）、`reviewer`（审查与最终确认）、`code-researcher`（按需代码分析）、`web-researcher`（按需联网调研）。

**另外两个值得抄的机制：**

**karajan-code** —— *"Deterministic first, then cross-AI review"*：先跑 SonarQube（BLOCKER/CRITICAL 当场拒绝），然后把**另一个 AI** 的审查结论**绑定到该 diff 的 sha256** 上。没有 approved verdict，commit 进不去。

**local-ai-agent-orchestrator** —— planner → coder → verifier → reviewer 四段，在 coder 和 reviewer 之间插了 **Mechanical Verification**（文件是否存在、AST / JSON 能否解析）。

**决策 3：LLM 审计之前先过机械验证门。**

这正好回答你说的"gpt 审计 grok 是否真的干完了"——**先用确定性检查回答"干完了没有"**（文件存在吗？能编译吗？测试过吗？lint 干净吗？），机械检查过不了就直接打回，**根本不用花审计模型的 token**。机械检查过了，再让审计模型看"干得对不对"。

**决策 4：审计结论绑定 diff 哈希。** 抄 karajan。审计通过的是"这一份具体的 diff"，coder 改完之后旧的通过结论自动失效。这防止"审计通过 → 又偷偷改了 → 直接提交"。

**atmux 的 pair-program 角色**对应你说的"grok 和 composer 共同写代码"：driver（快模型写代码、跑测试）+ navigator（强模型盯着共享 worktree 的滚动 diff，发现实现漂移就打断，**自己不编辑文件**）。这个模式留到 Phase C 实现。

### 2.5 必须正视的负面数据

**这一节决定了 Phase B 的默认配置。**

Anthropic 公开了他们多 Agent 研究系统的真实数据：

| 事实 | 数值 |
|---|---|
| 单 Agent vs 普通对话 token 消耗 | **4 倍** |
| 多 Agent vs 普通对话 token 消耗 | **15 倍** |
| token 用量单独解释了性能方差的 | **80%** |
| WorkBuddy 专家团 vs 单专家积分消耗 | 3–5 倍 |

三条原文警告：

> "most coding tasks involve fewer truly parallelizable tasks than research, and LLM agents are not yet great at coordinating and delegating to other agents in real time."

**RxyCode 是编码 Agent，正好落在 Anthropic 说的"不太适合"那一类。**

> "The published architecture has no circuit breakers or per-run caps... a subagent that recursively spawns more subagents, or a tool that returns oversized results, can multiply a single query's cost by another 10x or more."

**Anthropic 自己都没做熔断。我们必须做**（规则 MB6/MB7，任务卡 B9）。

还有一项失败归因研究：跨 AutoGen / CrewAI / LangGraph 的失败分类中，**协调失败占全部失败的 36.94%**。也就是说，你新加的这一层协调逻辑，本身就是最大的失败来源。

**决策 5：多 Agent 默认关闭，由难度路由 + 用户显式指令决定何时开。**

这正好是你设想的"判断任务难度 → 选择单/多 Agent"，调研数据强力支持这个设计。

**决策 6：即使不开多 Agent，也先把三个便宜的模式吃下来。** Anthropic 明确指出这三条在单 Agent 内就能拿到收益：
1. 上下文填满前把状态外置到记忆（RxyCode 的 `memory/` 已有）
2. 用自包含的任务描述隔离 worker（对应我们的 `DelegateRequest`）
3. **高风险产出用独立的一遍来验证**（对应我们的机械验证门 + 审计角色）

### 2.6 抄取清单汇总

| 来源 | 抄什么 | 落在哪张卡 |
|---|---|---|
| CrewAI | `Agent(role, goal, backstory)` + `Task(expected_output)` 的角色抽象形状 | B3 |
| MetaGPT | SOP 编码进流程；**结构化文档通信而非自由对话**；角色 profile（name/goal/constraints） | B3 B5 |
| WorkBuddy 专家团 | 团长不干活只调度；建团/派活/中转/收口四步；**所有跨成员流量经团长**；任务预检做能力匹配 | B6 B7 |
| AgentMux | 确定性状态机 SOP；per-role provider/model 配置；"agents don't freelance" | B5、Phase C |
| karajan-code | 确定性检查先于 AI 审查；**审计结论绑定 diff sha256** | B8 |
| local-ai-agent-orchestrator | coder 与 reviewer 之间的机械验证（文件存在、AST 可解析） | B8 |
| Anthropic | 15x 成本事实；熔断与预算上限；三条"单 Agent 也能用"的模式 | B9 B14 |
| LangGraph | supervisor 拓扑、checkpointing、条件边 | B5 B6 |
| atmux | pair-program 的 driver/navigator | Phase C |
| CodeBuddy Agent Teams | **反面参考**：成员直连，我们不采纳 | §2.3 |

---

## §3 目标架构

### 3.1 全景图

```
用户输入
   │
   ▼
┌──────────────────────────────────────────────────────────┐
│ core/agents/router.py  ModeRouter  「难度路由」            │
│                                                            │
│  第 1 级 用户显式指令   /solo /team /team-multi  → 直接决定 │
│  第 2 级 确定性信号     涉及文件数 / 跨模块 / 任务树规模     │
│  第 3 级 LLM 判难度     模型由用户在 settings 里选（可关闭） │
│                                                            │
│  输出：SOLO | TEAM | TEAM_MULTI_MODEL                      │
└───────────────┬──────────────────────────────────────────┘
                │
    ┌───────────┼────────────────────┐
    ▼           ▼                    ▼
  SOLO        TEAM              TEAM_MULTI_MODEL
 现有单Agent   专家团（本 Phase）    专家团 + 每角色不同模型
 路径不变                          （Phase C）
                │
                ▼
┌──────────────────────────────────────────────────────────┐
│ core/agents/coordinator.py   Coordinator「团长」           │
│                                                            │
│  职责（抄 WorkBuddy 主理人）：                              │
│   ① 建团      只有团长能建，成员不能建子团队               │
│   ② 派活      按 SOP 阶段下发自包含任务                     │
│   ③ 中转      所有跨成员消息必经此处                        │
│   ④ 收口      汇总产出，决定是否进入下一阶段                │
│                                                            │
│  它自己不写代码、不调业务工具，只调协调工具                  │
└───┬────────────────────────────────────────────┬─────────┘
    │                                             │
    ▼                                             ▼
┌────────────────────────┐          ┌────────────────────────┐
│ SopMachine「SOP 状态机」│          │ BudgetGuard「成本熔断」 │
│ 确定性阶段转移           │          │  token 预算             │
│ PLAN→CODE→VERIFY→       │          │  委派深度 ≤ 3           │
│ AUDIT→DONE              │          │  委派次数上限           │
│ 只在"审计失败打回给谁"   │          │  墙钟时长上限           │
│ 这类真决策点用 LLM       │          │  禁止递归 spawn         │
└────────────────────────┘          └────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│ Mailbox「邮箱」 + Blackboard「黑板」                       │
│  Mailbox   : 团长 ↔ 成员的定向消息，append-only            │
│  Blackboard: 阶段产出物，成员按 context_keys 授权可见       │
└───┬──────────────────────────────────────────────────────┘
    │
    ├──────────────┬──────────────┬──────────────┐
    ▼              ▼              ▼              ▼
AgentRuntime   AgentRuntime   AgentRuntime   AgentRuntime
 architect       coder         verifier       auditor
 只读工具       全部工具       机械验证       只读工具
 独立记忆       独立记忆       无 LLM ！      独立记忆
 独立缓存       独立缓存       纯确定性        独立缓存
 独立熔断       独立熔断                      独立熔断
```

**注意 `verifier` 是特殊的：它不是 LLM Agent，是纯确定性的机械验证门**（决策 3）。它跑 lint、测试、AST 解析、文件存在性检查。过不了就直接打回给 coder，不消耗 auditor 的 token。

### 3.2 七条不可违反的设计约束

| # | 约束 | 依据 |
|---|---|---|
| DB1 | **单 Agent 是"只有一个成员的团"**，不是另一条代码路径 | 两条路径必然漂移 |
| DB2 | **成员之间不得直连**，所有通信经 Coordinator | §2.3 WorkBuddy / AgentMux |
| DB3 | **每个 AgentRuntime 独立持有** memory namespace、cache namespace、circuit breaker、tool registry | §1.3 的三组单例是反面教材 |
| DB4 | **SOP 阶段转移由确定性状态机决定**，LLM 只在明确标注的决策点介入 | §2.2 CrewAI 的 20% 无法调试 |
| DB5 | **LLM 审计前必须过机械验证门**，审计结论绑定 diff sha256 | §2.4 karajan |
| DB6 | **成员不得创建子团队**，委派深度 ≤ 3，且每次运行有 token / 时长 / 次数三重上限 | §2.5 Anthropic |
| DB7 | **多 Agent 默认关闭** | §2.5，编码任务本就不是多 Agent 的强项 |

### 3.3 文件布局（**不要改**）

```
protocol/
  agents.py                    # AgentSpec / TeamSpec / 各类消息
core/
  agents/
    __init__.py
    spec.py                    # AgentSpec / TeamSpec 解析与静态校验
    runtime.py                 # AgentRuntime（隔离运行时）
    coordinator.py             # Coordinator（团长）
    sop.py                     # SopMachine（确定性状态机）
    mailbox.py                 # 定向消息
    blackboard.py              # 阶段产出物
    verifier.py                # 机械验证门（无 LLM）
    budget.py                  # BudgetGuard（成本熔断）
    router.py                  # ModeRouter（难度路由）
    teams/
      __init__.py
      software_dev.yaml        # 内置专家团：软件开发 SOP
tests/
  test_agents/
    __init__.py
    test_spec.py
    test_isolation.py          # B2 之后每张卡都跑
    test_coordinator.py
    test_sop.py
    test_mailbox.py
    test_verifier.py
    test_budget_guard.py       # B9 之后每张卡都跑
    test_router.py
    test_e2e_team.py
```

---

## §4 任务卡

### B1 · 清理多 Agent 死代码

`P0` / 4h / 无依赖（可与 Phase A 并行）

**背景**
§1.1 的五处遗留物持续误导人和 AI 代理。**造真的之前先把假的清干净**，否则你会在半途分不清哪些是遗留、哪些是自己新写的。

**操作步骤**

1. 确认无调用点：

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
Select-String -Path *.py,core\*.py,tools\*.py,execution\*.py,tests\*.py,api_server.py -Pattern "_run_with_subagents|SubAgentV2|agent_tool|run_agent_async" -Recurse |
  ForEach-Object { "$($_.Path -replace '.*RxyCode1_1_0\\',''):$($_.LineNumber): $($_.Line.Trim())" }
```

预期只有定义处 + 测试里"断言它被禁用"那几条。测试也一并删。

2. 删除 `_run_with_subagents`、`SubAgentV2`、`tools/agent_tool.py`。

3. `_should_use_subagents` **不要删**——它设的 `parallel_requested` 标志是当前并行执行的真实入口。改名 + 改注释：

```python
    def _should_request_parallel_execution(self, user_input: str) -> bool:
        """启发式判断用户是否希望并行执行多个任务。

        命名历史：原名 _should_use_subagents，但它与子代理无关——唯一作用
        是往 graph state 写 parallel_requested，触发 core/graph.py:1171 的
        TaskTree 叶节点并行。真正的多 Agent 编排见 core/agents/。

        这是关键词路由（主计划 P6 要消除的 25 处之一），对非中英文输入无效。
        Phase B 的 ModeRouter（B10）会取代它，届时本方法删除。
        """
```

用 Grep 找出所有调用点同步改名。

4. `SUBAGENT_DECOMPOSE_TEMPLATE` 保留，加状态注释：

```python
# 状态：已定义、已注册，生产代码尚未调用。实际任务分解走 decomposer 模板。
# Phase B 的 Coordinator（B6）会真正用上它做团队级任务拆分。
```

5. 修正 `docs/modules/core.md`（约 `:36`、`:43`）和 `AGENTS.md` 里 "Multi-task -> Sub-agent delegation" 的描述，改成实际行为：单 Agent + 图内任务并行。

**验收命令**

```powershell
Select-String -Path *.py,core\*.py,tools\*.py,tests\*.py,api_server.py -Pattern "_run_with_subagents|SubAgentV2|agent_tool" -Recurse
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] grep 无残留
- [ ] `_should_use_subagents` 已改名，调用点同步
- [ ] 文档描述与代码一致
- [ ] 全量测试绿，evals 无回归

**Commit**
```
chore(agents): remove dead multi-agent scaffolding

_run_with_subagents raised unconditionally, SubAgentV2 only forwarded to
its parent with zero call sites, and agent_tool was never registered so
the LLM could not reach it. All three made docs and readers believe
multi-agent support existed.
```

---

### B2 · 拆掉三组全局单例

`P0` / 2 周 / 依赖 B1、主计划 Phase 2

**背景**
§1.3 的三组进程级单例是多 Agent 的真正障碍。**纯粹的"全局变量 → 依赖注入"，一行业务逻辑都不改**（MB2）。

**拆成 3 个 commit，每组一个，让 Sonnet 5 逐个审查。**

#### 第 1 组：ToolRegistry

1. 摸清使用面（**这张表是你的改造清单，改完逐条勾掉**）：

```powershell
Select-String -Path *.py,core\*.py,tools\*.py,execution\*.py,api_server.py,tests\*.py -Pattern "from.*tools\.registry import|tools\.registry\.|\bregistry\.(register|get|get_descriptions|all|list_names)\b" -Recurse |
  ForEach-Object { "$($_.Path -replace '.*RxyCode1_1_0\\',''):$($_.LineNumber): $($_.Line.Trim())" }
```

2. `tools/registry.py`：

```python
#: 进程级默认注册表。
#:
#: 历史上这是唯一的注册表，所有工具都注册到这里，因此无法给不同 Agent 配
#: 不同工具集。Phase B 引入 per-agent 注册表；本实例保留为默认值，供单
#: Agent 路径和未显式传注册表的调用方使用。
#:
#: 新代码请通过依赖注入接收 ToolRegistry，不要直接 import 这个全局。
default_registry = ToolRegistry()

#: 向后兼容别名。新代码不要用。
registry = default_registry
```

3. `ToolOrchestrator.__init__` 接受 `tool_registry: ToolRegistry | None = None`，内部全部改用 `self._registry`。`AgentV2` 这一步先传 `None`（走默认），B4 才真正用上 per-agent 注册表。

#### 第 2 组：两级缓存

4. 全局实例改名 `default_precise_cache` / `default_semantic_cache`，旧名保留为别名。

5. **关键**：`_application_cache_namespace()`（`core/agent_v2.py:2098-2104`）加 agent 维度：

```python
    def _application_cache_namespace(self) -> str:
        """缓存命名空间。

        改造前只按 (模型, 凭证) 分，两个 Agent 用同一模型会互相命中对方的
        缓存。多 Agent 下不同角色的 system prompt 和工具集不同，必须隔离。
        """
        base = ...  # 原有逻辑一字不动
        agent_ns = getattr(self, "_agent_namespace", None)
        return f"{base}|{agent_ns}" if agent_ns else base
```

`self._agent_namespace` 在 `__init__` 里默认 `None`——**单 Agent 下必须返回与原来完全一样的字符串**，否则已有缓存全失效。

#### 第 3 组：熔断器

6. `recovery/circuit_breaker.py` 按 key 分桶：

```python
"""LLM 调用熔断器。

改造前是进程级单例，一个 Agent 触发熔断会连坐所有 Agent。现在按 key 分桶：
单 Agent 用默认 key（行为不变），多 Agent 下每个 AgentRuntime 用自己的 key。
"""

_BREAKERS: dict[str, CircuitBreaker] = {}


def get_breaker(key: str = "default") -> CircuitBreaker:
    breaker = _BREAKERS.get(key)
    if breaker is None:
        breaker = CircuitBreaker()
        _BREAKERS[key] = breaker
    return breaker


def reset_all_breakers() -> None:
    """仅供测试使用。"""
    _BREAKERS.clear()
```

#### 隔离测试

7. 新建 `tests/test_agents/test_isolation.py`（**Phase B 的安全网，之后每张卡都要跑**）：

```python
"""Agent 间状态隔离测试。

拆全局单例最典型的 bug 是"看起来能跑，但两个 Agent 悄悄共享了状态"——它
不会让别的测试变红，只会让行为变怪。这个文件专门抓它。
"""

def test_two_registries_do_not_share_tools():
def test_default_registry_not_polluted_by_new_instances():
def test_cache_namespaces_isolate_agents():
def test_single_agent_cache_namespace_is_unchanged():   # ← 最关键
def test_breakers_are_isolated_by_key():
def test_same_breaker_key_returns_same_instance():
```

`test_single_agent_cache_namespace_is_unchanged` 是防止已有缓存全失效的关键，一定要写。

**验收命令**

```powershell
python -m pytest tests/test_agents/test_isolation.py -q
python -m pytest tests -q --timeout=600
python -m ruff check .
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
```

**完成判据**
- [ ] 三组都改成"默认实例 + 可注入"，旧名保留
- [ ] 第 1 步的清单逐条勾掉，贴在 PR 描述里
- [ ] 隔离测试全绿
- [ ] 测试通过数与改动前一致
- [ ] **evals 零回归且耗时无明显增加**（耗时增加 = 缓存 namespace 变了）
- [ ] Sonnet 5 确认无业务逻辑改动

**常见坑**
- 最容易漏 `from tools.registry import registry` 这种 import 后直接用的写法。
- 改缓存 namespace 时如果单 Agent 路径的值变了，测试不会红但 evals 会变慢。

**Commit**（3 个）
```
refactor(tools): make ToolRegistry injectable instead of a process global
refactor(cache): add agent dimension to cache namespaces
refactor(recovery): key circuit breakers instead of one per process
```

---

### B3 · AgentSpec 与 TeamSpec

`P0` / 1 周 / 依赖 B2、主计划 Phase 2

**背景**
定义"一个角色是什么"和"一支专家团是什么"。角色抽象的形状抄 CrewAI（role / goal / backstory），profile 字段抄 MetaGPT（name / profile / goal / constraints）。纯数据结构 + 校验，风险低。

**涉及文件**
- 新建 `protocol/agents.py`、`core/agents/spec.py`、`tests/test_agents/test_spec.py`

**操作步骤**

1. `protocol/agents.py`：

```python
"""多 Agent 协议类型。

放在 protocol/ 内是为了能导出 JSON Schema 并生成 TypeScript 类型——CLI 和
Desktop 都需要展示"现在是哪个角色在工作"、"谁委派给了谁"。

角色抽象的形状参考 CrewAI（role/goal/backstory），profile 字段参考 MetaGPT
（name/profile/goal/constraints）。调研见
docs/plans/opus5-plan/PHASE-B-MULTI-AGENT-ORCHESTRATION.md §2。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    """一个角色的静态定义。Spec 不可变；运行时实例是 AgentRuntime。"""

    #: 角色标识，团内唯一，用作 memory / cache / breaker 的 namespace 前缀
    role: str
    #: 人类可读名称，UI 展示用
    display_name: str
    #: 这个角色为什么存在（进 prompt）
    goal: str
    #: 领域背景与行事风格（进 prompt）。抄 CrewAI 的 backstory。
    backstory: str = ""
    #: 硬性约束，例如"不得修改测试文件"（进 prompt，且尽量同时有工具级约束）
    constraints: list[str] = Field(default_factory=list)

    #: 使用的模型 id。None = 跟随会话默认模型。
    #: Phase B 阶段全部留 None（同模型）；Phase C 才按角色配不同模型。
    model: str | None = None

    #: 允许的工具名。None = 全部工具；[] = 无工具（纯推理角色）。
    tools: list[str] | None = None

    #: prompt 注册表的 stage 名
    prompt_stage: str

    #: 是否是"机械角色"——不调 LLM，只跑确定性检查（verifier 就是）
    mechanical: bool = False

    #: 记忆域。private = 独占 namespace；shared = 与会话共享。
    memory_scope: Literal["private", "shared"] = "private"

    #: 单次任务的墙钟超时（秒）
    timeout_s: float = 300.0
    #: 单次任务的 token 预算上限。None = 用团队默认。
    token_budget: int | None = None

    #: 该角色可以向哪些角色发起「咨询」（经团长转发，不是直连）。
    #: 空表示不能咨询任何人。见 §2.3 决策 2。
    may_consult: list[str] = Field(default_factory=list)

    #: 扩展字段。按命名空间约定使用，避免不同 Phase 的扩展互相踩：
    #:   pair.*      Phase C  结对编程
    #:   vision.*    Phase D  视觉能力
    #:   persona.*   Phase E  人格
    #: 详见 PHASE-E-PERSONA-AGENT-INTERFACE.md 的 E2。
    extra: dict[str, Any] = Field(default_factory=dict)


class SopStage(BaseModel):
    """SOP 的一个阶段。

    确定性状态机的一个节点（决策 DB4）。阶段转移由 next_on_success /
    next_on_failure 静态决定，不由 LLM 现场发挥。
    """

    name: str
    #: 该阶段由哪个角色执行
    role: str
    #: 该阶段要产出什么（进 prompt，抄 CrewAI 的 expected_output）
    expected_output: str
    #: 该阶段能看到哪些黑板条目（按 key 授权，默认不是全部可见）
    context_keys: list[str] = Field(default_factory=list)
    #: 产出写进黑板的哪个 key
    output_key: str
    #: 进入下一阶段前要跑哪些机械检查（B8）
    verify_before_next: list[str] = Field(default_factory=list)
    #: 机械检查通过后是否还要 LLM 审计
    audit_after_verify: bool = False
    #: 成功后去哪个阶段。None = 流程结束。
    next_on_success: str | None = None
    #: 失败后去哪个阶段。None = 整体失败。
    next_on_failure: str | None = None
    #: 该阶段最多重试几次
    max_retries: int = 2


class TeamSpec(BaseModel):
    """一支专家团 = 成员 + SOP。

    抄 WorkBuddy 专家团：团长不在成员列表里，它是运行时构造的。
    """

    name: str
    display_name: str
    description: str = ""
    members: list[AgentSpec]
    stages: list[SopStage]
    #: 起始阶段名
    entry_stage: str
    #: 整个团队单次运行的总 token 预算（决策 DB6）
    total_token_budget: int = 500_000
    #: 整个团队单次运行的墙钟上限（秒）
    total_timeout_s: float = 1800.0
    #: 最大委派次数（防止在两个阶段之间无限打回）
    max_delegations: int = 20


# ---- 运行时消息 -------------------------------------------------------

class DelegateRequest(BaseModel):
    """团长 → 成员：下发一个自包含任务。

    "自包含"是 Anthropic 的建议：目标、输出格式、工具清单、完成边界都要
    写清楚，否则成员会重复劳动或者不知道什么时候算完。
    """

    method: Literal["agents/delegate"] = "agents/delegate"
    session_id: str
    request_id: str
    to_role: str
    stage: str
    task: str
    expected_output: str
    context_keys: list[str] = Field(default_factory=list)
    depth: int = 0


class DelegateResult(BaseModel):
    request_id: str
    role: str
    ok: bool
    answer: str = ""
    error: str = ""
    tools_used: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    duration_s: float = 0.0


class ConsultRequest(BaseModel):
    """成员 → 团长 → 另一个成员：咨询。

    这是你说的"coder 发现问题去找 architect 沟通"。它**不是**成员直连——
    团长会校验 may_consult、记录、计入预算，再转发（决策 DB2）。
    """

    method: Literal["agents/consult"] = "agents/consult"
    session_id: str
    request_id: str
    from_role: str
    to_role: str
    question: str
    #: 咨询发起时所处的阶段，用于 trace
    stage: str


class VerdictRecord(BaseModel):
    """审计结论，绑定被审对象的哈希。

    抄 karajan-code：审计通过的是"这一份具体的产出"。产出变了，旧结论
    自动失效，防止"审计通过 → 又偷偷改了 → 直接提交"。
    """

    subject_hash: str          # 被审对象的 sha256
    auditor_role: str
    passed: bool
    findings: list[str] = Field(default_factory=list)
    created_at: float


class AgentEvent(BaseModel):
    """推给客户端的生命周期通知。"""

    method: Literal["event/agent"] = "event/agent"
    session_id: str
    role: str
    stage: str = ""
    phase: Literal["team_created", "stage_started", "delegated", "consulted",
                   "verified", "audited", "stage_completed", "failed",
                   "budget_exceeded", "team_completed"]
    detail: str = ""
```

2. `core/agents/spec.py` 的静态校验——**在配置时就拦住会烧钱或死循环的错误**：

```python
MAX_DELEGATE_DEPTH = 3


def validate_team(team: TeamSpec) -> None:
    """静态校验一支专家团。

    这些检查存在的意义是在配置时拦住错误，而不是等线上跑炸。
    """
    roles = {m.role for m in team.members}
    if len(roles) != len(team.members):
        raise AgentSpecError("duplicate role in team members")

    stage_names = {s.name for s in team.stages}
    if len(stage_names) != len(team.stages):
        raise AgentSpecError("duplicate stage name")

    if team.entry_stage not in stage_names:
        raise AgentSpecError(f"entry_stage {team.entry_stage!r} is not a stage")

    for stage in team.stages:
        if stage.role not in roles:
            raise AgentSpecError(
                f"stage {stage.name!r} references unknown role {stage.role!r}"
            )
        for nxt in (stage.next_on_success, stage.next_on_failure):
            if nxt is not None and nxt not in stage_names:
                raise AgentSpecError(
                    f"stage {stage.name!r} points at unknown stage {nxt!r}"
                )

    for member in team.members:
        if member.role in member.may_consult:
            raise AgentSpecError(f"role {member.role!r} may not consult itself")
        for target in member.may_consult:
            if target not in roles:
                raise AgentSpecError(
                    f"role {member.role!r} may_consult unknown role {target!r}"
                )

    _check_stage_graph_terminates(team)
    _check_consult_graph_acyclic(team)


def _check_stage_graph_terminates(team: TeamSpec) -> None:
    """确认 SOP 图存在可达的终点。

    全是环、没有 next=None 的出口，会让团队永远跑下去（预算会兜住，但那是
    最后一道防线，不该靠它）。
    """


def _check_consult_graph_acyclic(team: TeamSpec) -> None:
    """确认咨询图无环。

    A 可咨询 B、B 可咨询 A 会导致互相甩锅的无限往返。DFS 三色找环。
    """
```

3. `tests/test_agents/test_spec.py` 必须覆盖：重复 role、重复 stage、entry_stage 不存在、stage 引用未知 role、next 指向未知 stage、`may_consult` 未知角色、自咨询、**咨询二元环**、**咨询三元环**、SOP 图无出口。

**验收命令**

```powershell
python -m pytest tests/test_agents/test_spec.py -q
python -m ruff check protocol/agents.py core/agents
python -m protocol.schema | Out-File -Encoding utf8 protocol\schema.json
python -m pytest tests/test_protocol_schema.py -q
cd frontend\protocol-client; bun run generate; cd ..\..
git diff --exit-code frontend/protocol-client/src/generated/
```

**完成判据**
- [ ] 类型已进 `schema.json`，TS 类型已重新生成并提交
- [ ] 10 类校验错误都有测试
- [ ] 环检测覆盖自环、二元环、三元环
- [ ] `extra` 的命名空间约定已写进注释（Phase E 的 E2）

---

### B4 · AgentRuntime：隔离运行时

`P0` / 1.5 周 / 依赖 B2 B3

**背景**
把 Spec 变成能跑的东西。B2 拆出来的三组可注入资源在这里真正用起来（约束 DB3）。

**操作步骤**

1. `core/agents/runtime.py`：

```python
"""AgentRuntime：一个角色的运行实例。

每个 runtime 独立持有：
  - ToolRegistry   只含 spec.tools 声明的工具
  - cache namespace
  - circuit breaker key
  - memory namespace（memory_scope="private" 时）
  - LLM（按 spec.model 解析，走 Phase A 的 provider 层）

约束（§3.2）：
  DB2 —— runtime 之间不持有对方引用，只通过 Coordinator 通信
  DB3 —— 默认全隔离，共享必须显式声明
"""

class AgentRuntime:
    def __init__(self, spec: AgentSpec, *, session: "Session", ...):
        self._spec = spec
        self._namespace = f"agent:{spec.role}"
        self._registry = self._build_scoped_registry(spec.tools)
        self._cache_namespace = self._namespace
        self._breaker_key = self._namespace
        self._memory_namespace = (
            f"{session.id}:{spec.role}" if spec.memory_scope == "private"
            else session.id
        )
        if not spec.mechanical:
            self._llm, self._provider, self._capabilities = self._build_llm(spec)

    @staticmethod
    def _build_scoped_registry(tool_names: list[str] | None) -> ToolRegistry:
        """按角色声明构造独立注册表。

        None  → 复制默认注册表全部工具（等同单 Agent 行为）
        []    → 空注册表（纯推理角色）
        [...] → 只放声明的工具

        声明了不存在的工具名必须**抛异常**，不能静默忽略——静默忽略的后果
        是"这个 agent 莫名其妙不会写文件"，极难排查。
        """
```

2. `mechanical=True` 的角色（verifier）**不构造 LLM**。这是 B8 的基础。

3. 让 `Session` 能持有多个 runtime。**单 Agent = 只有一个 role="default" 的 runtime**（DB1）。

4. `tests/test_agents/test_isolation.py` 扩充：

```python
def test_runtimes_have_separate_tool_registries():
def test_runtimes_have_separate_cache_namespaces():
def test_runtimes_have_separate_breakers():
def test_private_memory_scope_does_not_leak():
def test_shared_memory_scope_does_leak_intentionally():
def test_unknown_tool_name_in_spec_raises():
def test_empty_tool_list_yields_empty_registry():
def test_mechanical_role_has_no_llm():
def test_single_agent_path_is_byte_identical():
```

**完成判据**
- [ ] 9 个隔离测试全绿
- [ ] 单 Agent 路径 evals 零回归（DB1 的验证）
- [ ] spec 里的错误工具名在构造时报错
- [ ] `mechanical` 角色确实没有 LLM
- [ ] Sonnet 5 确认 runtime 之间无交叉引用

---

### B5 · SOP 状态机

`P0` / 1 周 / 依赖 B3

**背景**
抄 AgentMux 的确定性状态机（决策 DB4）。**阶段转移是静态的，不是 LLM 现想的**——这是与 CrewAI hierarchical 最大的区别，也是可调试性的来源。

**操作步骤**

1. `core/agents/sop.py`：

```python
"""SOP 状态机。

阶段转移完全由 TeamSpec.stages 里声明的 next_on_success / next_on_failure
决定，不由 LLM 决定。这是刻意的：调研显示基于 LLM 的动态路由「80% 时候很
漂亮，另外 20% 做出莫名其妙的决策，而且因为推理隐含在响应里而极难调试」
（见 PHASE-B §2.2）。

LLM 只在一个地方介入：某阶段失败且 next_on_failure 有多个候选时，由团长
决策打回给谁。这个决策点是显式标注的，会进 trace。
"""

class SopMachine:
    def __init__(self, team: TeamSpec):
        self._team = team
        self._stages = {s.name: s for s in team.stages}
        self._current = team.entry_stage
        self._retries: dict[str, int] = {}
        self._history: list[StageRecord] = []

    def current_stage(self) -> SopStage: ...

    def advance(self, *, ok: bool) -> SopStage | None:
        """按结果推进。返回下一阶段，None 表示流程结束。

        失败时先看 max_retries：还有次数就原地重试，用完了才走
        next_on_failure。
        """

    def history(self) -> list[StageRecord]:
        """完整的阶段轨迹，用于 trace 和事后复盘。"""
```

2. **`SopMachine` 不依赖 LLM、不依赖 Session、不做 IO。** 它是纯函数式的状态机，可以直接单元测试。

3. `tests/test_agents/test_sop.py` 覆盖：正常推进、失败重试到上限、失败后走 failure 分支、终点、`max_retries=0`、阶段轨迹完整性。

**完成判据**
- [ ] `SopMachine` 无任何 LLM / IO 依赖，纯逻辑可测
- [ ] 6 类转移场景有测试
- [ ] 轨迹能完整还原一次运行

---

### B6 · Coordinator（团长）

`P0` / 1.5 周 / 依赖 B4 B5

**背景**
抄 WorkBuddy 主理人的四项职责：建团、派活、中转、收口。**团长不干活**——它没有业务工具，只有协调工具。

**操作步骤**

1. `core/agents/coordinator.py`：

```python
"""Coordinator：专家团团长。

职责（抄腾讯 WorkBuddy 专家团主理人，见 PHASE-B §2.3）：
  ① 建团   只有团长能建团，成员不得创建子团队（DB6）
  ② 派活   按 SOP 阶段下发自包含任务
  ③ 中转   所有跨成员消息必经此处（DB2）
  ④ 收口   汇总产出，决定是否进入下一阶段

团长自己**不写代码、不调业务工具**。它的工具集是空的，只能调协调动作。
这是刻意的：团长一旦开始干活，就会和成员抢上下文，而且它的上下文是全局
最宝贵的。
"""

class Coordinator:
    async def run_team(self, team: TeamSpec, user_input: str) -> str:
        """跑完一整支专家团。"""
        self._budget.start(team)
        self._emit(AgentEvent(phase="team_created", ...))

        sop = SopMachine(team)
        while (stage := sop.current_stage()) is not None:
            self._budget.check()               # 超预算直接抛，见 B9

            # 任务预检：能力匹配（抄 WorkBuddy 的"任务预检"）
            self._precheck(stage)

            result = await self._dispatch(stage)

            # 机械验证门先跑（DB5），过不了不花审计的 token
            if stage.verify_before_next:
                verdict = self._verifier.run(stage, result)
                if not verdict.passed:
                    result.ok = False
                    result.error = "; ".join(verdict.findings)

            self._blackboard.put(stage.output_key, result.answer, stage.role)
            nxt = sop.advance(ok=result.ok)
            if nxt is None:
                break

        return self._synthesize(sop.history())
```

2. **`_precheck`**（抄 WorkBuddy 的"任务预检"）：派发前校验目标角色的工具集能否胜任该阶段。例如某阶段要写文件，但该角色的 `tools` 里没有写工具——**在派发前就报错**，而不是让它跑一遍再失败。

3. **`_dispatch` 下发的必须是自包含任务**（Anthropic 建议）：目标、期望输出格式、可用工具清单、完成判据、可见的黑板 key。团长的对话历史**不传给成员**（抄 CodeBuddy：成员有独立上下文窗口）。

4. **LLM 决策点只有一处**：某阶段失败、`next_on_failure` 需要在多个候选中选时。这一处要 `_emit` 一个显式事件，进 trace。其余全部是状态机。

5. `tests/test_agents/test_coordinator.py` 用 mock runtime 覆盖：正常走完 SOP、某阶段失败重试、机械验证打回、预检拦截、成员不能建团、团长工具集为空。

**完成判据**
- [ ] 团长的工具集是空的（写一个显式断言）
- [ ] 预检能在派发前拦住不胜任的角色
- [ ] 成员尝试建团会被拒绝
- [ ] 唯一的 LLM 决策点有显式事件
- [ ] 团长对话历史不泄漏给成员（写测试验证）

---

### B7 · 邮箱与黑板（消息中转）

`P0` / 1 周 / 依赖 B6

**背景**
实现 DB2：所有跨成员通信经团长。这是你要的"coder 找 architect 沟通"的落地方式。

**操作步骤**

1. `core/agents/mailbox.py`——**定向消息，append-only，每条都记录经手的团长**：

```python
"""成员邮箱。

所有消息都经团长中转（DB2，抄 WorkBuddy「所有跨成员的信息流必须经主理人
中转」）。刻意做成 append-only 且记录 relayed_by，理由是可追溯——多 Agent
系统最难调试的问题是"这个错误判断是谁传出去的"。

对照：腾讯 CodeBuddy Agent Teams 允许成员直连。我们不采纳，因为直连会让
委派树变成图，失去限流点和 trace 的父子关系。
"""
```

2. `ConsultRequest` 的处理流程（这是重点）：

```
coder 在实现时发现架构有问题
  → coder 发出 ConsultRequest(to_role="architect", question="...")
  → 团长校验：coder.may_consult 里有 architect 吗？
  → 团长校验：预算还够吗？咨询次数没超吗？
  → 团长记录到 mailbox（含 relayed_by）
  → 团长把问题 + 必要的黑板上下文转给 architect
  → architect 回答
  → 团长把答案转回 coder，同时写进黑板（这样后续阶段也能看到这次讨论）
```

**每一步都要有测试。** 特别是"`may_consult` 不含目标时被拒"和"咨询计入预算"。

3. `core/agents/blackboard.py`——阶段产出物，**append-only、带作者、按 key 授权可见**：
   - 只能 `put(key, value, author_role)` / `get(key)` / `list_keys()`
   - **不能删除、不能覆盖**（同 key 再 put 是追加新版本，读取取最新）
   - 成员只能看到 `stage.context_keys` 授权的 key，**默认不是全部可见**
   - 单 session 黑板总字节上限（默认 1 MB），超了拒绝写入并明确报错

4. **结构化产出而非自由对话**（抄 MetaGPT）：黑板条目应该是结构化文档（设计方案、任务清单、审计发现），不是聊天记录。在 `SopStage.expected_output` 里强制指定格式。

**完成判据**
- [ ] `may_consult` 校验有测试（含拒绝路径）
- [ ] 咨询计入预算和次数上限
- [ ] mailbox 每条消息都有 `relayed_by`
- [ ] 黑板 append-only 语义有测试
- [ ] `context_keys` 授权可见性有测试
- [ ] 黑板大小上限有测试

---

### B8 · 机械验证门

`P0` / 1 周 / 依赖 B4 B6

**背景**
决策 DB5。抄 karajan-code 的 *"deterministic first, then cross-AI review"* 和 local-ai-agent-orchestrator 的 mechanical verification。

**这一卡直接回答你说的"gpt 审计 grok 是否真的干完了"**：先用确定性检查回答"干完了没有"，过不了直接打回，**不花审计模型一分钱**；过了再让审计模型看"干得对不对"。

**操作步骤**

1. `core/agents/verifier.py`——**无 LLM，纯确定性**：

```python
"""机械验证门。

在 LLM 审计之前跑确定性检查。抄 karajan-code 的 "deterministic first, then
cross-AI review" 和 local-ai-agent-orchestrator 在 coder 与 reviewer 之间
插入的 mechanical verification。

省钱逻辑：机械检查过不了就直接打回 coder，审计模型一个 token 都不用花。
可靠性逻辑：「文件存在吗」「能编译吗」这类问题不该交给 LLM 判断。

本模块**不得引入任何 LLM 调用**。有测试守这条。
"""

class MechanicalVerifier:
    CHECKS = {
        "files_exist":     _check_files_exist,      # 声称创建的文件真的在吗
        "python_parses":   _check_python_parses,    # AST 能解析吗
        "json_parses":     _check_json_parses,
        "yaml_parses":     _check_yaml_parses,
        "lint_clean":      _check_ruff,             # ruff check 干净吗
        "tests_pass":      _check_pytest,           # 指定测试过吗
        "no_forbidden":    _check_forbidden_paths,  # 有没有碰不该碰的文件
        "diff_non_empty":  _check_diff_non_empty,   # 声称改了但 diff 是空的
    }
```

2. **`diff_non_empty` 这一条别漏。** "声称完成但什么都没改"是 LLM Agent 最常见的假完成模式。

3. 审计结论绑定哈希（抄 karajan）：

```python
def subject_hash(stage_output: str, diff: str) -> str:
    """计算被审对象的哈希。

    审计通过的是"这一份具体的产出"。coder 改完之后旧的通过结论自动失效，
    防止"审计通过 → 又偷偷改了 → 直接进入下一阶段"。
    """
    return hashlib.sha256((stage_output + "\n---\n" + diff).encode()).hexdigest()
```

`Coordinator` 在进入下一阶段前校验：当前产出的 hash 是否有匹配的 `VerdictRecord(passed=True)`。没有就不许过。

4. `SopStage.verify_before_next` 和 `audit_after_verify`（B3 已定义）在这里真正生效。

5. `tests/test_agents/test_verifier.py` 覆盖每一种检查的通过与失败，外加：

```python
def test_verifier_never_calls_an_llm():
    """机械验证门必须是纯确定性的。"""
    import inspect
    from core.agents import verifier
    src = inspect.getsource(verifier)
    for forbidden in ("ainvoke", "ChatOpenAI", "_llm", "get_role_prompt"):
        assert forbidden not in src, (
            f"verifier must stay LLM-free but references {forbidden!r}"
        )


def test_stale_verdict_is_rejected_after_output_changes():
    """产出变了，旧的审计通过结论必须失效。"""
```

**完成判据**
- [ ] 8 种机械检查都实现且有测试
- [ ] `test_verifier_never_calls_an_llm` 通过
- [ ] 审计结论绑定哈希，产出变更后旧结论失效
- [ ] `diff_non_empty` 能抓住"假完成"
- [ ] PR 描述里给出一个真实例子：机械检查打回节省了多少 token

---

### B9 · 成本熔断与失控保护

`P0` / 5d / 依赖 B6

**背景**
Anthropic 实测多 Agent 消耗 **15 倍 token**，并明确承认*"已发布的架构没有熔断器或单次运行上限……一个递归 spawn 更多子代理的子代理，或者一个返回超大结果的工具，能让单次查询的成本再翻 10 倍以上。"*

**这一卡不是优化，是功能的一部分。** 没有它，一次失控就能烧掉你的月度额度。

**操作步骤**

1. `core/agents/budget.py`：

```python
"""成本熔断。

Anthropic 实测：多 Agent 消耗约 15 倍于普通对话的 token，且他们公开承认
自己的架构没有熔断——一个失控的子代理能让单次成本再翻 10 倍。腾讯
WorkBuddy 专家团的积分消耗也是单专家的 3-5 倍。

四道闸门，任何一道触发都立即停止整个团队运行并返回已有产出。
"""

class BudgetGuard:
    def __init__(self, team: TeamSpec):
        self._token_budget = team.total_token_budget
        self._deadline = time.monotonic() + team.total_timeout_s
        self._max_delegations = team.max_delegations
        self._tokens_used = 0
        self._delegations = 0

    def check(self) -> None:
        """任何一道闸门触发就抛 BudgetExceeded。"""
        if self._tokens_used > self._token_budget:
            raise BudgetExceeded(f"token budget {self._token_budget} exhausted")
        if time.monotonic() > self._deadline:
            raise BudgetExceeded("wall-clock deadline reached")
        if self._delegations > self._max_delegations:
            raise BudgetExceeded(
                f"delegation count exceeded {self._max_delegations} — "
                f"likely a ping-pong loop between two stages"
            )
```

2. **第四道闸门在 Coordinator 里**：拒绝成员创建子团队（DB6）。这是防递归 spawn 的唯一手段。

3. **超预算不是崩溃，是优雅降级**：停止后续阶段，把黑板上已有的产出综合成一个部分答案返回给用户，并**明确告知"因为超出预算而提前停止，已完成 X/Y 个阶段"**。

4. 预算要能在 settings 里配，也要能按单次请求覆盖。

5. `tests/test_agents/test_budget_guard.py`（**B9 之后每张卡都要跑**）：

```python
def test_token_budget_stops_the_team():
def test_wall_clock_deadline_stops_the_team():
def test_delegation_count_catches_ping_pong_loop():
def test_member_cannot_create_a_subteam():
def test_budget_exceeded_returns_partial_result_not_crash():
def test_partial_result_tells_the_user_it_was_truncated():
```

**完成判据**
- [ ] 四道闸门都有测试
- [ ] 超预算返回部分结果而非崩溃
- [ ] 部分结果明确告知用户被截断了
- [ ] 预算可配置、可单次覆盖

---

### B10 · 难度路由（ModeRouter）

`P0` / 1 周 / 依赖 B6 B9

**背景**
你的设想：**一个模型判断任务难度 → 选择单 Agent / 多 Agent / 多 Agent+多模型**。

调研支持这个设计（多 Agent 15 倍成本、编码任务本就不太适合），但**纯 LLM 路由有已知问题**：延迟、成本、不确定性。所以做成**三级混合**，你要的"模型判难度"是第三级，且模型用户自选。

**操作步骤**

1. `core/agents/router.py`：

```python
"""执行模式路由。

三级决策，从便宜到贵，命中即返回：

  第 1 级 用户显式指令      /solo /team /team-multi 或 settings 强制
  第 2 级 确定性信号        涉及文件数、是否跨模块、任务树规模、是否只读
  第 3 级 LLM 判难度        可选，模型由用户在 settings 里指定

为什么不是纯 LLM 判断：调研显示基于 LLM 的路由会增加延迟、成本和不确定性
（见 PHASE-B §2.2）。大部分请求用确定性信号就能判准，把 LLM 留给真正含糊
的那一小部分。

为什么保留 LLM 那一级：确定性信号看不出"这个需求有多难"，只能看出"它涉及
多少东西"。含糊场景需要语义判断。
"""

class ExecutionMode(str, Enum):
    SOLO = "solo"                      # 现有单 Agent 路径，行为不变
    TEAM = "team"                      # 专家团，同一个模型
    TEAM_MULTI_MODEL = "team_multi"    # 专家团 + 每角色不同模型（Phase C）


@dataclass
class RoutingDecision:
    mode: ExecutionMode
    #: 哪一级做出的决定，进 trace 和 UI
    decided_by: Literal["user", "heuristic", "llm", "default"]
    reason: str
    #: 第 3 级用到的 token，计入预算
    tokens_used: int = 0
```

2. **第 2 级的确定性信号**（可配置阈值）：

| 信号 | 倾向 |
|---|---|
| 用户输入 < 一定长度且是提问句 | SOLO |
| 只涉及只读操作 | SOLO |
| 显式提到多个模块 / 多个文件 | TEAM |
| 任务分解后叶节点数超阈值 | TEAM |
| 涉及"重构"、"迁移"、"设计"等大范围动词 | TEAM |

3. **第 3 级的 LLM 判难度**：
   - 模型由 `settings.agents.router_model` 指定，**默认 `None` = 关闭这一级**
   - 用一个极短的 prompt，只要求输出 `solo` / `team` / `team_multi` 之一
   - 消耗计入 BudgetGuard
   - **超时或解析失败时退回第 2 级的结论**，不能因为路由失败而整个请求失败

4. **用户永远能覆盖**。斜杠命令：

| 命令 | 效果 |
|---|---|
| `/solo <任务>` | 强制单 Agent |
| `/team <任务>` | 强制专家团 |
| `/team-multi <任务>` | 强制专家团 + 多模型（Phase C 之后可用） |
| `/why-mode` | 打印上一次路由决策的依据 |

5. **默认关闭多 Agent**（DB7）：`settings.agents.enabled` 默认 `False`。关闭时 `ModeRouter` 恒返回 SOLO，**连第 2 级都不跑**（零开销）。

6. B1 里改名保留的 `_should_request_parallel_execution` 在这一卡**删除**，由 ModeRouter 取代。

**完成判据**
- [ ] 三级路由都有测试，含"第 3 级失败退回第 2 级"
- [ ] 四个斜杠命令可用
- [ ] `settings.agents.enabled=False` 时零开销（写一个断言不调用任何 LLM 的测试）
- [ ] 路由决策进 trace 和 `AgentEvent`
- [ ] `_should_request_parallel_execution` 已删除

---

### B11 · 内置专家团：软件开发 SOP

`P1` / 1 周 / 依赖 B4–B10

**背景**
把前面的抽象验证一遍。**如果这支团配不出来，说明 AgentSpec / SopStage 的设计有问题。**

角色设置参考 MetaGPT（PM / Architect / PM / Engineer / QA）和 AgentMux（architect / coder / reviewer / researcher），按 RxyCode 的实际场景裁剪。

**操作步骤**

1. `core/agents/teams/software_dev.yaml`：

```yaml
# 内置专家团：软件开发。
#
# 角色设置参考 MetaGPT 的五角色 SOP 和 AgentMux 的四角色流水线，按 RxyCode
# 的编码场景裁剪。设计原则：
#   - 能写文件的角色只有 coder 一个
#   - verifier 是机械角色，不调 LLM
#   - 只有 coder 能咨询 architect（对应"实现时发现架构有问题"）
#   - 只有 auditor 能同时咨询 architect 和 coder（对应"审计发现问题要定位
#     是架构错还是实现错"）

name: software_dev
display_name: 软件开发专家团
description: 架构 → 实现 → 机械验证 → 审计 的四段流水线

members:
  - role: architect
    display_name: 架构师
    goal: 把需求转成可执行的实现方案，明确文件清单、接口和验收标准
    backstory: 你熟悉本仓库的模块边界与既有约定，倾向最小改动方案。
    constraints:
      - 不要写实现代码，只产出方案
      - 方案必须列出要改哪些文件、每个文件改什么
      - 方案必须给出可机械验证的验收标准
    prompt_stage: agent_architect
    tools: [read_file, grep, list_dir, codebase_search]
    memory_scope: private
    timeout_s: 300

  - role: coder
    display_name: 编码员
    goal: 严格按方案实现，不做方案外的改动
    backstory: 你按方案施工。遇到方案本身有问题时提出咨询，而不是自行改设计。
    constraints:
      - 不得偏离方案；方案有问题就咨询 architect
      - 不得修改测试文件的断言来让测试通过
    prompt_stage: agent_coder
    tools: null            # 全部工具，含写入与 shell
    may_consult: [architect]
    memory_scope: private
    timeout_s: 900

  - role: verifier
    display_name: 机械验证
    goal: 用确定性检查回答"到底干完了没有"
    mechanical: true       # 不调 LLM
    prompt_stage: ""       # 机械角色无 prompt
    tools: []
    timeout_s: 300

  - role: auditor
    display_name: 审计员
    goal: 在机械检查通过之后，判断"干得对不对"
    backstory: 你只读代码，不改代码。发现问题时要判断是方案错还是实现错。
    constraints:
      - 不得修改任何文件
      - 每条发现都要指出具体文件和行号
      - 要明确区分"方案问题"和"实现问题"
    prompt_stage: agent_auditor
    tools: [read_file, grep, list_dir, codebase_search]
    may_consult: [architect, coder]
    memory_scope: private
    timeout_s: 300

stages:
  - name: plan
    role: architect
    expected_output: |
      结构化实现方案，含：① 要改的文件清单 ② 每个文件的改动要点
      ③ 可机械验证的验收标准（哪些测试要过、哪些命令要成功）
    output_key: plan
    next_on_success: implement
    next_on_failure: null
    max_retries: 1

  - name: implement
    role: coder
    expected_output: 按方案完成的代码改动 + 改动摘要
    context_keys: [plan]
    output_key: implementation
    verify_before_next: [diff_non_empty, files_exist, python_parses, lint_clean]
    audit_after_verify: true
    next_on_success: audit
    next_on_failure: implement      # 机械检查失败原地重试
    max_retries: 2

  - name: audit
    role: auditor
    expected_output: |
      审计结论：通过 / 不通过。不通过时逐条列出问题，每条标注
      「方案问题」或「实现问题」，并给出文件和行号。
    context_keys: [plan, implementation]
    output_key: audit_report
    next_on_success: null           # 通过则结束
    next_on_failure: implement      # 不通过打回实现
    max_retries: 2

entry_stage: plan
total_token_budget: 500000
total_timeout_s: 1800
max_delegations: 20
```

2. 在 `core/prompts/templates.py` 加 `agent_architect` / `agent_coder` / `agent_auditor` 三个 stage 模板。**这时才真正用上 B1 保留的 `SUBAGENT_DECOMPOSE_TEMPLATE`**——architect 用它拆任务。

3. **核对工具名**：

```powershell
python -c "from tools.registry import default_registry; print(sorted(default_registry.list_names()))"
```

YAML 里每个名字都要在这个列表里，否则 B4 的构造校验会报错（这是**期望**行为）。

4. `tests/test_agents/test_e2e_team.py`：用 mock LLM 跑完整流水线，覆盖：
   - 一次通过（plan → implement → audit → done）
   - 机械检查失败原地重试
   - 审计不通过打回实现
   - 打回超过 max_retries 后整体失败
   - coder 咨询 architect 的完整往返
   - 超预算时的部分结果

**完成判据**
- [ ] 专家团能加载且通过 B3 的静态校验
- [ ] 三个 prompt stage 存在
- [ ] YAML 里的工具名全部有效
- [ ] 6 个端到端场景测试通过
- [ ] **auditor 确实不能改文件**（写一个显式测试）

---

### B12 · 观测：委派树与 trace

`P1` / 5d / 依赖 B6 B7

**背景**
调研显示协调失败占多 Agent 全部失败的 **36.94%**。观测不是锦上添花，是排查协调失败的唯一手段。

**操作步骤**

1. 扩展 `core/tracing.py`：span 加 `role`、`stage`、`delegation_depth`、`tokens`。
2. 委派、咨询、机械验证、审计各自是一个 span，父子关系反映真实的调用链。
3. `python -m core.tracing replay --session <id> --show-team` 输出：

```
session abc123   team=software_dev   mode=TEAM (decided_by=heuristic)
budget: 187k/500k tokens · 412s/1800s · 7/20 delegations

└─ plan · architect (12.3s, 4.2k tok)                          OK
   └─ implement · coder (45.2s, 18.7k tok)                     OK
      ├─ [consult] coder → architect "方案里没提到迁移脚本"      (6.1s, 2.3k tok)
      ├─ [tool] write_file × 3
      └─ [verify] diff_non_empty OK · files_exist OK
                  python_parses OK · lint_clean FAIL
         └─ implement · coder (retry 1) (22.8s, 9.1k tok)      OK
            └─ [verify] all OK
      └─ audit · auditor (9.8s, 3.4k tok)                       FAIL
         └─ 2 findings: 1 实现问题 / 1 方案问题
            └─ implement · coder (retry 2) (31.4s, 12.2k tok)  OK
               └─ audit · auditor (8.2s, 3.1k tok)              OK
```

4. `AgentEvent` 推给前端，CLI 和 Desktop 都能显示当前角色和阶段。

5. **同时做 Phase E 的 E3**（蒸馏数据埋点）。E3 要往 span 里加一组可选的原始 IO 记录，和这一卡改的是同一处代码——分两次改是浪费。见 `PHASE-E-PERSONA-AGENT-INTERFACE.md` §4 的 E3。

**完成判据**
- [ ] replay 能还原完整委派树，含咨询和验证
- [ ] 预算消耗在树顶可见
- [ ] 路由决策依据可见
- [ ] 前端能显示当前角色
- [ ] Phase E 的 E3 一并完成

---

### B13 · 客户端适配

`P1` / 1 周 / 依赖 B10 B12，依赖主计划 Phase 2

**背景**
你要求"无论 Desktop 前端还是 CLI 都要做适配"，以及"settings 里有开关，打开才需要填那么多"。

**操作步骤**

1. **Settings 分层**（这是你要的渐进式配置）：

```
[ ] 启用多 Agent 专家团                       ← 默认关闭
    └─ 打开后才显示：
       专家团        [软件开发 ▾]
       路由模式      ( ) 总是单 Agent
                     (•) 自动判断
                     ( ) 总是专家团
       难度判断模型  [不使用 ▾]                 ← 你要的"判难度的模型用户自选"
       token 预算    [500000]
       时长上限      [1800] 秒
       [ ] 启用多模型协作（每角色不同模型）      ← Phase C 才可用，现在置灰
```

**关闭时整块隐藏**，用户看不到任何多 Agent 相关配置。

2. **CLI（OpenTUI）**：
   - 四个斜杠命令（B10）
   - 运行时状态行显示 `[architect] 正在制定方案... 12.3s · 4.2k tok`
   - 阶段切换时打一行分隔
   - `/why-mode` 打印路由依据
   - 预算用量在状态行右侧显示 `187k/500k`

3. **Desktop**（如果主计划 Phase 3 已完成）：
   - 侧栏显示团队成员和当前阶段
   - 委派树可视化（B12 的 replay 输出的图形版）
   - 预算进度条，接近上限时变色

4. **协议**：`AgentEvent` 和 `RoutingDecision` 进 `protocol/`，重新生成 TS 类型。

**完成判据**
- [ ] Settings 开关关闭时看不到任何多 Agent 配置
- [ ] 四个斜杠命令可用
- [ ] CLI 能显示当前角色、阶段、预算
- [ ] 难度判断模型可在 settings 里选
- [ ] TS 类型已重新生成并提交

---

### B14 · 评测：诚实面对 15 倍成本

`P1` / 1 周 / 依赖 B11，依赖主计划 Phase 1

**背景**
Anthropic 说多 Agent 15 倍 token，且**编码任务本就不是多 Agent 的强项**。我们必须自己测出来到底值不值。

**操作步骤**

1. `evals/cli.py` 加 `--mode solo|team|auto`。
2. 新增检查类型：`role_participated`（某角色确实参与了）、`max_delegations`（委派没失控）、`verdict_bound`（审计结论绑定了正确的哈希）。
3. 产出三方对比矩阵：

```
Mode         Pass rate   Avg tokens   Avg duration   Avg cost   Delegations
solo            68%         9,870        41.7s        $0.09          —
team            ??%        ??,???        ??.?s        $?.??         ?.?
auto            ??%        ??,???        ??.?s        $?.??         ?.?
                            ↑ 如果 team 的 token 不是 solo 的 3-15 倍，
                              说明团队没真正跑起来，检查配置
```

4. **按任务类型分组看**。多 Agent 大概率在简单任务上更差更贵，在跨模块重构上才有优势。找出**分界线在哪**——这个分界线就是 B10 第 2 级启发式的阈值依据。

5. **诚实写结论。** 如果测下来多 Agent 在多数编码任务上不划算：
   - 写进 `docs/modules/agents.md`
   - 把默认保持关闭
   - 把 B10 的启发式阈值调高
   - **这不是失败，这是你省下的钱**

**完成判据**
- [ ] 三方矩阵已产出并提交
- [ ] 按任务类型分组的分析已完成
- [ ] 分界线写进 B10 的启发式阈值
- [ ] 结论（含负面结论）写进文档

---

### B15 · 文档

`P1` / 5d / 依赖 B1–B14

**操作步骤**

1. 新建 `docs/modules/agents.md`：
   - §2 的调研结论摘要（抄了谁、为什么不抄别的）
   - 七条设计约束（§3.2）及理由
   - `AgentSpec` / `TeamSpec` / `SopStage` 字段语义，含 `extra` 的命名空间约定
   - 团长的四项职责与唯一的 LLM 决策点
   - 机械验证门的 8 种检查
   - 四道成本闸门
   - **B14 的评测结论，明确写"什么时候不该用多 Agent"**
   - 加角色 / 加专家团 / 加 SOP 的步骤（照抄 §6）
   - **Phase E 的 E6 要求的"程序化构造 AgentSpec"一节**
2. 更新 `docs/modules/core.md`、`tools.md`（per-agent 注册表）、`cache.md`（agent namespace）、`memory.md`（memory_scope）、`recovery.md`（breaker key）、`frontend.md`（settings 分层）。
3. 更新 `AGENTS.md` 架构图。
4. 更新主计划的 Phase 表。

---

## §5 Phase B 出口检查

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q --timeout=900
python -m pytest tests/test_agents -q
python -m evals.cli run --backend agent --mode solo --compare-baseline evals\baselines\latest-agent.json
python -m evals.cli run --backend agent --mode team --save-baseline
Select-String -Path *.py,core\*.py,tools\*.py -Pattern "_run_with_subagents|SubAgentV2|agent_tool|_should_use_subagents" -Recurse
```

**Phase B 完成的定义：**
- 前 5 条全绿，**`--mode solo` 零回归**
- 最后一条无输出（死代码已清）
- 软件开发专家团端到端跑得通，含咨询、机械验证打回、审计打回
- 四道成本闸门都能触发且优雅降级
- 三级难度路由可用，用户能覆盖，默认关闭
- **B14 的评测矩阵已产出，结论（含负面结论）写进了文档**
- `docs/modules/agents.md` 可独立指导加新角色和新专家团
- **Phase E 的 E1 / E2 / E3 / E5 / E6 五张预留卡已完成**（见 `PHASE-E-PERSONA-AGENT-INTERFACE.md` §4）

---

## §6 扩展手册

### 6.1 加一个新角色

1. **先回答三个问题**，答不上来就不要加：这个角色需要哪些工具（能不能只给只读）？它需要咨询谁（`may_consult` 越短越好）？它的记忆要不要共享（默认 private）？
2. `core/prompts/templates.py` 加 `agent_<role>` 模板 + `few_shot.py` 至少 1 个示例
3. 在专家团 YAML 的 `members` 里加 `AgentSpec`
4. 核对工具名：`python -c "from tools.registry import default_registry; print(sorted(default_registry.list_names()))"`
5. `tests/test_agents/test_isolation.py` 加一条，断言新角色工具集受限
6. 跑评测对比加角色前后。**加了反而更差就不要加**

### 6.2 加一支新专家团

1. 复制 `core/agents/teams/software_dev.yaml`
2. **先画 SOP 状态图**（纸上画），确认有终点、没有无出口的环
3. 静态校验：`python -c "from pathlib import Path; from core.agents.spec import load_team; load_team(Path('core/agents/teams/<新团>.yaml')); print('ok')"`
4. 端到端测试用 mock LLM 先跑通
5. 设一个**保守的** `total_token_budget`，跑几次真实任务看实际消耗再调

### 6.3 加一种机械检查

1. `core/agents/verifier.py` 的 `CHECKS` 加一项
2. **必须是纯确定性的**——`test_verifier_never_calls_an_llm` 会守这条
3. 在 `SopStage.verify_before_next` 里引用
4. 加通过与失败两个测试

### 6.4 调整难度路由阈值

阈值来自 B14 的评测数据，不要拍脑袋改。改之前重跑：

```powershell
python -m evals.cli run --backend agent --mode solo --save-baseline
python -m evals.cli run --backend agent --mode team --save-baseline
```

找到"team 开始比 solo 划算"的那条线。

---

## §7 与后续 Phase 的接口

| 预留 | 给谁 | 约束 |
|---|---|---|
| `AgentSpec.model` | **Phase C** 多模型协作 | Phase B 全部留 `None`（同模型）。Phase C 才按角色配不同模型 |
| `ExecutionMode.TEAM_MULTI_MODEL` | **Phase C** | 枚举值先占上，Phase B 阶段路由到它会明确报错 |
| `AgentSpec.extra` 的命名空间约定 | **Phase C / D / E** | `pair.*` / `vision.*` / `persona.*`，见 Phase E 的 E2 |
| Provider 无状态单例（Phase A 的 DC2） | **Phase C** | 多个 runtime 会并发调用同一 provider 实例 |
| `Blackboard` 条目的 value 是 `str` | **Phase D** 多模态 | Phase D 会拓宽成 content block，**现在不要在别处假设它一定是纯文本** |
| `AgentSpec.tools` 的作用域机制 | **Phase E** PersonaAgent | Persona 可能需要**运行时**替换工具集而不只是构造时。**如果你倾向要这个能力，在 B4 就把 `_build_scoped_registry` 设计成可运行时替换的，成本几乎为零**；Phase B 做完再改要动 `AgentRuntime` 核心。见 Phase E §6.1 |
| `TeamSpec` 的 YAML 加载路径 | **Phase E** | 除了内置的 `core/agents/teams/`，还要扫用户级目录 `~/.rxycode/teams/` |
| `VerdictRecord` + 机械验证结果 | **Phase E** 蒸馏 | 这两个是蒸馏质量标注的来源（Phase E 的 E4）。**不要把它们做成只在内存里存在的临时对象** |
