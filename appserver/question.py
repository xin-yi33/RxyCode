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

# PROBE-20260923: runtime probe (one-grep removal; see D:\tmp-cursor-probe\PROBE-MANIFEST.md)
try:
    from ..core.runtime_probe import probe as _probe
except Exception:
    try:
        from RxyCode.RxyCode1_1_0.core.runtime_probe import probe as _probe
    except Exception:
        try:
            from core.runtime_probe import probe as _probe
        except Exception:
            def _probe(event: str, **fields: Any) -> None:
                return None


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
        # PROBE-20260923: question.ask start — 定位"不限时仍 ~9.5s 自动提交空串"
        _probe(
            "question.ask.start",
            session_id=session_id,
            question_id=request.question_id,
            timeout=self.timeout,
            input_type="choice" if request.options else "text",
        )
        _ask_started = asyncio.get_event_loop().time()
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
            # PROBE-20260923: question.ask end (asyncio timeout path)
            _probe(
                "question.ask.end",
                question_id=request.question_id,
                outcome="asyncio_timeout",
                elapsed_s=round(asyncio.get_event_loop().time() - _ask_started, 3),
            )
            return QuestionResponse(question_id=request.question_id, timed_out=True)
        except Exception as exc:
            # PROBE-20260923: question.ask end (transport error path)
            _probe(
                "question.ask.end",
                question_id=request.question_id,
                outcome="error",
                error=type(exc).__name__,
                elapsed_s=round(asyncio.get_event_loop().time() - _ask_started, 3),
            )
            return QuestionResponse(question_id=request.question_id, unavailable=True)

        if not isinstance(payload, dict):
            _probe(  # PROBE-20260923: question.ask end (bad payload)
                "question.ask.end",
                question_id=request.question_id,
                outcome="bad_payload",
                elapsed_s=round(asyncio.get_event_loop().time() - _ask_started, 3),
            )
            return QuestionResponse(question_id=request.question_id, unavailable=True)
        cancelled = bool(payload.get("cancelled"))
        timed_out = bool(payload.get("timed_out"))
        unavailable = bool(payload.get("unavailable"))
        answer = payload.get("answer")
        if cancelled or timed_out or unavailable:
            answer = None
        elif answer is not None:
            answer = str(answer)
        # PROBE-20260923: question.ask end (normal result)
        _probe(
            "question.ask.end",
            question_id=request.question_id,
            outcome="ok",
            cancelled=cancelled,
            timed_out=timed_out,
            unavailable=unavailable,
            answer_len=len(answer) if answer else 0,
            elapsed_s=round(asyncio.get_event_loop().time() - _ask_started, 3),
        )
        return QuestionResponse(
            question_id=str(payload.get("question_id") or request.question_id),
            answer=answer,
            cancelled=cancelled,
            timed_out=timed_out,
            unavailable=unavailable,
        )
