"""Protocol TUI adapter: maps AgentV2 TUI calls to protocol notifications."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

try:
    from ..protocol.notifications import (
        MessageDelta,
        ProgressUpdate,
        ReasoningSnapshot,
        ToolBegin,
        ToolEnd,
    )
except ImportError:
    from protocol.notifications import (
        MessageDelta,
        ProgressUpdate,
        ReasoningSnapshot,
        ToolBegin,
        ToolEnd,
    )

EmitCallback = Callable[[BaseModel], None]


class ProtocolTui:
    """Minimal TUI surface for appserver: emit protocol models, no direct I/O."""

    def __init__(self, session_id: str, emit: EmitCallback) -> None:
        self.session_id = session_id
        self._emit = emit
        self._expand_thinking = False
        self._thinking_acc = ""
        self._mode = "build"
        self._model_name = ""

    def set_thinking_expanded(self, expanded: bool) -> None:
        was = self._expand_thinking
        self._expand_thinking = bool(expanded)
        # Mid-run expand: push accumulated thinking so the client can show it.
        if self._expand_thinking and not was and self._thinking_acc:
            self._emit(
                ReasoningSnapshot(
                    session_id=self.session_id,
                    text=self._thinking_acc,
                    snapshot=True,
                )
            )

    def get_thinking_expanded(self) -> bool:
        return self._expand_thinking

    def set_mode(self, mode: str) -> None:
        self._mode = str(mode)

    def set_model(self, model_name: str) -> None:
        self._model_name = str(model_name)

    def write_progress(self, text: str) -> None:
        self._emit(ProgressUpdate(session_id=self.session_id, text=str(text)))

    def write(self, text: str, color: str = "") -> None:
        self.write_progress(text)

    def write_info(self, text: str) -> None:
        self.write_progress(text)

    def write_success(self, text: str) -> None:
        self.write_progress(text)

    def write_warning(self, text: str) -> None:
        self.write_progress(text)

    def write_error(self, text: str) -> None:
        self.write_progress(f"[error] {text}")

    def write_reasoning(self, text: str) -> None:
        chunk = str(text)
        self._thinking_acc += chunk
        if self._expand_thinking:
            self._emit(
                ReasoningSnapshot(
                    session_id=self.session_id,
                    text=chunk,
                    snapshot=False,
                )
            )

    def stream_token(self, token: str) -> None:
        self._emit(MessageDelta(session_id=self.session_id, text=str(token)))

    def write_plan(self, steps: Any) -> None:
        self.write_progress(f"plan: {steps}")

    def write_step(self, num: int, total: int, desc: str) -> None:
        self.write_progress(f"step {num}/{total}: {desc}")

    def write_tool_call(self, name: str, args: Any, call_id: str | None = None) -> str:
        resolved_id = str(call_id or uuid.uuid4().hex)
        arguments = args if isinstance(args, dict) else {"raw": str(args)}
        self._emit(
            ToolBegin(
                session_id=self.session_id,
                call_id=resolved_id,
                tool_name=str(name),
                arguments=arguments,
            )
        )
        return resolved_id

    def write_tool_result(
        self,
        result: Any,
        *,
        call_id: str | None = None,
        status: str = "success",
    ) -> None:
        self._emit(
            ToolEnd(
                session_id=self.session_id,
                call_id=str(call_id or uuid.uuid4().hex),
                ok=status == "success",
                summary=str(result),
                status=status,
            )
        )

    def set_session_list_fn(self, fn: Any) -> None:
        return None

    def set_new_session_fn(self, fn: Any) -> None:
        return None