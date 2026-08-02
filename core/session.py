"""Headless session facade over AgentV2 (Phase 2 strangler entry point)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from protocol.notifications import ErrorNotification, FinalAnswer, TokenUsage


EmitCallback = Callable[[BaseModel], None]


@dataclass(frozen=True)
class PromptResult:
    """Terminal outcome of one Session.prompt() turn."""

    answer: str
    status: str
    detail: str = ""
    thinking: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def thinking_cursor(agent: Any) -> tuple[tuple[str, ...], str]:
    """Snapshot agent thinking state before a prompt."""
    history = tuple(str(item) for item in getattr(agent, "_thinking_history", []))
    return history, str(getattr(agent, "_last_thinking", "") or "")


def thinking_since(agent: Any, cursor: tuple[tuple[str, ...], str]) -> str:
    """Return thinking text produced since ``thinking_cursor``."""
    previous_history, previous_last = cursor
    current_history = tuple(
        str(item) for item in getattr(agent, "_thinking_history", [])
    )
    if current_history[: len(previous_history)] == previous_history:
        new_history = current_history[len(previous_history) :]
    else:
        new_history = current_history
    if new_history:
        return "\n".join(new_history)
    current_last = str(getattr(agent, "_last_thinking", "") or "")
    return current_last if current_last != previous_last else ""


def notification_to_sse_event(notification: BaseModel) -> dict[str, Any] | None:
    """Map protocol notifications to legacy HTTP SSE event dicts."""
    if isinstance(notification, FinalAnswer):
        event: dict[str, Any] = {
            "type": "final",
            "run_id": notification.run_id,
            "text": notification.text,
            "thinking": notification.thinking or "",
            "input_tokens": notification.input_tokens or 0,
            "output_tokens": notification.output_tokens or 0,
        }
        if notification.session_schema_version is not None:
            event["session_schema_version"] = notification.session_schema_version
        return event
    if isinstance(notification, ErrorNotification):
        event = {
            "type": "error",
            "message": notification.message,
        }
        if notification.run_id is not None:
            event["run_id"] = notification.run_id
        if notification.status is not None:
            event["status"] = notification.status
        return event
    if isinstance(notification, TokenUsage):
        return None
    method = getattr(notification, "method", None)
    if isinstance(method, str) and method.startswith("event/"):
        return None
    return None


class Session:
    """One conversation session. No direct I/O — output flows through ``emit``."""

    def __init__(
        self,
        *,
        session_id: str,
        workspace_root: Path | str,
        emit: EmitCallback,
        session_schema_version: int | None = None,
    ) -> None:
        self.session_id = session_id
        self.workspace_root = Path(workspace_root)
        self.emit = emit
        self.session_schema_version = session_schema_version

    async def prompt(
        self,
        agent: Any,
        text: str,
        *,
        mode: str,
        run_id: str,
    ) -> PromptResult:
        """Run one user turn through AgentV2 and emit terminal protocol events."""
        from RxyCode.RxyCode1_1_0.log.log_helpers import classify_agent_result
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats as token_stats

        previous_input = token_stats.input_tokens
        previous_output = token_stats.output_tokens
        cursor = thinking_cursor(agent)

        try:
            answer = await agent.run(text, mode=mode)
        except Exception as exc:
            detail = str(exc)
            self.emit(
                ErrorNotification(
                    session_id=self.session_id,
                    run_id=run_id,
                    message=detail,
                    status="failed",
                )
            )
            return PromptResult(answer="", status="failed", detail=detail)

        status, detail = classify_agent_result(answer)
        delta_input = token_stats.input_tokens - previous_input
        delta_output = token_stats.output_tokens - previous_output
        thinking = thinking_since(agent, cursor)

        if delta_input or delta_output:
            self.emit(
                TokenUsage(
                    session_id=self.session_id,
                    input_tokens=max(delta_input, 0),
                    output_tokens=max(delta_output, 0),
                )
            )

        if status == "succeeded":
            self.emit(
                FinalAnswer(
                    session_id=self.session_id,
                    run_id=run_id,
                    text=answer,
                    thinking=thinking or None,
                    input_tokens=delta_input,
                    output_tokens=delta_output,
                    session_schema_version=self.session_schema_version,
                )
            )
            return PromptResult(
                answer=answer,
                status=status,
                detail=detail,
                thinking=thinking,
                input_tokens=delta_input,
                output_tokens=delta_output,
            )

        self.emit(
            ErrorNotification(
                session_id=self.session_id,
                run_id=run_id,
                message=detail,
                status=status,
            )
        )
        return PromptResult(
            answer=answer,
            status=status,
            detail=detail,
            thinking=thinking,
            input_tokens=delta_input,
            output_tokens=delta_output,
        )

    def interrupt(self, agent: Any) -> bool:
        """Request cancellation on the underlying agent, if supported."""
        cancel = getattr(agent, "cancel", None)
        if callable(cancel):
            return bool(cancel())
        return False
