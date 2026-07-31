# L2 · RxyCode 桥接

> **前置**：[`L1-EKO-CORE.md`](./L1-EKO-CORE.md) 全部完成 + RxyCode 可本地安装
> **产出**：LinkAgent 能调 RxyCode 执行任务、能把 EKO 上下文注入进去、能从轨迹里回收证据
> **工时**：6 天
> **卡数**：6 张（L2-1 ~ L2-6）
>
> **干活前读** [`../COMPOSER-2.5-PLAYBOOK.md`](../COMPOSER-2.5-PLAYBOOK.md) §2。**一次只做一张卡。**

---

## §0 这份文档要解决什么

L1 之后有了经验库，但它是个孤岛：不知道用户在干什么，也没有执行能力。

L2 建三座桥：

```
        ┌──────── 注入 ────────┐
        │  EKO 上下文 → prompt │        【L2-3】
        ▼                      │
   RxyCode AgentV2.run()  ─────┘
        │
        ├──────── 拦截 ────────► 工具调用经过 LinkAgent 的 broker  【L2-4】
        │
        └──────── 回收 ────────► 轨迹 → EvidencePacket           【L2-5】
```

### ⚠ 核心约束：RxyCode 一行都不许改

任何一张卡如果发现"必须改 RxyCode 才能做"，按 Playbook 规则 C7 **停下来报告**。

不要 fork、不要打补丁文件、不要在 site-packages 里改。

---

## §1 实测出来的接口事实

**下面每一条都是核实过的**（2026-07-31）。写代码前先用 Grep 确认还成立。

### 1.1 能用的公开接口

| 能力 | 签名 | Grep 锚点 |
|---|---|---|
| 执行 | `async def run(self, user_input: str, mode: str = "build") -> str` | `async def run(self, user_input` |
| 构造 | `def __init__(self, model_name: Optional[str] = None)` | `def __init__(self, model_name` |
| 挂钩子 | `def register_hook(self, phase, callback, **kwargs) -> str` | `def register_hook` |
| 摘钩子 | `def unregister_hook(self, hook_id: str) -> bool` | `def unregister_hook` |
| 切会话 | `def set_session(self, session_id: str) -> str` | `def set_session` |
| 换模型 | `def switch_model(self, configured_name: str) -> dict` | `def switch_model` |
| 取消 | `def cancel(self) -> bool` | `def cancel` |
| 装审批 broker | `def set_approval_broker(broker) -> None` | `def set_approval_broker` |

### 1.2 三条必须知道的限制

> **① `run()` 只吃字符串。** 没有结构化输入，没有"附加上下文"参数。EKO 上下文只能通过别的途径进去（见 L2-3）。

> **② hooks 是观察性的，不能阻断。** `HookPhase` 只有 `BEFORE` / `AFTER`；`emit()` 返回 `list[HookAuditResult]`，**返回值不影响主流程**。
>
> **所以 SAG 的拦截能力不能靠 hooks 实现**，必须走 approval broker（那是唯一能返回"拒绝"的缝）。

> **③ 配置没有构造参数。** 没有 `AgentV2(config=...)`，配置来自 `load_config()` 读 YAML 文件。**同进程跑两套配置是不安全的**（全局单例清单见 [`APPENDIX-A §6.3`](./APPENDIX-A-ASSET-INVENTORY.md#63--全局单例清单决定进程隔离策略)）。

### 1.3 审批 broker 的形状

```python
class ApprovalBroker(ABC):
    async def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        # 有一层 always-allow 缓存,然后调 _ask
    async def _ask(self, request: ApprovalRequest) -> ApprovalDecision:  # 子类实现
```

`ApprovalRequest` 字段：`tool_name` / `args_summary` / `risk` / `approval_id`。

**注意 `args_summary` 是被截断过的**（`__post_init__` 里调了 `summarize_args`）。SAG 要检查完整参数的话，这里拿到的可能不够——L4 会处理。

---

## §2 架构决策（已定，不要自己发挥）

### D1 · LinkAgent 拥有外层循环

**LinkAgent 是调用方，RxyCode 是被调方。** 不是反过来。

```python
class LinkAgent:
    async def run_turn(self, request: str) -> TurnResult:
        ekos = self._retrieve(request)        # L3
        decision = self._authorize(ekos)      # L4
        answer = await self._agent.run(...)   # RxyCode 执行
        self._harvest(...)                    # L5
```

**为什么不做成 RxyCode 的插件**：RxyCode 的 LangGraph 拓扑没有插件 API（`build_graph` 是硬编码的），想插节点只能 fork。而外层包装用的全是公开接口。

### D2 · 一个进程一个 AgentV2

个人 agent 场景下这不是限制——一个用户、一个会话、一个 Agent。

需要两套配置的唯一场景是 **L7 的 A/B 评测**（EKO 开 vs 关）。那里用**子进程隔离**，不在同进程里切。

### D3 · EKO 上下文注入走 memory 通道

三个候选方案，选第二个：

| 方案 | 怎么做 | 判决 |
|---|---|---|
| 拼进 `user_input` | `run("【经验】...\n\n" + request)` | ❌ 污染用户消息，会被日志和 UI 原样显示 |
| **包装 `MemoryManager.get_context_for_prompt`** | 调原方法拿到结果，追加 EKO 段 | ✅ **选这个**。它就是为"注入上下文"设计的槽位 |
| 覆盖 prompt 模板 | `prompts.registry.register(...)` | ❌ 全局单例，会影响同进程所有东西 |

**方案二的代价要说清楚**：`agent._memory` 是**私有属性**。RxyCode 的 Phase 2 重构可能改它。

**缓解办法**：写一个契约测试，专门检查这个缝还在。它红了就说明 RxyCode 变了，需要人来适配——这比运行时静默失效好得多。

### D4 · 轨迹回收走 hooks

hooks 不能阻断，但**观察**正是回收要的。`subject="tool_call"` 的 `AFTER` 钩子能拿到工具调用记录。

---

## §3 任务卡

### L2-1 · 桥接层类型与契约测试

`P0` / 1 天 / 依赖：L1 全部

**背景**

**先写契约测试，再写桥接代码。**

理由：L2 全部建立在 RxyCode 的几个接口上，其中一个（`_memory`）还是私有的。如果没有测试守着，RxyCode 一升级，LinkAgent 会在运行时静默出错——EKO 注入不进去，但一切看起来正常，只是效果消失了。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/bridge/types.py` | 新建 |
| `tests/bridge/test_rxycode_contract.py` | 新建，**这张卡的核心** |

**已经替你决定好的**

- 契约测试**必须**在 RxyCode 未安装时 skip，不能 error（L0-5 定的规矩）
- 契约测试失败时的信息要写清"RxyCode 的哪个接口变了、LinkAgent 的哪一层会受影响"
- 类型全用 `frozen dataclass`，不用 pydantic（桥接层是内部数据流，不需要序列化校验）

**操作步骤**

1. `src/linkagent/bridge/types.py`：

```python
"""桥接层的数据类型。

这些是 LinkAgent 内部的数据流,不跨进程,所以用 dataclass 而不是 pydantic
——不需要序列化校验,少一层开销。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolInvocation:
    """一次工具调用的记录。轨迹回收的最小单元。"""

    name: str
    args: dict[str, Any]
    result_summary: str
    succeeded: bool
    duration_ms: float


@dataclass(frozen=True)
class Trajectory:
    """一个 turn 的可观测轨迹。

    **刻意不含模型的隐藏推理。** AED 蒸馏的硬约束之一就是只用可观测轨迹
    (任务 → 状态 → 工具调用 → 观测 → 结果),隐藏 CoT 严禁使用。这里从
    类型上就不给它位置。
    """

    request: str
    answer: str
    tools: tuple[ToolInvocation, ...] = ()
    succeeded: bool = False


@dataclass(frozen=True)
class TurnResult:
    """LinkAgent 一个 turn 的完整结果。"""

    answer: str
    trajectory: Trajectory
    #: 本次注入的 EKO id,用于事后归因
    activated_eko_ids: tuple[str, ...] = ()
    #: 安全门的判定,None 表示未启用
    safety_verdict: str | None = None
```

2. `tests/bridge/test_rxycode_contract.py` —— **这是核心**：

```python
"""RxyCode 接口契约测试。

LinkAgent 建立在 RxyCode 的几个接口上,其中 `AgentV2._memory` 还是私有的。
这组测试的作用是:RxyCode 一旦改了这些接口,**在测试里红,而不是在运行时
静默失效**。

静默失效长这样:EKO 注入不进去了,但对话照常返回,只是个性化效果消失。
这种 bug 几乎不可能在使用中被发现。
"""

import inspect

import pytest

from linkagent.bridge._require import rxycode_available

pytestmark = pytest.mark.skipif(
    not rxycode_available(), reason="RxyCode 未安装"
)


def test_agent_run_accepts_user_input_and_mode():
    """AgentV2.run(user_input: str, mode: str) 签名不变。

    变了的话:LinkAgent 的执行调用要改。
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    sig = inspect.signature(AgentV2.run)
    assert "user_input" in sig.parameters
    assert "mode" in sig.parameters


def test_agent_exposes_hook_registration():
    """register_hook / unregister_hook 存在。

    变了的话:L2-5 的轨迹回收失效。
    """


def test_memory_context_injection_seam_exists():
    """MemoryManager.get_context_for_prompt 存在且接受 query。

    ⚠ 这是 LinkAgent 注入 EKO 上下文的唯一通道(见 L2 文档 §2 D3)。
    它变了的话,个性化会**静默失效**——对话正常返回,只是不再带经验。
    """
    from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

    sig = inspect.signature(MemoryManager.get_context_for_prompt)
    assert "query" in sig.parameters
    assert sig.return_annotation in (str, "str")


def test_agent_has_memory_attribute():
    """AgentV2 实例有 _memory 属性。

    ⚠ 私有属性,RxyCode 的 Phase 2 重构可能改它。红了就来读 L2 §2 D3,
    换一个注入通道。
    """


def test_approval_broker_can_be_installed():
    """set_approval_broker 存在,ApprovalBroker 可被继承。

    变了的话:L4 的安全门装不上——那是唯一能返回「拒绝」的缝。
    """


def test_hooks_cannot_block_execution():
    """确认 hooks 是观察性的。

    这条不是怕它变,是**记录一个设计事实**:HookRegistry.emit 返回审计
    结果,不影响主流程。所以 SAG 的拦截必须走 approval broker,不能靠
    hooks。有人以后想「用 hook 拦住危险工具」时,这个测试是文档。
    """
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/bridge/test_rxycode_contract.py -v
python -m ruff check src/linkagent/bridge/
```

`-v` 是刻意的：你要**看到**每条契约的名字。

**完成判据**
- [ ] 六条契约测试全部通过
- [ ] 卸载 RxyCode 后它们 skip（不是 error）
- [ ] `Trajectory` 类型里**没有**隐藏推理的位置
- [ ] 每条测试的 docstring 说清"变了会影响哪一层"

**Commit**
```
test(bridge): pin the RxyCode interfaces LinkAgent depends on

The memory-context seam is a private attribute, so a silent RxyCode
refactor would disable personalization while conversations kept working.
These contracts turn that into a red test instead.
```

---

### L2-2 · Agent 生命周期包装

`P0` / 1 天 / 依赖：L2-1

**背景**

包一层 `RxyCodeExecutor`，把 AgentV2 的构造、会话、取消收进来，别的层不直接碰 `AgentV2`。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/bridge/executor.py` | 新建 |
| `tests/bridge/test_executor.py` | 新建 |

**已经替你决定好的**

- **只有 `bridge/` 能 import RxyCode。** 其他包（`eko/`、`distillation/`、`safety/`、`runtime/`）一律不许——这样将来换底座只动一个包
- AgentV2 **懒构造**：第一次 `execute()` 时才建。理由：构造它会读配置、建 LLM、建 memory、注册工具，只想跑 EKO 单测的场景不该付这个代价
- 提供 `FakeExecutor` 给测试用，实现同一个 Protocol

**操作步骤**

1. 先定 Protocol（放 `bridge/types.py`）：

```python
class Executor(Protocol):
    """执行底座的抽象。

    LinkAgent 的 runtime 层只依赖这个 Protocol,不直接依赖 AgentV2。
    测试用 FakeExecutor,生产用 RxyCodeExecutor。
    """

    async def execute(self, request: str, *, mode: str = "build") -> Trajectory: ...
```

2. `src/linkagent/bridge/executor.py`：

```python
"""RxyCode 执行底座包装。

**这是全项目唯一 import RxyCode 的地方。** 其他包一律通过 Executor
Protocol 访问执行能力,这样换底座只动这一个文件。
"""


class RxyCodeExecutor:
    """把 AgentV2 包成 Executor。

    懒构造:AgentV2 的 __init__ 会读配置、建 LLM、建 memory、注册全部工具,
    只想跑 EKO 单测的场景不该付这个代价。
    """

    def __init__(self, *, model_name: str | None = None, session_id: str = "latest") -> None:
        self._model_name = model_name
        self._session_id = session_id
        self._agent = None  # 懒构造

    def _ensure_agent(self):
        if self._agent is None:
            require_rxycode()
            from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

            self._agent = AgentV2(model_name=self._model_name)
            self._agent.set_session(self._session_id)
        return self._agent

    async def execute(self, request: str, *, mode: str = "build") -> Trajectory:
        ...

    def cancel(self) -> bool:
        ...
```

3. `FakeExecutor`（放 `src/linkagent/bridge/fake.py`，**不是 tests 里**——L7 的评测也要用）：

```python
class FakeExecutor:
    """脚本化的假执行器。

    放在生产包而不是 tests/ 里,因为 L7 的评测 harness 也要用它跑
    「不调真实模型的确定性回归」。
    """

    def __init__(self, responses: list[str]) -> None: ...
```

4. 测试覆盖：懒构造（没调 `execute` 前 `_agent is None`）、会话设置、取消、`FakeExecutor` 满足 Protocol。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/bridge -q
python -m ruff check src/linkagent/
```

**加一条边界检查**——确认只有 bridge 碰 RxyCode：

```powershell
Get-ChildItem -Path "src\linkagent" -Recurse -Filter *.py |
  Where-Object { $_.FullName -notmatch '\\bridge\\' } |
  Select-String -Pattern "RxyCode"
```

**必须零输出。**

**完成判据**
- [ ] 测试全绿
- [ ] **边界检查零输出**（只有 `bridge/` import RxyCode）
- [ ] 懒构造有测试
- [ ] `FakeExecutor` 在生产包里且满足 Protocol

**Commit**
```
feat(bridge): wrap AgentV2 behind an Executor protocol

Confining the RxyCode import to bridge/ keeps the EKO layer testable
without the substrate and makes a future swap a single-file change.
```

---

### L2-3 · EKO 上下文注入

`P0` / 1 天 / 依赖：L2-2

**背景**

把检索到的 EKO 变成文本，送进 RxyCode 的 prompt。

**这张卡决定了个性化到底有没有效果。** 注入格式写差了，模型会忽略它。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/bridge/context.py` | 新建 |
| `tests/bridge/test_context.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 注入通道 | 包装 `agent._memory.get_context_for_prompt` | §2 D3 |
| 包装方式 | **装饰原对象的方法**，不是替换整个 MemoryManager | 替换会丢掉 RxyCode 自己的记忆功能 |
| EKO 段位置 | 追加在原 context **之后** | 经验比历史对话更该被"最后看到" |
| 单次注入上限 | **5 条 EKO** | 论文的检索 `limit=5`，且 Recall@5 已达 98.42%，多了只是噪声 |
| 字符上限 | 4000 | 防一条 EKO 的 procedure 特别长把上下文挤爆 |
| 零命中 | **不注入任何东西** | 不要输出"没有找到相关经验"这类噪声 |

**注入格式**（照抄，不要自己设计）：

```
## 相关经验

以下是从你的经验库中检索到的、适用于当前请求的条目。它们来自你过去的
交互或已验证的执行轨迹。如果与当前请求冲突，以当前请求为准。

### 1. <description>
- 适用前提：<preconditions,逗号分隔;为空则省略这一行>
- 做法：
  1. <procedure[0]>
  2. <procedure[1]>
- 来源：<mode_u|aed> · 版本 <version>
```

**为什么加"以当前请求为准"这句**：五级优先级里 `EXPLICIT_INSTRUCTION(80) > PERSISTENT_PERSONAL(40)`。代码层面 L6 才做冲突裁决，但**这句话现在就能让模型自己处理大部分情况**，成本为零。

**操作步骤**

1. `src/linkagent/bridge/context.py`：

```python
"""EKO → prompt 上下文注入。

通道是包装 MemoryManager.get_context_for_prompt(见 L2 文档 §2 D3)。
选它而不是拼进 user_input,是因为拼进去会污染用户消息——日志和 UI 会把
注入的经验当成用户自己说的话原样显示。
"""

MAX_INJECTED_EKOS = 5      # 论文检索 limit=5,Recall@5 已达 98.42%
MAX_CONTEXT_CHARS = 4000   # 防单条 procedure 过长挤爆上下文


def render_ekos(ekos: Sequence[FormalEKO]) -> str:
    """把 EKO 渲染成注入文本。零条时返回空串,不输出占位噪声。"""


def install_injector(agent, provider: Callable[[str], Sequence[FormalEKO]]) -> Callable[[], None]:
    """在 agent 上装 EKO 注入,返回卸载函数。

    装饰 agent._memory.get_context_for_prompt:先调原方法拿 RxyCode 自己的
    记忆上下文,再追加 EKO 段。**不替换整个 MemoryManager**——替换会把
    RxyCode 的短期/长期记忆一起丢掉。

    返回卸载函数是为了测试和 L7 的 A/B:同一个 agent 要能干净地关掉注入。
    """
```

2. 测试必须覆盖：

```python
def test_zero_ekos_injects_nothing():
    """零命中时原 context 逐字节不变。"""

def test_original_memory_context_is_preserved():
    """RxyCode 自己的记忆上下文没被吃掉。"""

def test_at_most_five_ekos_are_injected():

def test_context_is_truncated_at_the_char_limit():

def test_rendered_text_tells_the_model_to_prefer_the_current_request():
    """注入文本里必须有「以当前请求为准」。

    这是最便宜的冲突处理——五级优先级里显式指令高于持久化个人偏好,
    L6 之前先靠这句话兜住。
    """

def test_uninstall_restores_the_original_method():
    """卸载后逐字节回到原状。L7 的 A/B 依赖这条。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/bridge/test_context.py -q
python -m ruff check src/linkagent/bridge/
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 零命中不注入任何字符
- [ ] 原 memory context 被保留
- [ ] 卸载能完全还原
- [ ] 注入文本含"以当前请求为准"

**Commit**
```
feat(bridge): inject retrieved EKOs through the memory context channel

Decorating get_context_for_prompt keeps RxyCode's own memory intact and
avoids polluting the user's literal message, which logs and the UI echo
verbatim. The rendered block tells the model to prefer the current
request, which covers most preference conflicts before L6 lands.
```

---

### L2-4 · 审批 broker 接线

`P0` / 4h / 依赖：L2-2

**背景**

**装一个能拦住工具调用的 broker。** 这张卡只搭管道，SAG 规则接进来是 L4。

为什么现在做：这是**唯一能返回"拒绝"的缝**（hooks 不行，见 §1.2）。先把管道打通并测好，L4 只需要往里填规则。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/safety/broker.py` | 新建 |
| `tests/safety/test_broker.py` | 新建 |

**已经替你决定好的**

- 继承 RxyCode 的 `ApprovalBroker`，实现 `_ask`
- **必须能委托给原 broker**。LinkAgent 装了自己的之后，RxyCode 原来的 TUI/SSE 审批不能失效——用户还是要能看到审批提示
- 委托链：`LinkAgent 判定` → 明确拒绝就直接拒；否则 → `原 broker`
- L2 阶段的判定函数是**恒等放行**（`always allow`），L4 才换成 SAG

**操作步骤**

1. `src/linkagent/safety/broker.py`：

```python
"""LinkAgent 的审批 broker。

这是**唯一能阻断工具执行的缝**。RxyCode 的 hooks 只能观察
(HookRegistry.emit 返回审计结果,不影响主流程),所以安全拦截只能走这里。

设计:装饰而不是替换。LinkAgent 先判定,明确拒绝就直接拒;否则委托给原
broker,这样 RxyCode 原有的 TUI / SSE 审批提示继续工作。
"""


class GatedApprovalBroker(ApprovalBroker):
    """在原有审批之前插入一道 LinkAgent 判定。"""

    def __init__(self, inner, verdict_fn) -> None:
        """
        Args:
            inner: 原 broker,可以是 None(没装过的情况)
            verdict_fn: (tool_name, args) -> Verdict。L2 阶段传恒等放行,
                        L4 换成 SAG。
        """

    async def _ask(self, request):
        ...


def install(verdict_fn) -> Callable[[], None]:
    """装上 broker,返回卸载函数。

    卸载函数会把原 broker 装回去——测试和 L7 的 A/B 都需要能干净还原。
    """
```

2. 测试必须覆盖：

```python
def test_denied_verdict_blocks_without_reaching_inner_broker():
    """明确拒绝时不打扰用户——不该为一个必然拒绝的请求弹审批框。"""

def test_allowed_verdict_delegates_to_inner_broker():
    """放行时原有的 TUI/SSE 审批仍然生效。"""

def test_missing_inner_broker_is_handled():
    """原来没装 broker 时不能崩。"""

def test_install_returns_a_working_uninstall():
    """卸载后 get_approval_broker() 回到原值。"""

def test_verdict_function_exceptions_do_not_crash_the_tool_call():
    """判定函数抛异常时降级为「交给原 broker」,不是让工具调用失败。

    安全检查本身出 bug,不该把用户的任务搞挂。记 warning 就好。
    """
```

最后一条很重要——**安全组件的失败模式必须是降级，不是阻断**。

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/safety/test_broker.py -q
python -m ruff check src/linkagent/safety/
```

**完成判据**
- [ ] 五个测试全绿
- [ ] 拒绝时不弹审批框
- [ ] 放行时原 broker 仍被调用
- [ ] 判定函数抛异常时降级不阻断
- [ ] 卸载能完全还原

**Commit**
```
feat(safety): install a gating approval broker ahead of RxyCode's own

The approval broker is the only seam that can refuse a tool call; hooks
are observational. Wiring the pipe now means L4 only has to supply rules.
A failing verdict function degrades to the inner broker rather than
failing the user's task.
```

---

### L2-5 · 轨迹回收

`P0` / 1 天 / 依赖：L2-2

**背景**

从 RxyCode 的执行过程里收集可观测轨迹，供 L5 蒸馏用。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/bridge/harvest.py` | 新建 |
| `tests/bridge/test_harvest.py` | 新建 |

**已经替你决定好的**

| 决定 | 值 | 理由 |
|---|---|---|
| 采集通道 | `register_hook(AFTER, ...)`，`subject == "tool_call"` | hooks 就是干这个的 |
| **绝不采集隐藏推理** | 只收工具调用和可观测结果 | AED 的硬约束。类型上就不给位置（L2-1 的 `Trajectory`） |
| 默认**开启** | — | 与 RxyCode Phase E 的埋点不同：那是给蒸馏训练用的原始 IO（含隐私风险），这里只是工具调用元数据 |
| 参数脱敏 | 采集前过滤敏感键 | 见下 |
| 采集失败 | 静默跳过 + warning | **绝不能影响主流程** |

**敏感键过滤**（默认列表，可配置）：

```python
SENSITIVE_KEY_PATTERNS = ("password", "token", "secret", "api_key", "apikey", "credential", "auth")
```

命中的键，值替换成 `"<redacted>"`。

**操作步骤**

1. `src/linkagent/bridge/harvest.py`：

```python
"""执行轨迹回收。

采集的是**可观测轨迹**:工具名、参数(脱敏后)、结果摘要、成败、耗时。

**刻意不采集模型的隐藏推理。** 这是 AED 蒸馏的硬约束——从隐藏 CoT 里
提炼出来的「经验」无法被验证,也无法在回放里复现。类型层面就不给它位置
(见 bridge/types.py 的 Trajectory)。

采集永远不能影响主流程:任何异常都吞掉记 warning。用户的任务比我们的
训练数据重要。
"""


class TrajectoryCollector:
    """挂在 agent 上收集一个 turn 的工具调用。"""

    def attach(self, agent) -> Callable[[], None]:
        """注册 hook,返回卸载函数。"""

    def take(self) -> tuple[ToolInvocation, ...]:
        """取走本 turn 收集到的调用并清空。"""
```

2. 测试必须覆盖：

```python
def test_tool_calls_are_collected_in_order():

def test_sensitive_args_are_redacted():
    """password / token / api_key 之类的值不进轨迹。"""

def test_hidden_reasoning_has_no_place_in_the_trajectory():
    """Trajectory 类型里没有存隐藏推理的字段。

    这是类型层面的保证,不是运行时检查——不给位置比事后过滤可靠。
    """

def test_collector_exception_does_not_break_the_turn():
    """采集器抛异常时任务照常完成。"""

def test_take_clears_the_buffer():
    """两个 turn 的轨迹不能串。"""

def test_detach_removes_the_hook():
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/bridge/test_harvest.py -q
python -m ruff check src/linkagent/bridge/
```

**完成判据**
- [ ] 六个测试全绿
- [ ] 敏感参数被脱敏
- [ ] 采集异常不影响主流程（写测试注入异常验证）
- [ ] `Trajectory` 里没有隐藏推理的字段
- [ ] turn 之间不串数据

**Commit**
```
feat(bridge): collect observable execution trajectories

Only tool calls and their observable outcomes are recorded — hidden
reasoning is excluded at the type level because AED can only distil from
traces that can be replayed and verified. Collection failures degrade to
a warning so a full disk never fails a user's task.
```

---

### L2-6 · Turn 编排骨架

`P0` / 1 天 / 依赖：L2-3、L2-4、L2-5

**背景**

把前面几张卡串成一个 turn。**七步里现在只有第 5 步（执行）和第 6 步（回收）是真的**，其余是留好位置的空实现。

**涉及文件**

| 文件 | 说明 |
|---|---|
| `src/linkagent/runtime/turn.py` | 新建 |
| `src/linkagent/cli.py` | 改（替换 L0 的占位） |
| `tests/runtime/test_turn.py` | 新建 |

**已经替你决定好的**

- 七步的**顺序固定**，与 [`00-OVERVIEW §4`](./00-OVERVIEW-AND-ARCHITECTURE.md#4-一个-turn-长什么样) 一致
- 未实现的步骤写成**显式的空实现 + TODO 注释指向对应文档**，不要省略——省略了后面的人不知道该插哪
- 每步受 `Config.features` 控制
- CLI 只做最小的"输入一句话、跑一个 turn、打印结果"

**操作步骤**

1. `src/linkagent/runtime/turn.py`：

```python
"""LinkAgent 的 turn 编排。

七步流程见 00-OVERVIEW-AND-ARCHITECTURE.md §4。顺序是固定的:检索必须在
安全门之前(要检查的是「用了这些经验之后的计划」),回收必须在执行之后。

L2 阶段只有执行和回收是实的,其余是占位。每个占位都写明由哪份文档实现,
不要因为「现在是空的」就把它删掉——删了之后就没人知道该插在哪。
"""


class TurnRunner:
    def __init__(self, config: Config, executor: Executor, engine: EKOEngine) -> None:
        ...

    async def run(self, request: str) -> TurnResult:
        # 1. 情境化检索 —— L3 实现
        ekos = self._retrieve(request)

        # 2. 依赖组合 —— L6 实现,默认关闭
        if self._config.features.dependency_composition:
            ekos = self._compose(ekos)

        # 3. 冲突裁决 —— L6 实现,默认关闭
        if self._config.features.conflict_resolution:
            ekos = self._resolve_conflicts(ekos, request)

        # 4. 安全门控 —— L4 实现
        verdict = self._authorize(ekos, request) if self._config.features.safety_gate else None

        # 5. 执行(RxyCode)
        trajectory = await self._executor.execute(request)

        # 6. 证据回收 —— L5 实现完整版,L2 只收轨迹
        packet = self._harvest(trajectory)

        # 7. 反馈演化 —— L5 实现
        if self._config.features.feedback_evolution:
            self._evolve(packet)

        return TurnResult(...)

    def _retrieve(self, request: str) -> list[FormalEKO]:
        """情境化检索。

        TODO(L3-RETRIEVAL-AND-SCOPE.md):现在返回空列表。
        L3 会接上 EKOEngine.search 并修作用域语义。
        """
        return []
```

其余占位同理，每个都带 `TODO(<文档名>)`。

2. `cli.py`：

```python
def main() -> int:
    """最小 CLI:读一行、跑一个 turn、打印结果。

    刻意保持最小。完整的交互界面等 L7 之后再说——现在的目标是能手动
    验证一个 turn 跑通,不是做产品。
    """
```

3. 测试用 `FakeExecutor`，覆盖：

```python
def test_turn_runs_end_to_end_with_a_fake_executor():

def test_disabled_features_are_skipped():
    """关掉的 feature 对应的步骤不执行。"""

def test_step_order_is_retrieve_then_authorize_then_execute():
    """顺序不能乱。

    安全门必须在执行之前——事后检查没有意义。回收必须在执行之后。
    用调用记录断言顺序。
    """

def test_placeholder_steps_return_empty_without_crashing():
    """L3–L6 未实现时整条链路仍能跑通。"""
```

**验收命令**

```powershell
cd "D:\agent-demo\LinkAgent"
python -m pytest tests/runtime -q
python -m pytest -q
python -m ruff check .
```

**手动验证**（RxyCode 已装的情况下）：

```powershell
linkagent "用一句话说明什么是二分查找"
```

**完成判据**
- [ ] 四个测试全绿
- [ ] 七个步骤都在，未实现的带 `TODO(<文档名>)`
- [ ] feature 开关生效
- [ ] 步骤顺序有测试守
- [ ] CLI 能跑通一个真实 turn

**Commit**
```
feat(runtime): wire the seven-step turn with placeholders for L3-L6

Only execution and harvesting are real; the rest are explicit no-ops
carrying a TODO that names the document which implements them. Keeping
the empty steps makes the insertion points unambiguous.
```

---

## §4 L2 出口检查

```powershell
cd "D:\agent-demo\LinkAgent"
python -m ruff check .
python -m pytest -q
python -m pytest tests/bridge/test_rxycode_contract.py -v

# 只有 bridge 能 import RxyCode
Get-ChildItem -Path "src\linkagent" -Recurse -Filter *.py |
  Where-Object { $_.FullName -notmatch '\\bridge\\' } |
  Select-String -Pattern "RxyCode"

# 真实 turn
linkagent "用一句话说明什么是二分查找"
```

**L2 完成的定义：**
- 全部命令绿，边界检查零输出
- 六条 RxyCode 契约测试全部通过，且卸载 RxyCode 后 skip 而非 error
- 能跑通一个真实 turn（虽然还没有任何 EKO 参与）
- 轨迹能收上来，敏感参数脱敏
- 审批 broker 装得上、拦得住、卸得掉
- 六个 commit

**⚠ 此时 LinkAgent 相对裸 RxyCode 还没有任何增益。** 经验库是空的、检索返回空列表、安全门恒等放行。**这是预期的**——L3 才开始产生价值。

**下一步**：[`L3-RETRIEVAL-AND-SCOPE.md`](./L3-RETRIEVAL-AND-SCOPE.md)
