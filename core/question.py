"""Interactive user-question protocol, independent from safety approvals.

Safety approval decisions answer whether a tool may run.  User questions carry
application data (an option value or free text), so they intentionally use a
separate request/response registry and transport.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class QuestionOption:
    label: str
    value: str

    def to_event(self) -> dict[str, str]:
        return {"label": self.label, "value": self.value}


@dataclass
class QuestionRequest:
    question: str
    header: str = ""
    options: list[QuestionOption] = field(default_factory=list)
    question_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self) -> None:
        self.question = str(self.question)[:4000]
        self.header = str(self.header)[:200]
        normalized: list[QuestionOption] = []
        for option in self.options[:100]:
            if isinstance(option, QuestionOption):
                normalized.append(option)
            elif isinstance(option, dict):
                value = str(option.get("value", option.get("label", "")))
                label = str(option.get("label", value))
                normalized.append(QuestionOption(label=label, value=value))
        self.options = normalized

    def to_event(self) -> dict:
        return {
            "type": "question_request",
            "question_id": self.question_id,
            "question": self.question,
            "header": self.header,
            "options": [option.to_event() for option in self.options],
            "input_type": "choice" if self.options else "text",
        }


@dataclass(frozen=True)
class QuestionResponse:
    question_id: str
    answer: str | None = None
    cancelled: bool = False
    timed_out: bool = False
    unavailable: bool = False


class SseQuestionBroker:
    """Publish questions to SSE and resolve answers on the owner event loop."""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._pending: dict[str, asyncio.Event] = {}
        self._pending_loops: dict[str, asyncio.AbstractEventLoop] = {}
        self._requests: dict[str, QuestionRequest] = {}
        self._responses: dict[str, QuestionResponse] = {}
        self._sink: Optional[Callable[[dict], None]] = None

    def set_event_sink(self, sink: Optional[Callable[[dict], None]]) -> None:
        self._sink = sink

    async def ask(self, request: QuestionRequest) -> QuestionResponse:
        sink = self._sink
        if sink is None:
            return QuestionResponse(
                question_id=request.question_id,
                unavailable=True,
            )
        event = asyncio.Event()
        owner_loop = asyncio.get_running_loop()
        question_id = request.question_id
        self._pending[question_id] = event
        self._pending_loops[question_id] = owner_loop
        self._requests[question_id] = request
        try:
            sink(request.to_event())
        except Exception:
            # A sink can disappear between channel setup and publication.
            # Fail fast instead of leaving an API worker blocked until timeout.
            self._pending.pop(question_id, None)
            self._pending_loops.pop(question_id, None)
            self._requests.pop(question_id, None)
            return QuestionResponse(question_id=question_id, unavailable=True)
        try:
            await asyncio.wait_for(event.wait(), timeout=self.timeout)
        except asyncio.TimeoutError:
            return QuestionResponse(question_id=question_id, timed_out=True)
        else:
            return self._responses.get(
                question_id,
                QuestionResponse(question_id=question_id, cancelled=True),
            )
        finally:
            self._pending.pop(question_id, None)
            self._pending_loops.pop(question_id, None)
            self._requests.pop(question_id, None)
            self._responses.pop(question_id, None)

    def _resolve_on_owner_loop(
        self,
        question_id: str,
        answer: str | None,
        cancelled: bool,
    ) -> None:
        event = self._pending.get(question_id)
        if event is None:
            return
        self._responses[question_id] = QuestionResponse(
            question_id=question_id,
            answer=answer,
            cancelled=cancelled,
        )
        event.set()

    def resolve(
        self,
        question_id: str,
        answer: str | None = None,
        *,
        cancelled: bool = False,
    ) -> bool:
        """Resolve one request from any thread/event loop.

        Choice questions accept option values, never display labels or safety
        approval enums.  Unknown/expired ids return ``False``.
        """
        request = self._requests.get(question_id)
        if request is None or question_id not in self._pending:
            return False
        if not cancelled:
            if answer is None:
                raise ValueError("answer is required unless cancelled is true")
            answer = str(answer)
            if request.options and answer not in {
                option.value for option in request.options
            }:
                raise ValueError("answer is not one of the offered option values")
        else:
            answer = None

        owner_loop = self._pending_loops.get(question_id)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if owner_loop is not None and owner_loop is not current_loop:
            if not owner_loop.is_running():
                return False
            owner_loop.call_soon_threadsafe(
                self._resolve_on_owner_loop,
                question_id,
                answer,
                cancelled,
            )
        else:
            self._resolve_on_owner_loop(question_id, answer, cancelled)
        return True

    def cancel(self, question_id: str) -> bool:
        return self.resolve(question_id, cancelled=True)

    def cancel_all(self) -> int:
        cancelled = 0
        for question_id in list(self._pending):
            cancelled += int(self.cancel(question_id))
        return cancelled


_broker: Optional[SseQuestionBroker] = None


def get_question_broker() -> Optional[SseQuestionBroker]:
    return _broker


def set_question_broker(broker: Optional[SseQuestionBroker]) -> None:
    global _broker
    _broker = broker
