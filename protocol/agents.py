"""多 Agent 协议类型。

放在 protocol/ 内是为了能导出 JSON Schema 并生成 TypeScript 类型——CLI 和
Desktop 都需要展示"现在是哪个角色在工作"、"谁委派给了谁"。

角色抽象的形状参考 CrewAI（role/goal/backstory），profile 字段参考 MetaGPT
（name/profile/goal/constraints）。调研见
docs/plans/opus5-plan/rxycode/PHASE-F-MULTI-AGENT-ORCHESTRATION.md §2。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentSpec(BaseModel):
    """一个角色的静态定义。Spec 不可变；运行时实例是 AgentRuntime。"""

    model_config = ConfigDict(frozen=True)

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
    #: Phase F 阶段全部留 None（同模型）；Phase H 才按角色配不同模型。
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
    #:
    #:   pair.*      Phase H  结对编程（pair.with / pair.role）
    #:   vision.*    Phase I  视觉能力（vision.required）
    #:   persona.*   Phase J  人格（persona.id / persona.skills / persona.source）
    #:   ecosystem.* F18/L2 专家团打包与角色级绑定：
    #:     skill / extra_skills / mcp / is_leader / category / version
    #:     disable_model_invocation / provenance / feasibility / tags
    #:
    #: 用 extra 而不是加一等字段，是为了不让还没定型的功能污染协议 schema。
    #: 某个命名空间稳定之后，再提升为一等字段并同步生成 TS 类型。
    #: 详见 PHASE-J-PERSONA-AGENT-INTERFACE.md 的 J2。
    extra: dict[str, Any] = Field(default_factory=dict)


class SopStage(BaseModel):
    """SOP 的一个阶段。

    确定性状态机的一个节点（决策 DC4）。阶段转移由 next_on_success /
    next_on_failure 静态决定，不由 LLM 现场发挥。
    """

    model_config = ConfigDict(frozen=True)

    name: str
    #: 该阶段由哪个角色执行
    role: str
    #: 该阶段要产出什么（进 prompt，抄 CrewAI 的 expected_output）
    expected_output: str
    #: 该阶段能看到哪些黑板条目（按 key 授权，默认不是全部可见）
    context_keys: list[str] = Field(default_factory=list)
    #: 产出写进黑板的哪个 key
    output_key: str
    #: 进入下一阶段前要跑哪些机械检查（F8）
    verify_before_next: list[str] = Field(default_factory=list)
    #: 机械检查通过后是否还要 LLM 审计
    audit_after_verify: bool = False
    #: 成功后去哪个阶段。None = 流程结束。
    next_on_success: str | None = None
    #: 失败后去哪个阶段。None = 整体失败。
    next_on_failure: str | None = None
    #: 该阶段最多重试几次
    max_retries: int = 2
    #: 并发成员。None = 仅 ``role`` 一人；非空 = 列出的角色并发执行（D3）。
    parallel_members: list[str] | None = None


class TeamSpec(BaseModel):
    """一支专家团 = 成员 + SOP。

    团长不在 members 里：它是运行时构造的 Coordinator（DC2；不干活、
    工具集为空）。WorkBuddy 详情页把主理人放在成员首位——那是产品展示，
    不是本协议的成员表。F18 用 extra['ecosystem.is_leader'] 标记展示用主理人。
    """

    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    description: str = ""
    members: list[AgentSpec]
    stages: list[SopStage]
    #: 起始阶段名
    entry_stage: str
    #: 整个团队单次运行的总 token 预算（决策 DC6）
    total_token_budget: int = 500_000
    #: 整个团队单次运行的墙钟上限（秒）
    total_timeout_s: float = 1800.0
    #: 最大委派次数（防止在两个阶段之间无限打回）
    max_delegations: int = 20
    #: 生态扩展字段（F18 追加）：照 AgentSpec.extra 的命名空间约定，
    #:   ecosystem.* 前缀 = category 分组 / version / disable_model_invocation
    #:   双控 / requires_mcp / requires_skills / hooks / is_leader
    extra: dict[str, Any] = Field(default_factory=dict)


class DelegateRequest(BaseModel):
    """团长 → 成员：下发一个自包含任务。

    "自包含"是 Anthropic 的建议：目标、输出格式、工具清单、完成边界都要
    写清楚，否则成员会重复劳动或者不知道什么时候算完。
    """

    model_config = ConfigDict(frozen=True)

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
    """成员 → 团长：一次委派的产出。"""

    model_config = ConfigDict(frozen=True)

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

    这是"coder 发现问题去找 architect 沟通"。它**不是**成员直连——
    团长会校验 may_consult、记录、计入预算，再转发（决策 DC2）。
    """

    model_config = ConfigDict(frozen=True)

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

    model_config = ConfigDict(frozen=True)

    subject_hash: str  # 被审对象的 sha256
    auditor_role: str
    passed: bool
    findings: list[str] = Field(default_factory=list)
    created_at: float


class TeamEvent(BaseModel):
    """推给客户端的编排层生命周期通知（F 层类型）。

    与 PHASE-E E4 的 AgentEvent 分工：
    - AgentEvent（E4）：运行时 event/agent_*
    - TeamEvent（本类型）：编排层 event/team（及 event/team_*）
    建团信号走 event/agent_team_created，不在本类型重复。
    F 层不得再定义名为 AgentEvent 的类型。
    """

    model_config = ConfigDict(frozen=True)

    method: Literal["event/team"] = "event/team"
    session_id: str
    role: str
    stage: str = ""
    phase: Literal[
        "stage_started",
        "delegated",
        "consulted",
        "verified",
        "audited",
        "stage_completed",
        "failed",
        "budget_exceeded",
        "team_completed",
    ]
    detail: str = ""


class RoutingDecision(BaseModel):
    """ModeRouter 的一次路由结论（F10/F13）。进 schema 供 CLI/Desktop 展示。"""

    model_config = ConfigDict(frozen=True)

    mode: Literal["solo", "team", "team_multi"]
    decided_by: Literal["user", "heuristic", "llm", "default"]
    reason: str
    tokens_used: int = 0
    experiment_tag: Literal["E0", "E1", "E2"] = "E0"
    task: str = ""


class BridgeBudget(BaseModel):
    """F16 task_delegate.budget — inherits F9 fuses."""

    model_config = ConfigDict(frozen=True)

    tokens: int = 80_000
    timeout_s: float = 900.0


class TaskDelegate(BaseModel):
    """Leader → Worker (F16). Lineage-only: refs, never conversation history."""

    model_config = ConfigDict(frozen=True)

    method: Literal["task_delegate"] = "task_delegate"
    task_id: str
    parent_id: str | None = None
    goal: str
    context_refs: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    budget: BridgeBudget = Field(default_factory=BridgeBudget)


class BridgeProgress(BaseModel):
    """Worker → Leader streaming status. notes truncated to ~2k tokens."""

    model_config = ConfigDict(frozen=True)

    method: Literal["progress"] = "progress"
    task_id: str
    status: Literal["running", "blocked", "done", "failed"]
    stage: str = ""
    percent: int = 0
    eta_s: float | None = None
    notes: str = ""


class BridgeToolCall(BaseModel):
    """Worker → Leader. Large results go to result_ref, never inline."""

    model_config = ConfigDict(frozen=True)

    method: Literal["tool_call"] = "tool_call"
    task_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["running", "done", "failed"] = "running"
    result_ref: str = ""


class BridgePlan(BaseModel):
    """Worker → Leader execution plan before work starts."""

    model_config = ConfigDict(frozen=True)

    method: Literal["plan"] = "plan"
    task_id: str
    steps: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    est_tokens: int = 0
    ack: bool = False


class BridgeResult(BaseModel):
    """Worker → Leader. summary is 1–2k tokens; artifacts are paths."""

    model_config = ConfigDict(frozen=True)

    method: Literal["result"] = "result"
    task_id: str
    ok: bool
    summary: str = ""
    artifact_paths: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    duration_s: float = 0.0


class BridgeAbort(BaseModel):
    """Leader → Worker. Sent before a hard kill."""

    model_config = ConfigDict(frozen=True)

    method: Literal["abort"] = "abort"
    task_id: str
    reason: Literal["budget", "timeout", "user"]
    partial: bool = False


AGENT_PROTOCOL_MODELS: tuple[type[BaseModel], ...] = (
    AgentSpec,
    SopStage,
    TeamSpec,
    DelegateRequest,
    DelegateResult,
    ConsultRequest,
    VerdictRecord,
    TeamEvent,
    RoutingDecision,
    BridgeBudget,
    TaskDelegate,
    BridgeProgress,
    BridgeToolCall,
    BridgePlan,
    BridgeResult,
    BridgeAbort,
)
