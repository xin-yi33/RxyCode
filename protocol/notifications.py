"""Server -> client one-way notifications (SSE sources in api_server.py)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, Strict, model_validator

from .types import JobState, JsonObject, RunStatus


# ---------------------------------------------------------------------------
# Phase E · E4 — agent runtime event domain (PHASE-E §4.1)
#
# EB1: add-only.  The ten methods below are the frozen AgentMethod list;
# later additions append, never rename/remove.  The field matrix (per-method
# required/optional/forbidden) is enforced by ``AgentEvent`` validation.
# ``event/team_*`` belongs to the F-layer TeamEvent; AgentEvent must never
# accept it (no default fallback).
# ---------------------------------------------------------------------------

AgentMethod = Literal[
    "event/agent_started",
    "event/agent_tool",
    "event/agent_progress",
    "event/agent_done",
    "event/agent_paused",
    "event/agent_cancelled",
    "event/agent_budget_exceeded",
    "event/agent_denied",
    "event/agent_routed",
    "event/agent_team_created",
]

ExperimentTag = Literal["E0", "E1", "E2"]

#: Methods that must carry routing metadata (F10 projection).
_ROUTED_METHODS = frozenset({"event/agent_routed"})

#: Methods that must never carry routing metadata (forbid).
_ROUTING_FORBIDDEN = frozenset(
    {
        "event/agent_started",
        "event/agent_tool",
        "event/agent_progress",
        "event/agent_done",
        "event/agent_paused",
        "event/agent_cancelled",
        "event/agent_budget_exceeded",
        "event/agent_denied",
        "event/agent_team_created",
    }
)

#: Methods that must carry the cumulative token snapshot (F14 anchor).
_BUDGET_SNAPSHOT_REQUIRED = frozenset({"event/agent_budget_exceeded"})


class AgentEvent(BaseModel):
    """Runtime agent event (Phase E4; E-layer bus carries these).

    Field matrix (PHASE-E §4.1, authoritative):
      method                | experiment_tag | cache_miss | tokens | budget | source | routing_reason
      ----------------------|--------------- |------------|--------|--------|--------|---------------
      agent_started         | opt            | opt        | req*   | req*   | opt    | forbid
      agent_tool            | opt            | opt        | req*   | req*   | opt    | forbid
      agent_progress        | opt            | opt        | req*   | req*   | opt    | forbid
      agent_done            | opt            | opt        | req*   | req*   | opt    | forbid
      agent_paused          | opt            | opt        | req*   | req*   | opt    | forbid
      agent_cancelled       | opt            | opt        | req*   | req*   | opt    | forbid
      agent_budget_exceeded | opt            | opt        | **req  | **req  | opt    | forbid
      agent_denied          | opt            | opt        | req*   | req*   | opt    | forbid
      agent_routed          | **req          | opt        | req*   | req*   | opt    | **req
      agent_team_created    | forbid         | opt        | req*   | req*   | opt    | forbid

    ``req*`` = the E3 runtime always writes these (0 at spawn, monotonic);
    the schema compatibility layer allows them to be absent (historical
    events).  ``**req`` = hard requirement at this layer; ``forbid`` =
    carrying the field is rejected.  ``tokens_used``/``budget_used`` are
    strict ints (bool/str/float rejected) and non-negative cumulative
    snapshots.  ``source`` distinguishes bridge-replayed events; unknown
    values are rejected on construction and deserialization.
    """

    method: AgentMethod
    session_id: str
    agent_id: str
    run_id: str | None = None
    payload: JsonObject = Field(default_factory=dict)
    seq: int
    experiment_tag: ExperimentTag | None = None
    cache_miss_warning: bool = False
    tokens_used: Annotated[int, Strict()] | None = None
    budget_used: Annotated[int, Strict()] | None = None
    source: Literal["internal", "bridge"] | None = "internal"
    routing_reason: str | None = None

    @model_validator(mode="after")
    def _check_field_matrix(self) -> "AgentEvent":
        if self.method in _ROUTED_METHODS:
            if self.experiment_tag is None:
                raise ValueError("event/agent_routed requires experiment_tag")
            if self.routing_reason is None:
                raise ValueError("event/agent_routed requires routing_reason")
        if self.method in _ROUTING_FORBIDDEN and self.routing_reason is not None:
            raise ValueError(
                f"{self.method} must not carry routing_reason"
            )
        if self.method == "event/agent_team_created" and self.experiment_tag is not None:
            raise ValueError(
                "event/agent_team_created must not carry experiment_tag"
            )
        if self.method in _BUDGET_SNAPSHOT_REQUIRED:
            if self.tokens_used is None or self.budget_used is None:
                raise ValueError(
                    "event/agent_budget_exceeded requires tokens_used and budget_used"
                )
        for name in ("tokens_used", "budget_used"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.experiment_tag is not None:
            _check_text_field("experiment_tag", self.experiment_tag, 256)
        if self.routing_reason is not None:
            _check_text_field("routing_reason", self.routing_reason, 256)
        return self


def _check_text_field(name: str, value: str, max_len: int) -> None:
    """Non-empty, length-capped, control-character-free text (PHASE-E §4.1)."""
    if not value:
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_len:
        raise ValueError(f"{name} must be at most {max_len} characters")
    if any(ch < " " for ch in value):
        raise ValueError(f"{name} must not contain control characters")


class MessageDelta(BaseModel):
    """SSE ``type: token`` via ``StreamTUI._buffer("token")`` / flush (api_server.py)."""

    method: Literal["event/message_delta"] = "event/message_delta"
    session_id: str
    text: str


class ProgressUpdate(BaseModel):
    """SSE ``type: progress`` from ``StreamTUI.write_progress`` (api_server.py)."""

    method: Literal["event/progress"] = "event/progress"
    session_id: str
    text: str


class ReasoningSnapshot(BaseModel):
    """SSE ``type: reasoning`` with ``snapshot: true`` from ``StreamTUI._emit_thinking_snapshot`` (api_server.py)."""

    method: Literal["event/reasoning_snapshot"] = "event/reasoning_snapshot"
    session_id: str
    text: str
    snapshot: bool = True


class PlanUpdate(BaseModel):
    """SSE ``type: plan`` from ``StreamTUI.write_plan`` (api_server.py)."""

    method: Literal["event/plan"] = "event/plan"
    session_id: str
    steps: list[str]


class StepProgress(BaseModel):
    """SSE ``type: step`` from ``StreamTUI.write_step`` (api_server.py)."""

    method: Literal["event/step"] = "event/step"
    session_id: str
    index: int
    total: int
    text: str


class TaskStarted(BaseModel):
    """Structured task boundary for LangGraph runs (future emit from chat worker)."""

    method: Literal["event/task_started"] = "event/task_started"
    session_id: str
    task_id: str
    title: str


class ToolBegin(BaseModel):
    """SSE ``type: tool_call`` from ``StreamTUI.write_tool_call`` (api_server.py)."""

    method: Literal["event/tool_begin"] = "event/tool_begin"
    session_id: str
    call_id: str
    tool_name: str
    arguments: JsonObject = Field(default_factory=dict)


class ToolEnd(BaseModel):
    """SSE ``type: tool_result`` from ``StreamTUI.write_tool_result`` (api_server.py)."""

    method: Literal["event/tool_end"] = "event/tool_end"
    session_id: str
    call_id: str
    ok: bool
    summary: str
    status: str | None = None


class TaskComplete(BaseModel):
    """Structured task completion paired with ``TaskStarted``."""

    method: Literal["event/task_complete"] = "event/task_complete"
    session_id: str
    task_id: str
    ok: bool


class TokenUsage(BaseModel):
    """Reported token usage; unknown provider values stay explicitly null."""

    method: Literal["event/token_usage"] = "event/token_usage"
    session_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_hit_rate: float | None = None
    reporting_status: Literal["reported", "partial", "not_reported"] = "reported"


class FinalAnswer(BaseModel):
    """SSE ``type: final`` payload in ``/chat/stream`` worker (api_server.py)."""

    method: Literal["event/final"] = "event/final"
    session_id: str
    run_id: str
    text: str
    thinking: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_write_tokens: int | None = None
    cache_hit_rate: float | None = None
    reporting_status: Literal["reported", "partial", "not_reported"] = "reported"
    session_schema_version: int | None = None


class RecoveryEventBase(BaseModel):
    """Common cursor-safe envelope for recovery lifecycle notifications."""

    session_id: str
    run_id: str
    recovery_id: str
    event_id: str
    seq: int
    timestamp: str


class RecoveryStarted(RecoveryEventBase):
    """Recovery budget opened after an operational failure."""
    method: Literal["event/recovery_started"] = "event/recovery_started"
    source_call_id: str
    recovery_kind: Literal["transport_retry", "model_recovery", "graph_replan"]
    error_kind: str
    max_attempts: int


class RecoveryAnalyzing(RecoveryEventBase):
    """Recovery planner is selecting the next user-safe strategy."""
    method: Literal["event/recovery_analyzing"] = "event/recovery_analyzing"


class RecoveryAttempt(RecoveryEventBase):
    """One concrete recovery strategy has been scheduled."""
    method: Literal["event/recovery_attempt"] = "event/recovery_attempt"
    attempt: int
    strategy: Literal[
        "same_tool",
        "corrected_arguments",
        "alternative_tool",
        "retry_task",
        "replan",
    ]
    replacement_call_id: str | None = None
    display_summary: str


class RecoveryResolved(RecoveryEventBase):
    """Recovery completed and the task returned to normal execution."""
    method: Literal["event/recovery_resolved"] = "event/recovery_resolved"
    attempts: int
    display_summary: str


class RecoveryExhausted(RecoveryEventBase):
    """Recovery budget was exhausted and a terminal error may be shown."""
    method: Literal["event/recovery_exhausted"] = "event/recovery_exhausted"
    attempts: int
    final_error: str


class ErrorNotification(BaseModel):
    """SSE ``type: error`` from ``StreamTUI.write_error`` and chat worker (api_server.py)."""

    method: Literal["event/error"] = "event/error"
    session_id: str
    message: str
    run_id: str | None = None
    status: RunStatus | None = None


class RunComplete(BaseModel):
    """SSE ``type: done`` from chat stream teardown (api_server.py)."""

    method: Literal["event/done"] = "event/done"
    session_id: str
    run_id: str
    status: RunStatus


class JobStatusUpdate(BaseModel):
    """Background job state for watchdog / appserver (submitted|running|failed)."""

    method: Literal["event/job_status"] = "event/job_status"
    session_id: str
    job_id: str
    state: JobState



class ServerHeartbeat(BaseModel):
    """Periodic appserver liveness signal (T4 watchdog)."""

    method: Literal["event/server_heartbeat"] = "event/server_heartbeat"
    uptime_seconds: float
    active_jobs: int
    degraded: bool


class InitializedNotification(BaseModel):
    """PhaseG-B2 handshake complete. No response expected."""

    method: Literal["initialized"] = "initialized"
    protocol_version: str
    server_version: str


class ProcessStarted(BaseModel):
    """PhaseG-B3 appserver process is up and holding the instance lock."""

    method: Literal["event/process_started"] = "event/process_started"
    pid: int
    started_at: float
    instance_policy: str = "single-instance-per-data-dir"


class ProcessShutdown(BaseModel):
    """PhaseG-B3 graceful shutdown. Incomplete work is not marked completed."""

    method: Literal["event/process_shutdown"] = "event/process_shutdown"
    reason: str
    graceful: bool


class RecoveryRequired(BaseModel):
    """PhaseG-B3 restart found an unfinished turn. UI must not show success."""

    method: Literal["event/recovery_required"] = "event/recovery_required"
    session_id: str
    previous_status: str
    status: str = "recovery_required"


class ProcessFailed(BaseModel):
    """PhaseG-B3 failed to become the instance (lock or boot)."""

    method: Literal["event/process_failed"] = "event/process_failed"
    reason: str
    error_code: str


NOTIFICATION_MODELS: tuple[type[BaseModel], ...] = (
    AgentEvent,
    MessageDelta,
    ProgressUpdate,
    ReasoningSnapshot,
    PlanUpdate,
    StepProgress,
    TaskStarted,
    ToolBegin,
    ToolEnd,
    TaskComplete,
    TokenUsage,
    FinalAnswer,
    RecoveryStarted,
    RecoveryAnalyzing,
    RecoveryAttempt,
    RecoveryResolved,
    RecoveryExhausted,
    ErrorNotification,
    RunComplete,
    JobStatusUpdate,
    ServerHeartbeat,
    InitializedNotification,
    ProcessStarted,
    ProcessShutdown,
    RecoveryRequired,
    ProcessFailed,
)
