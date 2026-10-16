"""Interactive user-question protocol, independent from safety approvals.

Safety approval decisions answer whether a tool may run.  User questions carry
application data (an option value or free text), so they intentionally use a
separate request/response registry and transport.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
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
        mark_question_pending(
            question_id,
            session_id=_caller_session_id(),
            prompt=request.question,
        )
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
            clear_question_pending(question_id)
            return QuestionResponse(question_id=question_id, unavailable=True)
        try:
            deadline = None
            if self.timeout and self.timeout > 0:
                deadline = asyncio.get_running_loop().time() + self.timeout
            while not event.is_set():
                mailed = take_question_answer(question_id)
                if mailed is not None:
                    self._responses[question_id] = QuestionResponse(
                        question_id=question_id,
                        answer=mailed,
                    )
                    event.set()
                    break
                remaining = None if deadline is None else deadline - asyncio.get_running_loop().time()
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    await asyncio.wait_for(
                        event.wait(),
                        timeout=0.2 if remaining is None else min(0.2, remaining),
                    )
                except asyncio.TimeoutError:
                    continue
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
            clear_question_pending(question_id)

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


def _question_dir() -> Path:
    folder = Path.home() / ".rxycode" / "questions"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _question_token(question_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", question_id):
        raise ValueError("question_id is not a safe token")
    return question_id


def _caller_session_id() -> str:
    try:
        from appserver.runtime import get_bound_session_id
    except ImportError:
        get_bound_session_id = None
    if get_bound_session_id is not None:
        bound = str(get_bound_session_id() or "").strip()
        if bound and bound != "latest":
            return bound
    else:
        bound = ""
    try:
        from core.session_runtime import current_session_id
    except ImportError:
        try:
            from RxyCode.RxyCode1_1_0.core.session_runtime import current_session_id
        except ImportError:
            return bound
    try:
        current = str(current_session_id() or "").strip()
    except (TypeError, ValueError):
        return bound
    if current and current != "latest":
        return current
    return bound or current


def mark_question_pending(question_id: str, *, session_id: str = "", prompt: str = "") -> None:
    token = _question_token(question_id)
    payload = {"question_id": token, "session_id": session_id, "prompt": prompt}
    (_question_dir() / f"{token}.pending.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def publish_question_answer(
    question_id: str,
    answer: str,
    *,
    session_id: str | None = None,
) -> bool:
    token = _question_token(question_id)
    pending = _question_dir() / f"{token}.pending.json"
    if not pending.is_file():
        return False
    try:
        pending_body = json.loads(pending.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    owner = str(pending_body.get("session_id") or "")
    if session_id is not None and owner != session_id:
        return False
    if not pending.is_file():
        return False
    folder = _question_dir()
    answer_path = folder / f"{token}.answer.json"
    if answer_path.exists():
        return False
    payload = json.dumps({"question_id": token, "answer": answer})
    temporary = folder / f"{token}.answer.{uuid.uuid4().hex}.tmp"
    temporary.write_text(payload, encoding="utf-8")
    linked = False
    try:
        os.link(temporary, answer_path)
        linked = True
    except FileExistsError:
        linked = False
    finally:
        temporary.unlink(missing_ok=True)
    return linked


def question_has_answer(question_id: str) -> bool:
    token = _question_token(question_id)
    return (_question_dir() / f"{token}.answer.json").is_file()


def clear_question_pending(question_id: str) -> None:
    token = _question_token(question_id)
    folder = _question_dir()
    (folder / f"{token}.pending.json").unlink(missing_ok=True)
    (folder / f"{token}.answer.json").unlink(missing_ok=True)


def take_question_answer(question_id: str) -> str | None:
    token = _question_token(question_id)
    path = _question_dir() / f"{token}.answer.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or "answer" not in payload:
        return None
    path.unlink(missing_ok=True)
    (_question_dir() / f"{token}.pending.json").unlink(missing_ok=True)
    answer = payload.get("answer")
    return str(answer) if answer is not None else None


def list_pending_questions(session_id: str = "") -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path in _question_dir().glob("*.pending.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if session_id and str(payload.get("session_id") or "") != session_id:
            continue
        if (_question_dir() / f"{payload.get('question_id')}.answer.json").is_file():
            continue
        found.append(
            {
                "question_id": str(payload.get("question_id") or ""),
                "prompt": str(payload.get("prompt") or ""),
                "session_id": str(payload.get("session_id") or ""),
            }
        )
    return found


_broker: Optional[SseQuestionBroker] = None


def get_question_broker() -> Optional[SseQuestionBroker]:
    return _broker


def set_question_broker(broker: Optional[SseQuestionBroker]) -> None:
    global _broker
    _broker = broker
