"""Server -> client messages that require a client reply."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .types import ApprovalDecisionName, JsonObject, RiskLevelName


class ApprovalRequest(BaseModel):
    """Maps ``ApprovalRequest.to_event()`` SSE in core/safety/approval.py."""

    method: Literal["approval/request"] = "approval/request"
    session_id: str
    request_id: str
    risk_level: RiskLevelName
    action: str
    details: JsonObject = Field(default_factory=dict)


class ApprovalResponse(BaseModel):
    """Reply consumed by ``POST /approve`` (api_server.py) / ``SseApproval``."""

    request_id: str
    decision: ApprovalDecisionName


class QuestionOption(BaseModel):
    """One choice row in ``QuestionRequest.options`` (``core/question.py`` ``QuestionOption.to_event``)."""

    label: str
    value: str


class QuestionRequest(BaseModel):
    """Maps ``QuestionRequest.to_event()`` in core/question.py."""

    method: Literal["question/request"] = "question/request"
    session_id: str
    question_id: str
    question: str
    header: str = ""
    options: list[QuestionOption] = Field(default_factory=list)
    input_type: Literal["choice", "text"] = "text"


class QuestionResponse(BaseModel):
    """Answer payload resolved by ``SseQuestionBroker.resolve`` (core/question.py)."""

    question_id: str
    answer: str | None = None
    cancelled: bool = False
    timed_out: bool = False
    unavailable: bool = False


SERVER_REQUEST_MODELS: tuple[type[BaseModel], ...] = (
    ApprovalRequest,
    ApprovalResponse,
    QuestionRequest,
    QuestionResponse,
)
