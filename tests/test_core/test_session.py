import pytest
from pathlib import Path
from pydantic import BaseModel

from core.session import (
    PromptResult,
    Session,
    notification_to_sse_event,
    thinking_cursor,
    thinking_since,
)
from protocol.notifications import ErrorNotification, FinalAnswer


class _FakeAgent:
    def __init__(self, answer: str = "ok", *, fail: bool = False):
        self._answer = answer
        self._fail = fail
        self._cancelled = False
        self._thinking_history: list[str] = []
        self._last_thinking = ""

    async def run(self, text: str, mode: str = "build") -> str:
        if self._fail:
            raise RuntimeError("boom")
        return self._answer

    def cancel(self) -> bool:
        self._cancelled = True
        return True


@pytest.mark.asyncio
async def test_session_prompt_emits_final_answer():
    emitted: list[BaseModel] = []
    session = Session(
        session_id="s1",
        workspace_root=Path("/tmp/ws"),
        emit=emitted.append,
        session_schema_version=3,
    )
    result = await session.prompt(
        _FakeAgent("hello"),
        "hi",
        mode="build",
        run_id="run-1",
    )
    assert result.status == "succeeded"
    assert result.answer == "hello"
    assert any(isinstance(item, FinalAnswer) for item in emitted)
    final = next(item for item in emitted if isinstance(item, FinalAnswer))
    assert final.text == "hello"
    assert final.run_id == "run-1"


@pytest.mark.asyncio
async def test_session_prompt_emits_error_on_exception():
    emitted: list[BaseModel] = []
    session = Session(session_id="s1", workspace_root=Path("/tmp/ws"), emit=emitted.append)
    result = await session.prompt(
        _FakeAgent(fail=True),
        "hi",
        mode="build",
        run_id="run-2",
    )
    assert result.status == "failed"
    assert any(isinstance(item, ErrorNotification) for item in emitted)


def test_notification_to_sse_event_maps_final():
    event = notification_to_sse_event(
        FinalAnswer(
            session_id="s1",
            run_id="run-1",
            text="answer",
            thinking="thought",
            input_tokens=1,
            output_tokens=2,
            session_schema_version=3,
        )
    )
    assert event == {
        "type": "final",
        "run_id": "run-1",
        "text": "answer",
        "thinking": "thought",
        "input_tokens": 1,
        "output_tokens": 2,
        "session_schema_version": 3,
    }


def test_session_interrupt_delegates_to_agent():
    agent = _FakeAgent()
    session = Session(session_id="s1", workspace_root=Path("/tmp/ws"), emit=lambda _: None)
    assert session.interrupt(agent) is True
    assert agent._cancelled is True


def test_thinking_since_returns_delta():
    agent = _FakeAgent()
    agent._thinking_history = ["a"]
    cursor = thinking_cursor(agent)
    agent._thinking_history = ["a", "b"]
    assert thinking_since(agent, cursor) == "b"