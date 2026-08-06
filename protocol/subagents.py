"""Phase B · Subagent protocol types.

AgentDefinition, TaskRequest, TaskResult, ChildSessionEvent, and supporting
types shared across all consumers (CLI, OpenTUI, Desktop, LinkAgent).

Schema version is tracked alongside the base protocol version so consumers
can detect incompatible changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Mapping
from uuid import uuid4


# ---------------------------------------------------------------------------
# Protocol version (separate from base protocol version)
# ---------------------------------------------------------------------------

SUBAGENT_PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentMode(str, Enum):
    """Allowed values for AgentDefinition.mode."""
    PRIMARY = "primary"
    SUBAGENT = "subagent"
    ALL = "all"


class TriggerKind(str, Enum):
    """How a child session was triggered."""
    AUTOMATIC = "automatic"   # Task Tool dispatched by model
    MENTION = "mention"       # User @agent invocation
    COMMAND = "command"       # Command with subtask=true
    TEAM = "team"             # Phase C Coordinator dispatch


class ChildStatus(str, Enum):
    """Child session terminal / non-terminal states."""
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class WorkspaceMode(str, Enum):
    """Workspace isolation level for a child session."""
    READ_ONLY = "read_only"
    LEASED_WRITE = "leased_write"
    ISOLATED_WORKTREE = "isolated_worktree"


class PermissionVerdict(str, Enum):
    """Per-tool permission decision."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# ---------------------------------------------------------------------------
# Permission types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PermissionRule:
    """A single permission rule: pattern → verdict.

    Rules are evaluated in definition order; the last matching rule wins.
    """

    pattern: str       # glob or regex pattern for tool input
    verdict: PermissionVerdict

    @classmethod
    def from_raw(cls, raw: str | dict[str, str]) -> PermissionRule:
        """Parse a raw permission entry into a PermissionRule."""
        if isinstance(raw, str):
            return cls(pattern="**", verdict=PermissionVerdict(raw))
        # dict form: {"src/**": "allow"}
        pattern, verdict = next(iter(raw.items()))
        return cls(pattern=pattern, verdict=PermissionVerdict(verdict))


@dataclass(frozen=True)
class ToolPermission:
    """Permission rules for a single tool category."""

    rules: tuple[PermissionRule, ...] = ()

    @classmethod
    def from_raw(cls, raw: str | dict[str, str] | list | None) -> ToolPermission:
        """Normalize diverse input formats into a ToolPermission."""
        if raw is None:
            return cls()
        if isinstance(raw, str):
            # "allow" / "deny" / "ask" → single catch-all rule
            return cls(rules=(PermissionRule(pattern="**", verdict=PermissionVerdict(raw)),))
        if isinstance(raw, dict):
            rules = tuple(PermissionRule.from_raw({k: v}) for k, v in raw.items())
            return cls(rules=rules)
        if isinstance(raw, list):
            rules = tuple(PermissionRule.from_raw(item) for item in raw)
            return cls(rules=rules)
        raise TypeError(f"Cannot parse ToolPermission from {type(raw)}: {raw!r}")


@dataclass(frozen=True)
class PermissionSpec:
    """Complete permission specification for an Agent."""

    read: ToolPermission = field(default_factory=ToolPermission)
    edit: ToolPermission = field(default_factory=ToolPermission)
    bash: ToolPermission = field(default_factory=ToolPermission)
    webfetch: ToolPermission = field(default_factory=ToolPermission)
    websearch: ToolPermission = field(default_factory=ToolPermission)
    task: ToolPermission = field(default_factory=ToolPermission)
    external_directory: PermissionVerdict = PermissionVerdict.DENY

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> PermissionSpec:
        """Parse a raw permission dict into a PermissionSpec."""
        if raw is None:
            return cls()
        return cls(
            read=ToolPermission.from_raw(raw.get("read")),
            edit=ToolPermission.from_raw(raw.get("edit")),
            bash=ToolPermission.from_raw(raw.get("bash")),
            webfetch=ToolPermission.from_raw(raw.get("webfetch")),
            websearch=ToolPermission.from_raw(raw.get("websearch")),
            task=ToolPermission.from_raw(raw.get("task")),
            external_directory=PermissionVerdict(raw.get("external_directory", "deny")),
        )


# ---------------------------------------------------------------------------
# Task permission (controls which agents a model/command can invoke via Task)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskPermissionSpec:
    """Normalized permission for which target agents can be invoked via Task Tool.

    This is the INTERNAL representation compiled from ``permission.task``.
    It is NOT a public configuration source — users write ``permission.task``
    in agent definitions; loaders produce this normalized form.
    """

    allowed_agents: tuple[str, ...] = ()
    denied_agents: tuple[str, ...] = ()
    default_verdict: PermissionVerdict = PermissionVerdict.DENY

    def allows(self, target_agent_id: str) -> bool:
        """Check whether invoking *target_agent_id* via Task is permitted."""
        if target_agent_id in self.denied_agents:
            return False
        if target_agent_id in self.allowed_agents:
            return True
        return self.default_verdict == PermissionVerdict.ALLOW

    @classmethod
    def from_raw(cls, raw: str | dict[str, str] | None) -> TaskPermissionSpec:
        """Parse permission.task from raw config into TaskPermissionSpec."""
        if raw is None:
            return cls(default_verdict=PermissionVerdict.DENY)
        if isinstance(raw, str):
            return cls(default_verdict=PermissionVerdict(raw))
        # dict: {"explore": "allow", "general": "deny"}
        allowed = []
        denied = []
        default = PermissionVerdict.DENY
        for agent_id, verdict_str in raw.items():
            verdict = PermissionVerdict(verdict_str)
            if agent_id == "**":
                default = verdict
            elif verdict == PermissionVerdict.ALLOW:
                allowed.append(agent_id)
            elif verdict == PermissionVerdict.DENY:
                denied.append(agent_id)
        return cls(
            allowed_agents=tuple(allowed),
            denied_agents=tuple(denied),
            default_verdict=default,
        )


# ---------------------------------------------------------------------------
# Core agent definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentDefinition:
    """Immutable, validated definition of an agent.

    This is the single source of truth produced by loading JSON, Markdown,
    or YAML agent definitions. All fields are frozen after construction.
    """

    id: str
    description: str
    mode: AgentMode = AgentMode.SUBAGENT
    prompt: str | None = None
    model: str | None = None               # None = inherit Primary model
    steps: int | None = None               # Max agentic iterations per invocation
    permission: PermissionSpec = field(default_factory=PermissionSpec)
    task_permission: TaskPermissionSpec = field(default_factory=TaskPermissionSpec)
    hidden: bool = False
    subagent_depth: int = 1                # 0=disable, 1=Primary→Child, 2=one more level
    workspace_scope: WorkspaceMode = WorkspaceMode.READ_ONLY
    extra: Mapping[str, object] = field(default_factory=dict)

    # -- derived properties -------------------------------------------------

    @property
    def is_primary_capable(self) -> bool:
        """Can serve as a user-facing primary agent?"""
        return self.mode in (AgentMode.PRIMARY, AgentMode.ALL)

    @property
    def is_subagent_capable(self) -> bool:
        """Can be dispatched as a child/subagent?"""
        return self.mode in (AgentMode.SUBAGENT, AgentMode.ALL)

    @property
    def can_create_children(self) -> bool:
        """Can this agent spawn child sessions?"""
        return self.subagent_depth > 0 and self.is_primary_capable


# ---------------------------------------------------------------------------
# Context envelope — what the child receives
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContextReference:
    """A single reference passed into a child session."""

    kind: str                              # "file", "item", "directory", "artifact"
    path: str = ""
    item_id: str = ""
    sha256: str = ""
    visibility: Literal["full", "summary"] = "summary"


@dataclass(frozen=True)
class ContextEnvelope:
    """Minimal context passed from Primary to Child.

    The child MUST NOT receive the full Primary conversation history.
    """

    parent_session_id: str
    task: str                              # Human-readable task description
    references: tuple[ContextReference, ...] = ()
    attachments: tuple[str, ...] = ()      # Content block ids
    redactions: tuple[str, ...] = ("secret", "api_key", "authorization")
    max_context_tokens: int = 12000


# ---------------------------------------------------------------------------
# Task request / result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetSpec:
    """Budget limits proposed by the caller, enforced by the server."""

    max_steps: int = 12
    max_tokens: int = 8000
    max_wall_time_seconds: int = 300
    max_concurrent_children: int = 3


@dataclass(frozen=True)
class WorkspaceScope:
    """Workspace access declaration for a child session."""

    mode: WorkspaceMode = WorkspaceMode.READ_ONLY
    leased_paths: tuple[str, ...] = ()     # Paths under lease (leased_write mode)
    lease_id: str = ""                     # Lease identifier for tracking


@dataclass(frozen=True)
class TaskRequest:
    """Request to create and dispatch a child session."""

    request_id: str = field(default_factory=lambda: str(uuid4()))
    parent_session_id: str = ""
    agent_id: str = ""
    prompt: str = ""
    context: ContextEnvelope | None = None
    trigger: TriggerKind = TriggerKind.AUTOMATIC
    output_schema: str | None = None
    requested_budget: BudgetSpec | None = None
    requested_workspace: WorkspaceScope | None = None


@dataclass(frozen=True)
class EffectiveTaskPolicy:
    """Server-computed policy snapshot persisted with the child session.

    This is the AUTHORITATIVE policy — the child cannot widen it.
    """

    task_permission: TaskPermissionSpec = field(default_factory=TaskPermissionSpec)
    subagent_depth: int = 1
    remaining_child_depth: int = 0
    budget: BudgetSpec = field(default_factory=BudgetSpec)
    workspace: WorkspaceScope = field(default_factory=WorkspaceScope)
    permission: PermissionSpec = field(default_factory=PermissionSpec)


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to a child-produced artifact."""

    kind: str
    ref: str
    sha256: str = ""


@dataclass(frozen=True)
class EvidenceRef:
    """Reference to evidence discovered by a child."""

    path: str
    line: int = 0
    sha256: str = ""


@dataclass(frozen=True)
class UsageRecord:
    """Token and step usage for a child session."""

    steps: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    wall_time_ms: int = 0
    retry_count: int = 0


@dataclass(frozen=True)
class ErrorRecord:
    """Structured error from a failed child session."""

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskResult:
    """Structured result returned from a child session to Primary."""

    request_id: str
    child_session_id: str
    status: ChildStatus
    summary: str = ""
    artifacts: tuple[ArtifactRef, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    usage: UsageRecord = field(default_factory=UsageRecord)
    error: ErrorRecord | None = None

    @property
    def is_terminal(self) -> bool:
        """Has the child reached a terminal state?"""
        return self.status in (
            ChildStatus.COMPLETED,
            ChildStatus.FAILED,
            ChildStatus.CANCELLED,
            ChildStatus.DENIED,
            ChildStatus.TIMED_OUT,
        )
