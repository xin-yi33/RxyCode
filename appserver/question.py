"""JSON-RPC question broker for appserver stdio transport.

Mirrors ``JsonRpcApproval``: the worker publishes ``question/request`` as a
server request and waits for the client's ``QuestionResponse`` result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from RxyCode.RxyCode1_1_0.core.question import (
        QuestionRequest,
        QuestionResponse,
        SseQuestionBroker,
    )
    from .runtime import get_bound_session_id
except ImportError:
    try:
        from ..core.question import QuestionRequest, QuestionResponse, SseQuestionBroker
        from .runtime import get_bound_session_id
    except ImportError:
        from core.question import QuestionRequest, QuestionResponse, SseQuestionBroker
        from appserver.runtime import get_bound_session_id


SendServerRequest = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class PipeQuestionBroker(SseQuestionBroker):
    """Forward interactive questions to the TUI/Desktop over JSON-RPC."""

    def __init__(
        self,
        send_request: SendServerRequest,
        *,
        timeout: float | None = None,
    ) -> None:
        # 废弃代码（2026-09-22）：timeout: float = 120.0
        # question 等用户选择，不该 120 秒自动放弃。
        super().__init__(timeout=0.0 if timeout is None else timeout)
        self._send_request = send_request

    async def ask(self, request: QuestionRequest) -> QuestionResponse:
        session_id = get_bound_session_id()
        params = {
            "session_id": session_id,
            "question_id": request.question_id,
            "question": request.question,
            "header": request.header,
            "options": [option.to_event() for option in request.options],
            "input_type": "choice" if request.options else "text",
        }
        try:
            if self.timeout and self.timeout > 0:
                payload = await asyncio.wait_for(
                    self._send_request("question/request", params),
                    timeout=self.timeout,
                )
            else:
                payload = await self._send_request("question/request", params)
        except asyncio.TimeoutError:
            return QuestionResponse(question_id=request.question_id, timed_out=True)
        except Exception:
            return QuestionResponse(question_id=request.question_id, unavailable=True)

        if not isinstance(payload, dict):
            return QuestionResponse(question_id=request.question_id, unavailable=True)
        cancelled = bool(payload.get("cancelled"))
        timed_out = bool(payload.get("timed_out"))
        unavailable = bool(payload.get("unavailable"))
        answer = payload.get("answer")
        if cancelled or timed_out or unavailable:
            answer = None
        elif answer is not None:
            answer = str(answer)
        return QuestionResponse(
            question_id=str(payload.get("question_id") or request.question_id),
            answer=answer,
            cancelled=cancelled,
            timed_out=timed_out,
            unavailable=unavailable,
        )
