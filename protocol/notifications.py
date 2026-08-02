"""Server -> client one-way notifications (SSE sources in api_server.py)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .types import JobState, JsonObject, RunStatus


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
    """Token deltas from chat ``final`` SSE payload fields (api_server.py queue)."""

    method: Literal["event/token_usage"] = "event/token_usage"
    session_id: str
    input_tokens: int
    output_tokens: int


class FinalAnswer(BaseModel):
    """SSE ``type: final`` payload in ``/chat/stream`` worker (api_server.py)."""

    method: Literal["event/final"] = "event/final"
    session_id: str
    run_id: str
    text: str
    thinking: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    session_schema_version: int | None = None


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


NOTIFICATION_MODELS: tuple[type[BaseModel], ...] = (
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
    ErrorNotification,
    RunComplete,
    JobStatusUpdate,
)
