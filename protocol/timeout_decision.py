"""Timeout decision wire models. Field set is pinned by the Phase P test pack."""

from __future__ import annotations

import logging
import math
from contextvars import ContextVar, Token
from typing import Literal

from pydantic import BaseModel, Field, model_validator

_log = logging.getLogger(__name__)
_PUBLISHED_EVENTS: ContextVar[list | None] = ContextVar(
    "rxycode_timeout_published_events", default=None
)

TRIGGER_POINTS = (
    "graph_task_max_time",
    "pipeline_soft_budget",
    "watchdog_stall",
    "tool_timeout",
)
DECISION_ACTIONS = ("continue", "steer", "stop")

ALLOWED_ACTIONS = {
    "graph_task_max_time": {"continue", "steer", "stop"},
    "pipeline_soft_budget": {"continue", "steer", "stop"},
    "watchdog_stall": {"continue", "stop"},
    "tool_timeout": {"continue", "stop"},
}

TriggerPoint = Literal[
    "graph_task_max_time",
    "pipeline_soft_budget",
    "watchdog_stall",
    "tool_timeout",
]
DecisionAction = Literal["continue", "steer", "stop"]


def _require_finite(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite JSON number")


class TimeoutEvidence(BaseModel):
    """决策证据包：LLM 决策的唯一输入。字段全集钉死。"""

    trigger_point: TriggerPoint
    session_id: str
    run_id: str
    subject_id: str
    task_hint: str
    elapsed_seconds: float = Field(ge=0)
    budget_seconds: float = Field(ge=0)
    extension_index: int = Field(ge=0)
    progress: str
    last_error: str

    @model_validator(mode="after")
    def finite_measurements(self) -> TimeoutEvidence:
        _require_finite(self.elapsed_seconds, "elapsed_seconds")
        _require_finite(self.budget_seconds, "budget_seconds")
        return self


class TimeoutDecisionResponse(BaseModel):
    """LLM 决策出参；也是 Policy.pre_check / 事件的同构载体。"""

    action: DecisionAction
    extend_seconds: float = Field(ge=0)
    note: str
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def continue_or_steer_needs_time(self) -> TimeoutDecisionResponse:
        _require_finite(self.extend_seconds, "extend_seconds")
        _require_finite(self.confidence, "confidence")
        if self.action in ("continue", "steer") and self.extend_seconds <= 0:
            raise ValueError("extend_seconds must be > 0 when action is continue or steer")
        return self


class TimeoutDecisionEvent(BaseModel):
    """P7 用户可见面。method 钉死；10 个决策字段钉死。"""

    method: Literal["event/timeout_decision"] = "event/timeout_decision"
    session_id: str
    run_id: str
    event_id: str
    seq: int
    timestamp: str
    trigger_point: TriggerPoint
    action: DecisionAction
    extend_seconds: float
    note: str
    confidence: float = Field(ge=0.0, le=1.0)
    extension_index: int
    elapsed_seconds: float
    fail_closed: bool
    decision_model: str
    cost: float = Field(ge=0)

    @model_validator(mode="after")
    def finite_event_numbers(self) -> TimeoutDecisionEvent:
        _require_finite(self.extend_seconds, "extend_seconds")
        _require_finite(self.confidence, "confidence")
        _require_finite(self.elapsed_seconds, "elapsed_seconds")
        _require_finite(self.cost, "cost")
        return self


def begin_decision_events() -> tuple[list, Token]:
    """Open a per-call bucket. Concurrent decisions do not share it."""
    bucket: list = []
    return bucket, _PUBLISHED_EVENTS.set(bucket)


def end_decision_events(token: Token) -> None:
    _PUBLISHED_EVENTS.reset(token)


def note_published_event(event: TimeoutDecisionEvent) -> None:
    """Record the event settled by the decide call that is running now."""
    bucket = _PUBLISHED_EVENTS.get()
    if bucket is not None:
        bucket.append(event)


def forward_decision_event(engine, tui) -> None:
    """Pass this call's settled events through. Writer errors stay here.

    ``engine`` is unused. The bucket is the one ``begin_decision_events``
    opened on this task, including a child task created after that open.
    """
    del engine
    writer = getattr(tui, "write_timeout_decision", None)
    bucket = _PUBLISHED_EVENTS.get()
    if not callable(writer) or not bucket:
        return
    pending = list(bucket)
    bucket.clear()
    for item in pending:
        try:
            event = (
                item
                if isinstance(item, TimeoutDecisionEvent)
                else TimeoutDecisionEvent.model_validate(item)
            )
            writer(event)
        except Exception:
            _log.warning("timeout decision event was not shown", exc_info=True)
