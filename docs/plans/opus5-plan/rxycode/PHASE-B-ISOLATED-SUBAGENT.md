# Phase B · 隔离式子代理（OpenCode-style Subagent Runtime）

> **在整条路线中的位置**：本文件是 [`00-EXECUTION-PLAN.md`](./00-EXECUTION-PLAN.md) 的后续扩展，编号为新的 Phase B。它位于 Phase A 之后，先提供真正的 Child Session / Subagent Runtime，再由 Phase C 组装专家团，由 Phase D 提供完整 Desktop 工作台，由 Phase E 接入多模型协作。
> **前置条件**：主计划 Phase 0/1/2 与 [`PHASE-A-MODEL-ADAPTATION-LAYER.md`](./PHASE-A-MODEL-ADAPTATION-LAYER.md) 全部完成；Phase A 的模型能力、Provider 适配和结构化输出契约必须稳定。
> **后继**：[`PHASE-C-MULTI-AGENT-ORCHESTRATION.md`](./PHASE-C-MULTI-AGENT-ORCHESTRATION.md) 只能在本 Phase 的 Child Session、权限、预算和结果协议之上实现 Coordinator 与专家团；[`PHASE-D-RXYCODE-DESKTOP.md`](./PHASE-D-RXYCODE-DESKTOP.md) 消费本 Phase 的子会话事件和能力声明。
>
> **一句话目标**：把“主 Agent 里再调用一个函数”的伪子代理，变成拥有独立会话、独立上下文、独立工具/权限、独立预算和独立生命周期的真实 Child Agent；Primary 只能通过结构化任务和结构化结果与它交互。
>
> **执行模型**：本 Phase 的代码由 **Composer 2.5 主写并收口**，但不是单模型独占开发。Grok 4.5 可按任务卡参与 OpenCode 资料核查、子会话 UI 的视觉验收和明确标注的多模态前端环节；Sonnet 5 可按任务卡做 diff 预审。Composer 仍然负责所有代码主线、协议决策、合并和最终验收。权威分工见 [`../MODEL-ASSIGNMENT.md`](../MODEL-ASSIGNMENT.md)、[`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) 和 [`../GROK-FRONTEND-PLAYBOOK.md`](../GROK-FRONTEND-PLAYBOOK.md)。
> **基线日期**：2026-08-02　**预计工时**：8–12 周（按任务卡，不把人的日历估计当作 Agent 速度承诺）　**任务卡**：B1–B14

---

## 目录

| 章节 | 内容 |
|---|---|
| [§0 执行手册](#0-执行手册必读) | Composer 主写、多模型协作、卡片循环、硬约束 |
| [§1 现状真相](#1-现状真相) | 当前项目为什么不是真正的子代理 |
| [§2 OpenCode 研究结论](#2-opencode-研究结论) | 官方文档中的角色、触发、会话、权限和递归控制 |
| [§3 RxyCode 目标架构](#3-rxycode-目标架构) | Primary、Child Session、Runtime、Task Tool 的边界 |
| [§4 配置与触发契约](#4-配置与触发契约) | JSON/Markdown Agent 定义、`@`、Task、`subtask` |
| [§5 任务卡 B1–B14](#5-任务卡-b1b14) | 可直接执行的实现卡、文件边界和验收命令 |
| [§6 安全、成本和失败处理](#6-安全成本和失败处理) | 权限、递归、预算、取消、写入冲突 |
| [§7 CLI/Desktop 体验](#7-clidesktop-体验) | 主子会话导航、事件和审计显示 |
| [§8 测试与验收](#8-测试与验收) | 单元、协议、E2E、视觉和出口标准 |
| [§9 与后续 Phase 的接口](#9-与后续-phase-的接口) | Phase C/D/E/F/G 和 LinkAgent 的依赖 |
| [附录 A 示例文件](#附录-a示例文件) | Agent 配置、Task 调用和结果示例 |
| [附录 B 开发交接模板](#附录-b开发交接模板) | Composer、Grok、Sonnet 的协作方式 |

---

## §0 执行手册（必读）

### 0.1 这不是“Composer 单独开发”

现有文档的真实模型是：**Composer 2.5 主写全部代码，其他模型在明确边界内协作**。本 Phase 必须继承这个模型，不能因为子代理本身是多 Agent 功能，就误把“运行时多个 Agent”理解成“开发时只能一个模型”。

| 角色 | 可以做什么 | 不可以做什么 |
|---|---|---|
| **Composer 2.5** | 主写 Python、协议 schema、CLI、OpenTUI、Electron/React/TypeScript、测试和文档；决定接口；合并辅助产出；执行最终验收 | 不能把未经验证的辅助产出直接当作契约 |
| **Grok 4.5** | 查阅 OpenCode 官方资料；对任务卡标注的 Desktop/CLI 子会话 UI 做截图核对、交互观察和图片类前端辅助；提交可复现的问题清单或小范围前端 patch | 不改 `core/`、`protocol/`、`appserver/`、权限核心、预算核心；不独立收口后端卡 |
| **Sonnet 5（可选）** | 对隔离边界、权限旁路、事件顺序、递归深度、预算和 diff 做独立预审 | 不代替 Composer 实现；预审结论不等于通过 |

**“Composer 主写”包含三层含义**：

1. Composer 拥有代码主线和最终接口决策权。
2. Composer 可以写任何目录，包括前端；Grok 没有前端文件所有权。
3. Grok/Sonnet 的产出必须回到 Composer 的任务卡，由 Composer 复核、合并、测试并提交。

### 0.2 每张卡固定执行七步

```text
1. LOCATE   用 rg/Grep 找真实符号、调用链、测试和协议消费者
2. READ     读目标符号上下文、相邻测试、对应主计划和前后 Phase 契约
3. WRITE    只写本卡白名单文件；先写 schema/测试，再写实现
4. LINT     运行 ruff、格式化、TypeScript typecheck 或本卡指定静态检查
5. TEST     运行本卡验收命令和受影响回归测试
6. CHECK    对照完成判据、git diff、事件/权限/隔离边界逐条检查
7. COMMIT   一张卡一个可回滚 commit；commit message 写清卡号
```

遇到文档与代码冲突时必须停止，不得自行扩大范围：

```text
STOP: B<编号> 无法按卡执行
- 文档预期：<文件/符号/行为>
- 代码事实：<rg/测试得到的事实>
- 冲突位置：<签名、schema、事件、权限或测试>
- 已修改：无 / <明确列出>
- 需要确认：<一个最小决策>
```

### 0.3 开工前自检

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests -q -x --timeout=120
Test-Path evals\baselines\latest-agent.json
Test-Path protocol\schema.json
Test-Path appserver
git status --short
```

已有用户修改必须先记录，不能用 `reset`、`checkout`、清目录或批量覆盖来“整理工作区”。

### 0.4 八条硬约束

| 编号 | 硬约束 | 违反时的判定 |
|---|---|---|
| SB1 | **子代理必须拥有独立 Child Session**，不能只在 Primary 上重新调用 `run()` | 伪子代理，不得合并 |
| SB2 | **Primary/Child 上下文隔离**：Child 默认只接收结构化任务、显式上下文引用和允许的附件 | 发现 Child 可读完整 Primary history 时失败 |
| SB3 | **运行时隔离**：每个 Child 拥有独立 ToolRegistry、PermissionPolicy、memory/cache namespace、budget 和 cancellation scope | 共享 singleton 只能作为显式只读 Provider，不得共享可变状态 |
| SB4 | **结果只能走协议回传**：Child 不得直接写 Primary 消息、状态对象、工具队列或内存 | 任何跨 session 直接引用都是失败 |
| SB5 | **权限最小化**：`read`、`edit`、`bash`、`task`、`webfetch`、`websearch`、`external_directory` 等按 Agent 配置和审批决定 | 默认放开全部工具不通过 |
| SB6 | **递归有上限**：Child 默认不能继续派生 Child；允许时必须同时满足 `permission.task`、深度上限、预算和并发上限 | 出现无界子代理树即失败 |
| SB7 | **写入有租约**：并行 Child 不能无协调地修改同一文件；写入必须拥有 WorkspaceScope/lease 或被降级为只读 | 同文件静默覆盖不通过 |
| SB8 | **入口统一**：CLI、OpenTUI、Desktop、未来 LinkAgent 都使用同一套 `TaskRequest`、`ChildSessionEvent`、`TaskResult` | 任一客户端复制一套子代理逻辑不通过 |

### 0.5 非目标

本 Phase 不实现以下内容：

- Phase C 的专家团 Coordinator、SOP、Mailbox、Blackboard 和角色编排策略；
- Phase E 的每角色不同模型、结对编程和仲裁；
- Phase D 的完整 Diff/Review 工作台；本 Phase 只提供事件、能力和审计基础；
- OpenCode 的源代码复制，或引入 CrewAI/AutoGen 等第三方编排框架；
- 把普通 `TaskTree` 并行节点重新命名为“子代理”；
- PersonaAgent 的自动激活、经验蒸馏和 LinkAgent 的业务视图。

---

## §1 现状真相

### 1.1 当前代码中“子代理”是兼容遗留，不是真正隔离

开工时必须实测，不能只根据符号名称下结论。当前应重点检查：

| 位置 | 现象 | 结论 |
|---|---|---|
| `core/agent_v2.py:2920` (`_run_with_subagents`, 当前快照) | 可能是禁用路径或异常提示 | 不能作为生产入口 |
| `core/agent_v2.py:3722` (`SubAgentV2`, 当前快照) | 任务重新交给父 `AgentV2.run()` | 没有 Child Session、独立 history、独立权限 |
| `tools/agent_tool.py` | 通过 compose 方式构造 Agent | 旧兼容工具，不等于隔离式 Task Tool |
| `tools/task_tool.py` | 管理当前 session 的任务清单和状态 | 已有 Task 管理工具，不得误当作子代理派发入口 |
| `core/graph.py` | `asyncio.gather` 或 TaskTree 节点并行 | 是同一个 Agent 的并行任务，不是隔离 Agent |
| `core/prompts/templates.py` | 存在 subagent decomposition prompt | 只是提示词，不能证明有运行时边界 |

B1 必须用 `rg` 找到真实调用者，并以测试结果决定保留、适配还是删除。未经验证，不得把以上任何符号直接当作目标架构的一部分。

### 1.2 普通并行和真正子代理的区别

```text
当前伪并行：
Primary Session
└── AgentV2 / shared history / shared tools / shared budget
    ├── TaskTree leaf A
    ├── TaskTree leaf B
    └── TaskTree leaf C

目标：
Primary Session
├── Child Session A / AgentRuntime A / policy A / budget A / memory A
├── Child Session B / AgentRuntime B / policy B / budget B / memory B
└── Child Session C / AgentRuntime C / policy C / budget C / memory C
```

判断标准不是是否用了 `asyncio.gather`，而是以下 namespace 是否独立：

1. `session_id` 和 parent/child relationship；
2. conversation/context history；
3. memory namespace；
4. cache namespace；
5. ToolRegistry 和 PermissionPolicy；
6. cancellation、budget、trace 和 audit scope。

### 1.3 为什么必须先做隔离式子代理

- Phase C 的专家团应该是多个 Child Runtime 的组合，而不是再复制一套运行核心。
- Phase D 需要在 Desktop 中展示 parent/child session tree、工具调用和审批结果。
- Phase E 的模型切换必须发生在 Child Runtime 创建阶段，不能从 Renderer 或 prompt 偷改。
- LinkAgent 的桌面扩展需要消费稳定的子会话事件，而不应读取 RxyCode 的内部对象。
- 审计必须能回答“哪个 Child 在什么权限下，对哪个 workspace 做了什么”，共享父状态无法可靠回答。

---

## §2 OpenCode 研究结论

本节只借鉴 OpenCode 官方文档公开的**用户可观察行为和配置契约**，不声称复制其内部实现。实现前必须重新打开官方页面核对当前内容：

- [OpenCode Agents](https://opencode.ai/docs/agents)
- [OpenCode Permissions](https://opencode.ai/docs/permissions)
- [OpenCode Commands](https://opencode.ai/docs/commands)
- [OpenCode Config](https://opencode.ai/docs/config)

### 2.1 Primary 和 Subagent 是两种不同角色

OpenCode 将 Agent 分成 Primary 和 Subagent：Primary 是用户直接交互的主助手，Subagent 是被 Primary 针对专门任务调用的辅助 Agent；Subagent 也可以通过 `@` 被用户直接调用。这个区分在 RxyCode 中对应：

| OpenCode 行为 | RxyCode 契约 |
|---|---|
| Primary 保持用户主会话 | `PrimarySession` 持有用户可见 Thread |
| Subagent 有自己的任务上下文 | `ChildSession` 只接收 `ContextEnvelope` |
| Subagent 的工具/模式可单独配置 | `AgentDefinition` 编译成独立 `PermissionPolicy` 和 `ToolRegistry` |
| 结果返回 Primary | 只通过 `TaskResult` 和事件协议回传 |

### 2.2 三种触发方式

OpenCode 官方文档描述的行为应在 RxyCode 中统一成三条入口：

| 触发方式 | OpenCode 语义 | RxyCode 实现 |
|---|---|---|
| Primary 自动调用 | Primary 根据 Subagent 的 `description` 选择并通过 Task 工具派发 | `Task Tool` 必须显式生成 `TaskRequest`，并写入 `trigger=automatic` |
| 用户 `@` 调用 | 用户在输入中选择某个 Subagent 并直接委派任务 | CLI/OpenTUI/Desktop 共用 `agent/invoke`，写入 `trigger=mention` |
| Command 的 `subtask` | 某个命令配置为子任务，不把中间过程混入 Primary | `subtask=true` 强制创建 Child Session，写入 `trigger=command` |

**禁止的第四种入口**：在某个前端组件里直接实例化 `AgentV2` 并调用 `run()`。这会绕过统一权限、审计、预算和 session tree。

### 2.3 Agent 定义的字段

OpenCode 文档公开了 JSON 配置与 Markdown Agent 文件两种定义方式，并支持 `description`、`mode`、`model`、`prompt`、`steps`、`permission`、`hidden`、`permission.task` 和 `subagent_depth` 等概念。`subtask=true` 是 Commands 文档中的官方布尔配置；RxyCode 的默认递归深度和内部字段命名属于本项目策略，不能倒写成 OpenCode 的实现细节。RxyCode 对应字段如下：

| 字段 | 必需 | 作用 |
|---|---:|---|
| `id` | 是 | 稳定机器标识，不使用显示名称作为主键 |
| `description` | 是 | 给自动触发器匹配任务的短说明 |
| `mode` | 是 | `primary` / `subagent` / `all` |
| `model` | 否 | 默认继承 Primary；Phase E 才允许按角色覆盖 |
| `prompt` | 否 | Agent 专用 system instructions，不可替代结构化任务 |
| `steps` | 否 | 单次 Child 的 agentic iteration 上限 |
| `permission` | 是 | 工具级 `allow` / `ask` / `deny` 规则 |
| `hidden` | 否 | 是否从 `@` 列表隐藏；不影响 Task Tool 显式调用 |
| `permission.task` | 否 | 按目标 Agent id 允许或拒绝该 Agent 继续启动哪些 Subagent；唯一公开的 task 权限入口 |
| `task_permission` | 内部 | 从 `permission.task` 编译出的规范化策略对象；不是第二个用户配置来源 |
| `subagent_depth` | 否 | 子代理递归深度上限；RxyCode 默认 0，较 OpenCode 默认 1 更严格 |
| `workspace_scope` | 否 | `read_only` / `leased_write` / `isolated_worktree` |

**配置来源唯一性**：JSON/Markdown 只允许在 `permission.task` 写 task 权限。顶层 `task_permission` 不属于公开 schema；如果解析器同时发现两处配置，必须以结构化配置错误拒绝，而不是猜测优先级或合并。Python `AgentDefinition.task_permission` 只表示归一化后的内部快照。

### 2.4 权限模型不能只做一个布尔开关

OpenCode 官方权限文档采用 `allow`、`ask`、`deny` 三态，并支持按工具输入的 glob/pattern 匹配。RxyCode 必须保留以下性质：

1. Agent 级规则覆盖全局默认规则，但不能绕过系统硬拒绝。
2. 同一工具多条规则按确定顺序匹配，规则优先级写进测试，不依赖字典遍历顺序。
3. `task` 权限按目标 Agent id 匹配，不得用“允许 task”代表允许任意递归。
4. `external_directory` 单独控制工作区外路径，不能从 `read` 或 `edit` 自动推断。
5. `ask` 必须生成可追踪的审批请求，审批决定绑定 `session_id`、`tool_call_id`、路径和规则版本。

建议的匹配表达式：

```yaml
permission:
  read:
    "src/**": allow
    "**/*.secret": deny
  edit:
    "tests/**": allow
    "src/**": ask
  bash:
    "pytest *": allow
    "git push *": deny
  task:
    "explore": allow
    "general": deny
  external_directory: deny
```

### 2.5 Child Session 导航是产品能力，不是实现细节

OpenCode 文档描述了进入 Child、循环 Child、返回 Parent 的导航体验。RxyCode 的 Desktop 与 OpenTUI 必须保留：

- parent/child 树，而不是把所有 Child 输出折叠为普通文本；
- Child 的独立状态、工具事件、审批事件、预算和失败原因；
- 从 Child 返回 Parent 后仍可重新打开 Child 的历史结果；
- 主会话取消时能递归取消尚未完成的 Child；
- Child 完成后 Primary 只接收摘要和结构化产物，不自动吞入全部内部 history。

### 2.6 借鉴边界

OpenCode 官方文档公开的是行为和配置，不是完整内部 runtime 实现。本 Phase 只借鉴：Primary/Subagent 二分、`@`、Task、Markdown/JSON Agent 定义、权限三态、task permission、child navigation、steps/depth 限制。RxyCode 的 Session、协议、审计、workspace lease 必须按本项目现有 Phase 2/Phase A 约束实现。

---

## §3 RxyCode 目标架构

### 3.1 分层总览

```text
CLI / OpenTUI / Desktop / LinkAgent
                │  TaskRequest / agent/invoke
                ▼
        PrimarySessionController
                │  creates child session
                ▼
          ChildSessionManager
        ┌───────┼────────┐
        ▼       ▼        ▼
  AgentRuntime A  AgentRuntime B  AgentRuntime C
   policy/tools     policy/tools    policy/tools
   budget/trace     budget/trace    budget/trace
        │       │        │
        └───────┴────────┘
                │  ChildSessionEvent / TaskResult
                ▼
        AppServer protocol event log
```

### 3.2 核心对象

```python
@dataclass(frozen=True)
class AgentDefinition:
    id: str
    description: str
    mode: Literal["primary", "subagent", "all"]
    prompt: str | None
    model: str | None
    steps: int | None
    permission: PermissionSpec
    task_permission: TaskPermissionSpec  # normalized from permission.task; not public input
    hidden: bool = False
    subagent_depth: int = 0
    workspace_scope: Literal["read_only", "leased_write", "isolated_worktree"] = "read_only"
    extra: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class TaskRequest:
    request_id: str
    parent_session_id: str
    agent_id: str
    prompt: str
    context: ContextEnvelope
    trigger: Literal["automatic", "mention", "command", "team"]
    output_schema: str | None
    budget: BudgetSpec
    workspace: WorkspaceScope
    allow_child_tasks: bool = False

@dataclass(frozen=True)
class TaskResult:
    request_id: str
    child_session_id: str
    status: Literal["completed", "failed", "cancelled", "denied", "timed_out"]
    summary: str
    artifacts: tuple[ArtifactRef, ...]
    evidence: tuple[EvidenceRef, ...]
    usage: UsageRecord
    error: ErrorRecord | None
```

> **术语约定**：Phase B 对后续 Phase 导出的运行时名称是 `ChildRuntime`；内部实现可以把通用实现类命名为 `AgentRuntime`，但必须从 `core/subagents/` 导出稳定的 `ChildRuntime` facade。Phase C 的专家角色只能依赖这个 facade，不能依赖私有实现类。

字段名可以按现有协议规范调整，但语义不能省略。`TaskResult.summary` 不是把完整 history 偷塞回 Primary；`artifacts` 和 `evidence` 必须可独立审计。

### 3.3 文件边界

目标目录建议如下。若现有 Phase 2 目录不同，B1 先定位真实边界，再由 Composer 更新本表，不得在多个目录各造一份 runtime：

```text
protocol/
  subagents.py                 # AgentDefinition / TaskRequest / TaskResult / events
  subagents_schema.json        # 机器可校验的协议 schema
core/
  subagents/
    __init__.py
    definitions.py              # AgentDefinition 加载与静态校验
    config_loader.py            # JSON/Markdown/YAML 归一化
    sessions.py                 # Primary/Child Session 生命周期
    runtime.py                  # 隔离 AgentRuntime，导出 ChildRuntime facade
    context.py                  # ContextEnvelope 构造与脱敏
    permissions.py               # allow/ask/deny 与 task permission
    workspace.py                 # WorkspaceScope 与写租约
    budget.py                    # steps/token/time/concurrency guard
    events.py                    # ChildSessionEvent 与持久化
    manager.py                   # ChildSessionManager / cancellation tree
tools/
  subagent_task_tool.py         # 唯一子代理派发 Task Tool 入口
  task_tool.py                  # 已有任务清单工具；不得与子代理 Task Tool 混名或覆盖
  agent_invoke.py               # CLI/Desktop 共用的 @ 触发适配
appserver/
  subagent_routes.py            # JSON-RPC 方法、通知和能力发现
frontend/
  protocol-client/
  desktop-app/
    src/subagents/              # 只做渲染和交互，不实现 runtime
tests/
  test_subagents/
```

`core/agents/` 如果在 Phase C 已经存在，只能作为专家角色 adapter；不能重新实现本节的 Child Runtime 隔离机制。

### 3.4 生命周期

```text
CREATED
  │ validate definition + context + permission + budget
  ▼
QUEUED ──cancel──► CANCELLED
  │ start
  ▼
RUNNING ──complete──► COMPLETED
  │  │  ├─failure──► FAILED
  │  │  ├─timeout──► TIMED_OUT
  │  │  └─deny─────► DENIED
  ▼
FINALIZING
  │ persist result + release lease + emit terminal event
  ▼
TERMINATED
```

终态必须幂等。重复收到 `cancel`、重复恢复事件或重复写入终态，不能产生两个结果或重复扣除预算。

---

## §4 配置与触发契约

### 4.1 JSON Agent 定义

```json
{
  "id": "explore",
  "description": "只读探索代码库并返回文件、符号和证据",
  "mode": "subagent",
  "model": null,
  "prompt": "你是只读探索 Agent。只返回证据，不修改文件。",
  "steps": 12,
  "permission": {
    "read": {"**": "allow"},
    "edit": {"**": "deny"},
    "bash": {"pytest *": "allow", "**": "deny"},
    "task": {"**": "deny"},
    "external_directory": "deny"
  },
  "hidden": false,
  "subagent_depth": 0,
  "workspace_scope": "read_only"
}
```

这里的 `permission.task` 是 task 权限的唯一公开来源。不得再添加顶层 `task_permission`；`AgentDefinition.task_permission` 只由加载器从 `permission.task` 生成，双写时必须 fail closed。

### 4.2 Markdown Agent 定义

Markdown 适合保存长 system prompt，但 frontmatter 必须先经过同一 `AgentDefinition` 校验：

```markdown
---
id: reviewer
description: 审查 diff、测试和权限边界，不写文件
mode: subagent
steps: 10
permission:
  read: allow
  edit: deny
  bash: ask
  task: deny
workspace_scope: read_only
---

你是 RxyCode 的只读审查 Agent。

输出必须包含：
1. 结论；
2. 证据文件和行号；
3. 风险级别；
4. 不修改文件的建议。
```

JSON、Markdown 和未来用户级目录的定义，最终都必须进入同一个 `AgentDefinitionRegistry`。禁止三个格式各有一套默认权限。

### 4.3 `@` 手动触发

用户输入：

```text
@explore 查找所有会修改 workspace 的工具，并列出它们的权限要求。
```

解析结果：

```json
{
  "method": "agent/invoke",
  "params": {
    "agent_id": "explore",
    "prompt": "查找所有会修改 workspace 的工具，并列出它们的权限要求。",
    "trigger": "mention",
    "parent_session_id": "ses_primary_123"
  }
}
```

要求：

- autocomplete 只展示 `mode in {subagent, all}` 且 `hidden=false` 的 Agent；
- 被隐藏的 Agent 仍可由 Task Tool 显式调用；
- 不存在、模式不匹配或权限不允许时，返回结构化错误，不创建半残 Child；
- mention 的显示名称不是 id，事件中永远记录稳定 `agent_id`。

### 4.4 Task Tool 自动触发

Primary 的模型可以提出 Task Tool 调用，但执行层不能信任模型直接给出的权限、预算或 workspace：

```json
{
  "tool": "task",
  "arguments": {
    "agent_id": "explore",
    "description": "探索认证模块的调用关系",
    "prompt": "只读检查 core/auth.py、相关测试和配置，返回证据列表。",
    "context_refs": ["turn_42.item_7", "file:core/auth.py"],
    "output_schema": "ExplorationReport"
  }
}
```

执行器必须：

1. 校验 `agent_id`、Agent mode 和规范化后的 `permission.task`；
2. 从 Primary 的允许上下文引用构造 `ContextEnvelope`；
3. 由服务端计算 budget、workspace scope 和实际 permission；
4. 创建 Child Session 并发出 `child_session/created`；
5. 只把 `TaskResult` 摘要回传给 Primary。

### 4.5 Command 的 `subtask=true`

```json
{
  "id": "review-diff",
  "description": "对当前 diff 做只读审查",
  "subtask": true,
  "agent": "reviewer",
  "permission": {
    "task": "deny"
  }
}
```

`subtask=true` 不是 UI 标签，而是运行时硬契约：命令执行必须走 `TaskRequest`，不能在 Primary 的消息循环内展开为普通 prompt。Command 结果仍以 Child Session 显示，便于 Desktop 审计和恢复。

### 4.6 ContextEnvelope：默认不复制完整 history

```json
{
  "parent_session_id": "ses_primary_123",
  "task": "只读探索认证模块",
  "references": [
    {"kind": "file", "path": "core/auth.py", "sha256": "..."},
    {"kind": "item", "id": "turn_42.item_7", "visibility": "summary"}
  ],
  "attachments": [],
  "redactions": ["secret", "api_key", "authorization"],
  "max_context_tokens": 12000
}
```

Context 构造器必须拒绝：

- 没有 parent session 的引用；
- 超出 workspace scope 的文件；
- Primary 未授权的完整私有消息；
- 过期或 sha256 不匹配的文件引用；
- 将 secret 作为普通文本复制给 Child。

---

## §5 任务卡 B1–B14

### B1 · 现状基线、遗留边界和零回归门

`P0` / 4–6h / 无依赖 / **owner: backend**

**目标**：确认当前伪子代理的真实调用链，建立删除/适配清单，不在旧路径上叠加第二套逻辑。

**操作步骤**

1. 用 `rg -n "subagent|SubAgent|TaskTree|_run_with_subagents|run_agent" core tools appserver protocol tests` 定位所有定义和调用。
2. 画出 `Primary -> tool -> child candidate -> provider -> result` 的实际链路。
3. 为每个遗留符号标记 `delete`、`adapter` 或 `keep-with-contract`。
4. 为单 Agent 路径增加基线测试，证明 B 阶段默认关闭时行为不变。
5. 把本卡结果写入 `docs/` 或本卡 commit 描述，不修改与本卡无关的业务行为。

**完成判据**

- [ ] 所有旧入口都有调用者和处置结论；
- [ ] 找不到未标记的第二套子代理实现；
- [ ] 单 Agent 旧路径回归基线不下降；
- [ ] 输出下一张卡的真实文件白名单；
- [ ] Composer 已把 Grok/Sonnet 的资料或审查意见转为可验证的卡内结论。

### B2 · AgentDefinition 与配置加载器

`P0` / 8–12h / 依赖 B1 / **owner: backend**

**目标**：把 JSON、Markdown 和内置定义归一化为单一不可变 `AgentDefinition`，先做静态校验，再允许运行时加载。

**必须实现**

- id 唯一性、保留字和命名规则；
- `mode`、`steps`、`subagent_depth`、workspace scope 的范围校验；
- permission 三态和 pattern 语法校验；
- `permission.task` 不能放宽系统默认 deny；顶层 `task_permission` 输入必须被拒绝；
- 配置错误包含文件、字段和可修复建议；
- 用户级定义不能覆盖系统硬拒绝和内置 Agent 安全边界。

**建议文件**：`core/subagents/definitions.py`、`core/subagents/config_loader.py`、`protocol/subagents.py`、`tests/test_subagents/test_definitions.py`。

**验收**

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m pytest tests/test_subagents/test_definitions.py -q
python -m ruff check core/subagents protocol tests/test_subagents
```

- [ ] JSON 和 Markdown 加载结果相同；
- [ ] 缺 id、重复 id、非法 mode、负 steps、非法权限规则均被拒绝；
- [ ] `hidden=true` 只影响 UI 列表，不影响显式 Task；
- [ ] schema 变更已生成 TypeScript 类型或明确记录生成命令。

### B3 · Primary / Subagent 模式和默认配置

`P0` / 6–8h / 依赖 B2 / **owner: backend**

**目标**：建立 Primary、Subagent、All 三种模式，确保默认 Agent 仍是 Primary，默认子代理不能继续派生子代理。

**操作步骤**

1. 给当前会话增加 `session_mode` 和 `agent_id`。
2. 只允许 `primary/all` 作为用户主入口。
3. 只允许 `subagent/all` 作为 Task 或 `@` 目标。
4. 默认 `subagent_depth=0`、`permission.task=deny`；内部 `task_permission` 由该字段归一化生成。
5. 在 capability 中报告 `subagents.task`、`subagents.mention`、`subagents.child_tasks` 是否可用。

**完成判据**

- [ ] 当前普通会话仍使用 Primary；
- [ ] 直接把 Subagent 当主会话启动会返回明确错误；
- [ ] `all` 的入口行为在 CLI、OpenTUI、Desktop 一致；
- [ ] 默认配置不产生额外模型调用；
- [ ] 无 feature flag 时单 Agent 字节级回归通过。

### B4 · Child Session 生命周期

`P0` / 10–14h / 依赖 B2、B3 / **owner: backend**

**目标**：实现独立的 parent/child session 树、终态和恢复基础。

**必须保存**

- `session_id`、`parent_session_id`、`root_session_id`；
- `agent_id`、trigger、创建者和定义版本；
- created/started/terminal timestamps；
- budget、workspace scope、permission snapshot；
- event cursor 和 result pointer。

**完成判据**

- [ ] created → queued → running → finalizing → terminated 有状态机测试；
- [ ] cancel、timeout、deny、failure、complete 都有终态；
- [ ] 重复 terminal event 幂等；
- [ ] Parent 取消会递归取消未完成 Child；
- [ ] Child 终态可从 event log 恢复。

### B5 · 隔离式 AgentRuntime

`P0` / 14–18h / 依赖 B4 / **owner: backend**

**目标**：把 AgentDefinition 编译成运行实例，彻底隔离可变资源。

每个 Runtime 至少拥有：

```text
AgentRuntime
├── AgentDefinition snapshot
├── ToolRegistry（按 permission 和 scope 构造）
├── PermissionPolicy
├── memory namespace
├── cache namespace
├── BudgetGuard
├── CancellationToken
├── Trace/Audit scope
└── Provider handle（Phase E 前默认继承 Primary model）
```

**禁止**：Child 保存 Primary `AgentV2` 的可变引用；Child 直接访问 Primary history；多个 Child 共享可写 singleton；Renderer 直接创建 Runtime。

**完成判据**

- [ ] 两个 Child 的 tool registry、memory、cache、budget、trace id 均不同；
- [ ] Provider 可共享的部分只有无状态调用能力，不能共享对话状态；
- [ ] Child 结果只能通过 manager 回传；
- [ ] 单 Agent 走 adapter 时旧路径回归通过；
- [ ] Sonnet 或 Composer 独立完成一次交叉引用审查。

### B6 · ContextEnvelope、引用和脱敏

`P0` / 10–14h / 依赖 B5 / **owner: backend**

**目标**：让 Child 得到“完成任务所需的最小上下文”，而不是 Primary 的完整隐私 history。

**必须支持**：文件引用、消息摘要引用、结构化 artifact 引用、附件引用、sha256 校验、secret 脱敏和最大 token 限制。

**完成判据**

- [ ] 未授权的完整 history 不会出现在 Child prompt；
- [ ] 引用文件在执行前校验 workspace scope 和 sha256；
- [ ] secret、token、authorization 等字段有脱敏测试；
- [ ] context 超限会产生结构化错误或可审计截断，不静默丢失；
- [ ] Child 结果保留引用而不是复制大段内部上下文。

### B7 · Task Tool 和自动触发

`P0` / 10–14h / 依赖 B4–B6 / **owner: backend**

**目标**：提供唯一的自动派发入口，支持 `agent_id`、prompt、context refs、output schema、budget 和 workspace scope。

**执行顺序必须固定**：解析参数 → 校验 AgentDefinition → 校验 `permission.task` 规范化结果 → 构造 ContextEnvelope → 计算 budget/scope → 创建 Child → 发事件 → 执行 → 回传 TaskResult。

**完成判据**

- [ ] Task Tool 不能通过参数绕过 Agent permission；
- [ ] 不存在的 agent、模式不匹配和 task deny 都不创建 Child；
- [ ] 自动触发和显式 `@` 使用相同 Child Manager；
- [ ] `output_schema` 错误不会导致原始模型输出冒充结构化结果；
- [ ] Task 调用和结果都带 correlation id。

### B8 · `@` 触发与 CLI/OpenTUI/Desktop 共用入口

`P1` / 8–12h / 依赖 B3、B7 / **owner: frontend**

**目标**：实现 OpenCode 风格的显式 `@agent`，但解析、权限和创建仍由后端统一负责。

**前端允许做**：autocomplete、显示名称、loading/terminal 状态、跳转 Child、渲染错误。

**前端不允许做**：本地决定权限、本地创建 session、本地运行模型、本地拼接完整 Primary history。

**Grok 辅助环节**：仅在本卡明确的 Desktop/OpenTUI 截图验收、空态/加载态/错误态和 Child tree 视觉核对中介入；Composer 写卡本体并收口。

**完成判据**

- [ ] `@explore` 在 CLI、OpenTUI、Desktop 触发相同协议；
- [ ] autocomplete 遵守 `hidden` 和 mode；
- [ ] Child tree、状态和错误可见；
- [ ] Grok 只提交视觉问题或受控前端 patch，Composer 完成最终合并和测试；
- [ ] 无网络/服务端断开时不会生成假 Child。

### B9 · PermissionPolicy、审批和 Agent task 权限

`P0` / 12–16h / 依赖 B2、B5、B7 / **owner: backend**

**目标**：实现 allow/ask/deny、工具输入 pattern、Agent 覆盖和递归 task 权限。

**验收重点**

- [ ] `deny` 永远优先于普通默认 allow；
- [ ] `ask` 产生可恢复审批，而不是直接失败或直接允许；
- [ ] approval 绑定 session、tool call、路径、Agent definition version；
- [ ] `task` 可允许 `explore` 而拒绝 `general`；
- [ ] `external_directory` 单独测试；
- [ ] 规则顺序和 pattern 匹配有表驱动测试；
- [ ] 审批日志可被 Desktop 后续审计面板消费。

### B10 · WorkspaceScope、写租约和并发冲突

`P0` / 12–16h / 依赖 B6、B9 / **owner: backend**

**目标**：让并行 Child 的读写边界可判断、可阻塞、可恢复。

```text
read_only          只能读和运行白名单只读命令
leased_write       必须取得目录/文件 lease，释放后才能由别的 Child 写
isolated_worktree  在独立 worktree 写，结果以 artifact/diff 回传
```

**必须拒绝**：两个 leased_write Child 同时持有同一文件；Child 未声明 scope 却 edit；workspace 外路径；lease 过期后继续写。

**完成判据**

- [ ] 同文件冲突有稳定错误码；
- [ ] lease 释放在 complete/fail/cancel/timeout 全部执行；
- [ ] crash recovery 能回收过期 lease；
- [ ] isolated worktree 的 diff 不会自动写回 Primary workspace；
- [ ] edit/bash Child 必须获得 WorkspaceScope；
- [ ] 并行只读任务可以安全并发。

### B11 · Budget、steps、depth、并发和取消

`P0` / 10–14h / 依赖 B5、B9、B10 / **owner: backend**

**目标**：建立多 Agent 的成本和失控保护，默认不让子代理无限递归或无限消耗。

预算至少包含：token、步骤数、墙钟时间、并发 Child 数和总 task 数。预算必须在创建时冻结上限，在每次模型调用和工具调用时扣减，在终态写入 usage。

**完成判据**

- [ ] `subagent_depth=0` 的 Child 不能创建子 Child；
- [ ] depth、steps、token、time、concurrency 任一达到上限都能进入可解释终态；
- [ ] cancel token 能终止模型等待、工具等待和子 Child；
- [ ] Parent 取消不留下 orphan process、orphan lease 或 orphan task；
- [ ] budget 使用量可在事件和 TaskResult 中查询；
- [ ] 默认多 Agent 开关为 off，单 Agent 不增加调用。

### B12 · ChildSessionEvent、持久化和恢复

`P1` / 10–14h / 依赖 B4、B7、B11 / **owner: backend**

**目标**：让 CLI、Desktop 和未来 LinkAgent 能实时观察、补读和恢复 Child。

最小事件集合：

```text
child_session/created
child_session/queued
child_session/started
child_session/context_ready
child_session/tool_call
child_session/approval_required
child_session/progress
child_session/partial_result
child_session/completed
child_session/failed
child_session/cancelled
child_session/recovered
```

每个事件必须带 `event_id`、`session_id`、`parent_session_id`、`request_id`、单调序号、时间、definition version 和 redaction metadata。

**完成判据**

- [ ] 事件序号单调且可检测 gap；
- [ ] 客户端断开后可从 cursor 补读；
- [ ] 重复事件幂等；
- [ ] terminal event 持久化后才释放 lease；
- [ ] 恢复后不会重复运行已完成的 Child；
- [ ] Desktop 可只订阅某个 Child 子树。

### B13 · 内置 Agent、Task Tool 迁移和示例目录

`P1` / 8–12h / 依赖 B2、B7、B9 / **owner: backend + frontend**

**目标**：提供可演示、可测试、默认安全的内置 Agent，而不是只留下抽象接口。

**迁移硬约束**：当前 `tools/agent_tool.py` 是旧的直接 `AgentV2` 兼容入口，当前 `tools/task_tool.py` 是任务清单/状态工具；二者都不能被静默改造成新的隔离子代理派发器。新的 LangChain/工具注册适配器使用 `tools/subagent_task_tool.py`，核心派发逻辑仍归 `core/subagents/manager.py`，对外工具名可以是 `task`，但模块名必须保持可区分。

**操作步骤**

1. 列出 `tools/agent_tool.py`、`tools/task_tool.py` 的所有注册点和调用者，形成旧入口→新入口迁移表。
2. 保留 `tools/task_tool.py` 的任务清单职责，不删除其 session task 持久化和锁语义。
3. 新建 `tools/subagent_task_tool.py` 薄适配层，只负责参数 schema、工具注册和调用 `ChildSessionManager`；不得在该文件创建 `AgentV2` 或拼接 Primary history。
4. 为旧 `agent_tool` 调用者提供显式 adapter/报废错误，并为每个迁移点添加回归测试；不得用同名覆盖掩盖行为变化。
5. 在协议、工具注册表、CLI/OpenTUI/Desktop 三个入口核对 `task` 的唯一注册来源，确保不会同时注册两个同名工具。

至少包含：

| Agent | 用途 | 权限 |
|---|---|---|
| `explore` | 只读代码探索 | read allow；edit deny；task deny |
| `general` | 通用子任务 | 按调用者 scope；task 默认 deny |
| `reviewer` | diff/测试审查 | read allow；edit deny；bash ask |
| `scout` | 外部文档/资料检索 | webfetch/websearch allow；workspace edit deny |

提供：

- `config/agents/` 或项目约定的内置定义；
- 一个 JSON 示例、一个 Markdown 示例、一个 `@` 示例和一个 Task 示例；
- 旧 `SubAgentV2` 调用者的迁移说明；
- `tools/agent_tool.py`、`tools/task_tool.py` 与 `tools/subagent_task_tool.py` 的职责和迁移矩阵；
- feature flag、回滚和兼容错误。

**完成判据**

- [ ] 新安装可以列出内置 Agent；
- [ ] `explore` 能完成只读任务并返回证据；
- [ ] `reviewer` 不能 edit；
- [ ] 现有 `tools/task_tool.py` 仍保持任务清单职责，未被覆盖成子代理派发工具；
- [ ] 新的子代理派发工具只有一个注册点，旧 `agent_tool` 调用者都有迁移或报废测试；
- [ ] 旧入口要么完全迁移，要么明确报废并有测试保护；
- [ ] Composer 已审查所有示例中的权限、路径和费用。

### B14 · 全链路评测、迁移门和 Phase B 出口

`P0` / 16–24h / 依赖 B1–B13 / **owner: backend + frontend**

**目标**：证明“真的隔离”“真的可用”“真的可以被后续 Desktop 和专家团消费”，并对多 Agent 的成本保持诚实。

**最小 E2E 场景**

1. Primary 通过 Task 调用 `explore`，Child 返回文件证据，Primary history 不泄露。
2. 用户通过 `@reviewer` 调用，reviewer 读 diff 但不能 edit。
3. `subtask=true` Command 创建 Child，事件不混入 Primary 普通消息。
4. 两个 Child 并行读不同目录，结果均可回传。
5. 两个 Child 争抢同一文件，一个拿 lease，另一个收到稳定冲突错误。
6. Child 触发 ask 审批，拒绝后进入 denied，不执行工具。
7. Child 尝试递归派生，被规范化后的 `permission.task` 或 depth 拒绝。
8. Parent 取消后所有 Child、工具等待和 lease 都终止。
9. appserver 重启后能补读已持久化事件，不重复执行终态 Child。
10. feature flag 关闭时，旧单 Agent baseline 不回归。

**出口**

- [ ] B1–B14 每张卡都有独立 commit 和真实验收输出；
- [ ] `ruff`、类型检查、协议 schema、单元、协议、E2E 全绿；
- [ ] 单 Agent baseline 不下降；
- [ ] 失败、取消、超时、拒绝和恢复均可审计；
- [ ] CLI/OpenTUI/Desktop 使用同一 TaskRequest/TaskResult/Event；
- [ ] Phase C 不需要复制 Runtime、权限或事件逻辑；
- [ ] Phase D 能显示 parent/child tree 和审批/工具事件；
- [ ] Phase E 可以在创建 Child 时替换 model，不改协议语义；
- [ ] LinkAgent 可通过公开协议而不是内部 import 消费子会话。

---

## §6 安全、成本和失败处理

### 6.1 安全边界

```text
用户输入
  ↓ 过滤和引用校验
Primary
  ↓ Task permission + budget + context policy
Child Session
  ↓ Agent permission + WorkspaceScope + approval
Tool Executor
  ↓ audit event + redacted result
Artifact / TaskResult
```

任何绕过其中一层的“方便 API”都不允许进入生产路径。

### 6.2 成本默认保守

- 多 Agent 默认关闭；
- 自动触发必须有 description 匹配、预算和 task permission；
- explore/reviewer 默认低 steps；
- Desktop 展示预计成本和已用量，但不在 Renderer 自己计算扣费；
- 失败重试要占用新的预算，不能无限重试同一工具调用；
- Phase E 之前，AgentDefinition 的 `model` 默认继承 Primary，不要在 B 阶段偷偷引入多模型路由。

### 6.3 失败分类

| 类别 | 示例 | 是否重试 |
|---|---|---|
| `denied` | 权限或 task permission 拒绝 | 不自动重试，提示用户调整权限 |
| `conflict` | workspace lease 冲突 | 可在用户决定后重新排队 |
| `timed_out` | 模型/工具超时 | 仅在预算允许时一次重试 |
| `cancelled` | 用户或 Parent 取消 | 不自动重试 |
| `provider_error` | API 暂时错误 | 按 Provider policy 小次数重试 |
| `invalid_result` | schema 解析失败 | 可要求 Child 按同一任务修正一次 |
| `internal_error` | runtime bug | 终止并保留审计证据，不吞异常 |

---

## §7 CLI/Desktop 体验

### 7.1 CLI

```text
RxyCode > @explore 找出所有会写文件的工具

┌ Child explore · ses_child_42 · running · 3.1k/8k tokens ┐
│ read core/tools.py                                        │
│ read tests/test_tools.py                                  │
│ progress: 2/5                                             │
└───────────────────────────────────────────────────────────┘

Child completed: 4 files, 7 evidence refs, no writes
```

CLI 至少提供：`/children`、`/child <id>`、`/parent`、`/cancel-child <id>`、`/retry-child <id>`。这些命令调用协议，不直接访问 manager 内部对象。

### 7.2 Desktop

本 Phase 只定义数据和最小展示，不抢 Phase D 的完整工作台：

- 主会话旁显示 Child 数量和运行状态；
- Child tree 可展开/折叠和跳转；
- 每个 Child 显示 Agent、触发方式、权限摘要、预算、工具调用和终态；
- approval_required 显示原因、目标路径、匹配规则和一次性/会话级范围；
- 失败显示错误分类和恢复动作；
- 不在 Renderer 内复制权限判断、预算扣减或 Task 创建逻辑。

Grok 只参与任务卡 B8 中标注的视觉验收。Composer 负责 React/TS 代码、协议客户端、测试和合并。

### 7.3 审计显示

审计记录至少能回答：

```text
谁：Primary session / Child session / Agent id
何时：created / tool call / approval / terminal timestamps
做了什么：Task prompt 摘要、工具名、参数摘要、artifact/diff
依据什么：Agent definition version、permission rule、workspace lease
结果：completed / denied / failed / cancelled / timed_out
花费：steps、tokens、time、重试次数
```

完整敏感 prompt 不默认展示；展示摘要必须保留 evidence pointer 和 redaction 标识。

---

## §8 测试与验收

### 8.1 测试层次

| 层次 | 验证内容 |
|---|---|
| Unit | definition、permission pattern、context redaction、budget、state machine |
| Protocol | schema、事件顺序、cursor、terminal 幂等、错误码 |
| Runtime | tool/memory/cache/budget/trace 隔离、Child 不读 Primary history |
| Integration | Task、`@`、command subtask、appserver、Provider、workspace lease |
| E2E | 取消、恢复、冲突、审批、递归、失败和单 Agent 回归 |
| Visual | Desktop child tree、审批、加载/空/错误态；仅执行标注的前端环节 |

### 8.2 必须有的隔离测试

```python
def test_child_has_different_session_id(): ...
def test_child_does_not_receive_primary_private_history(): ...
def test_child_has_scoped_tool_registry(): ...
def test_child_memory_namespace_does_not_leak(): ...
def test_child_cache_namespace_does_not_leak(): ...
def test_child_budget_is_not_primary_budget(): ...
def test_child_cannot_write_without_workspace_scope(): ...
def test_child_task_permission_blocks_recursion(): ...
def test_parent_cancel_cancels_descendants(): ...
def test_terminal_event_is_idempotent(): ...
def test_single_agent_path_preserves_baseline(): ...
```

### 8.3 机械验收命令

```powershell
cd "D:\agent-demo\RxyCode\RxyCode1_1_0"
python -m ruff check .
python -m pytest tests/test_subagents -q --timeout=120
python -m pytest tests/test_protocol tests/test_appserver -q --timeout=120
python -m pytest tests -q -x --timeout=120
python -m evals.cli run --backend agent --compare-baseline evals\baselines\latest-agent.json
git diff --check
git status --short
```

如果仓库实际没有某个测试目录，先记录事实并使用对应现有测试；不能伪造“通过”。

### 8.4 发布门禁

- feature flag 能关闭所有自动 Subagent 入口；
- 默认配置不增加单 Agent token 或 latency；
- 任何 Child 的 edit/bash/task 都能在审计中找到 permission snapshot；
- 所有终态都可恢复或解释；
- 无 orphan process、orphan lease、orphan event stream；
- 协议有版本字段和向后兼容策略；
- Desktop 只通过 protocol-client；
- 文档示例可从干净配置运行。

---

## §9 与后续 Phase 的接口

### 9.1 Phase C：专家团

Phase C 可以新增 `AgentSpec`、`TeamSpec`、Coordinator、SOP、Mailbox、Blackboard 和角色路由，但必须复用：

- B 的 `ChildSessionManager` 和 `AgentRuntime`；
- B 的 `TaskRequest`、`ContextEnvelope`、`TaskResult`；
- B 的 PermissionPolicy、WorkspaceScope、BudgetGuard；
- B 的 ChildSessionEvent 和恢复机制。

Phase C 不得再写一套 `core/agents/runtime.py` 来复制 B5。若需要角色级包装，只能是 adapter，内部调用 B 的 Child Runtime。

### 9.2 Phase D：RxyCode Desktop

Phase D 消费 B 的 session tree、事件、capability、审批和审计字段。Renderer 不拥有 Python runtime，不直接读数据库，不自己决定工具权限。

### 9.3 Phase E：多模型协作

Phase E 可以在 Child 创建时按角色绑定不同 Provider/model，并增加 handoff、成本和仲裁；不能改变 B 的 context、permission、budget 和 result contract。模型切换发生在 runtime 创建阶段，不能由 prompt 或 Renderer 偷改。

### 9.4 Phase F/G

- Phase F 只拓宽 `ContextEnvelope` 和 `ArtifactRef` 的附件/content block 能力，纯文本路径零回归。
- Phase G Persona 只能生成或覆盖声明字段，不能绕过 B 的 permission、depth、budget 和 workspace policy。
- LinkAgent 的 L9 从 Phase D 完整 Desktop fork，并通过 B 的公开协议显示和扩展子代理。

### 9.5 LinkAgent

LinkAgent 不得 import `core.subagents` 的私有类。公开接入面只有：

```text
protocol schema
appserver JSON-RPC
capability discovery
TaskRequest / TaskResult
ChildSessionEvent + cursor
extension manifest
```

这样 LinkAgent 可以在完整 RxyCode Desktop 基础上增加自己的视图，而不用维护第二套子代理生命周期。

---

## 附录 A · 示例文件

### A.1 只读探索 Agent

```yaml
id: explore
description: 只读探索代码库，返回文件、符号和证据
mode: subagent
steps: 12
permission:
  read: allow
  edit: deny
  bash:
    "pytest *": allow
    "**": deny
  task: deny
  external_directory: deny
workspace_scope: read_only
subagent_depth: 0
```

### A.2 Task 调用

```json
{
  "method": "task",
  "params": {
    "agent_id": "explore",
    "prompt": "找出 protocol/ 中所有事件定义，并指出客户端消费者。",
    "context": {
      "references": [
        {"kind": "directory", "path": "protocol", "mode": "read_only"}
      ]
    },
    "budget": {"max_steps": 12, "max_tokens": 8000},
    "workspace": {"mode": "read_only"}
  }
}
```

### A.3 结构化结果

```json
{
  "request_id": "req_42",
  "child_session_id": "ses_child_42",
  "status": "completed",
  "summary": "发现 9 个事件定义，客户端消费者位于 frontend/protocol-client。",
  "artifacts": [
    {"kind": "exploration_report", "ref": "artifact_42", "sha256": "..."}
  ],
  "evidence": [
    {"path": "protocol/events.py", "line": 18, "sha256": "..."}
  ],
  "usage": {"steps": 7, "input_tokens": 4200, "output_tokens": 1100},
  "error": null
}
```

### A.4 禁止示例

```python
# 禁止：绕过 ChildSessionManager，直接复用 Primary 的可变 Agent。
child = primary_agent
child.run(prompt)

# 禁止：Renderer 自己拼完整 history 并调用后端内部类。
window.api.invokeInternalAgent({history: primaryHistory, prompt})
```

---

## 附录 B · 开发交接模板

### B.1 Composer 主写卡交接

```text
卡号：B<编号>
实现范围：<文件白名单>
协议变化：<schema / method / event / none>
隔离证明：<session/tool/memory/cache/budget/trace 测试>
权限证明：<allow/ask/deny/task/workspace 测试>
验收命令：<真实命令>
真实输出：<粘贴摘要>
Grok 辅助：无 / <视觉问题或前端 patch>
Sonnet 预审：无 / <发现的问题和处理>
未解决：<没有就写无>
```

### B.2 Grok 前端辅助交接

```text
只处理：B8 的 Desktop/OpenTUI 视觉验收环节
不处理：core/、protocol/、appserver/、权限和预算核心
输入：Composer 当前 commit、启动命令、验收场景
输出：截图、复现步骤、视觉问题、最小前端 patch（如被明确委托）
收口：Composer 复核 diff、运行测试、合并并提交
```

### B.3 Sonnet diff 预审交接

```text
重点审查：上下文泄露、权限旁路、事件顺序、递归、预算、lease、孤儿任务
不做：直接改功能代码
结论格式：阻断问题 / 非阻断建议 / 未发现问题 + 证据
最终决定：Composer 根据测试和代码事实收口
```

---

## §10 Phase B 完成定义

Phase B 只有在以下条件全部满足时才算完成：

1. OpenCode 风格的 Primary/Subagent、`@`、Task 和 `subtask` 行为已在 RxyCode 中有统一契约；
2. Child 拥有独立 Session、Context、Runtime、Tool/Permission、Budget、Trace 和生命周期；
3. Child 不能通过内部引用修改 Primary；
4. 权限、workspace lease、递归和取消都能被测试与审计；
5. CLI、OpenTUI、Desktop 通过同一协议消费；
6. Composer 2.5 主写并完成最终合并，Grok 只参与标注的资料/视觉辅助，Sonnet 只做可选预审；
7. Phase C、Phase D、Phase E 和 LinkAgent 都有明确、稳定且不重复建设的接入面；
8. 单 Agent 默认路径零回归，多 Agent 的额外成本和失败不会被隐藏。

**下一步只能是 Phase C 的专家团编排**。Phase C 可以组合多个 Child，但不能再次发明 Child Runtime。
