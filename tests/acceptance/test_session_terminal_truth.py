"""Independent terminal-truth checks for real Session + ProtocolTui output."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from appserver.tui import ProtocolTui
from core.session import Session
from protocol.notifications import (
    ErrorNotification,
    FinalAnswer,
    MessageDelta,
    ToolBegin,
    ToolEnd,
)
from tests.test_core.test_session import _FakeAgent
from utils.user_facing_errors import to_user_facing_error


EVIDENCE_FAILURE = (
    "[evidence failed: requested side effect has no verified "
    "WRITE/DANGER tool execution]"
)


@pytest.fixture
def session_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("RXYCODE_DATA_DIR", str(tmp_path / "data"))
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


def _stack(
    workspace: Path,
) -> tuple[Session, ProtocolTui, list[BaseModel]]:
    emitted: list[BaseModel] = []
    tui = ProtocolTui("terminal-truth", emitted.append, run_id="run-terminal-truth")
    session = Session(
        session_id="terminal-truth",
        workspace_root=workspace,
        emit=emitted.append,
    )
    return session, tui, emitted


class _StreamingAgent(_FakeAgent):
    def __init__(self, answer: str, tui: ProtocolTui) -> None:
        super().__init__(answer)
        self._tui = tui

    async def run(self, text: str, mode: str = "build") -> str:
        self._tui.stream_token("partial visible text")
        return await super().run(text, mode)


@pytest.mark.asyncio
async def test_nonempty_evidence_failure_after_stream_keeps_failed_truth(
    session_workspace: Path,
) -> None:
    session, tui, emitted = _stack(session_workspace)

    class _EvidenceFailureAgent(_FakeAgent):
        async def run(self, text: str, mode: str = "build") -> str:
            tui.stream_token("partial visible text")
            call_id = tui.write_tool_call(
                "write",
                {"path": "artifacts/report.txt"},
                call_id="call-partial-artifact",
            )
            tui.write_tool_result(
                "wrote artifacts/report.txt",
                status="success",
                call_id=call_id,
            )
            return EVIDENCE_FAILURE

    result = await session.prompt(
        _EvidenceFailureAgent(EVIDENCE_FAILURE),
        "write the report",
        mode="build",
        run_id="run-terminal-truth",
        tui=tui,
    )

    assert result.status == "failed"
    assert result.answer == EVIDENCE_FAILURE
    assert result.detail == EVIDENCE_FAILURE
    assert not any(isinstance(item, FinalAnswer) for item in emitted)

    errors = [item for item in emitted if isinstance(item, ErrorNotification)]
    assert len(errors) == 1
    assert errors[0].status == "failed"
    assert errors[0].message == to_user_facing_error(EVIDENCE_FAILURE)

    # Error is terminal truth, not a destructive replacement for already
    # visible streamed text or a completed tool row.
    assert [
        item.text for item in emitted if isinstance(item, MessageDelta)
    ] == ["partial visible text"]
    begin = next(item for item in emitted if isinstance(item, ToolBegin))
    end = next(item for item in emitted if isinstance(item, ToolEnd))
    assert begin.call_id == "call-partial-artifact"
    assert end.call_id == "call-partial-artifact"
    assert end.summary == "wrote artifacts/report.txt"
    assert emitted.index(end) < emitted.index(errors[0])


@pytest.mark.asyncio
async def test_stream_only_empty_terminal_answer_keeps_legacy_success(
    session_workspace: Path,
) -> None:
    session, tui, emitted = _stack(session_workspace)

    result = await session.prompt(
        _StreamingAgent("", tui),
        "stream without a terminal string",
        mode="build",
        run_id="run-stream-only",
        tui=tui,
    )

    assert result.status == "succeeded"
    assert result.answer == ""
    assert not any(isinstance(item, ErrorNotification) for item in emitted)
    finals = [item for item in emitted if isinstance(item, FinalAnswer)]
    assert len(finals) == 1
    assert finals[0].text == ""
    assert [
        item.text for item in emitted if isinstance(item, MessageDelta)
    ] == ["partial visible text"]


@pytest.mark.asyncio
async def test_normal_success_still_emits_one_final_answer(
    session_workspace: Path,
) -> None:
    session, tui, emitted = _stack(session_workspace)

    result = await session.prompt(
        _StreamingAgent("complete answer", tui),
        "answer normally",
        mode="build",
        run_id="run-normal-success",
        tui=tui,
    )

    assert result.status == "succeeded"
    assert result.answer == "complete answer"
    assert not any(isinstance(item, ErrorNotification) for item in emitted)
    finals = [item for item in emitted if isinstance(item, FinalAnswer)]
    assert len(finals) == 1
    assert finals[0].text == "complete answer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("[cancelled by user]", "cancelled"),
        ("[task_stall_timeout] provider stopped producing events", "timed_out"),
    ],
)
async def test_cancel_and_timeout_after_stream_keep_their_status(
    session_workspace: Path,
    answer: str,
    expected: str,
) -> None:
    session, tui, emitted = _stack(session_workspace)

    result = await session.prompt(
        _StreamingAgent(answer, tui),
        "stop or time out",
        mode="build",
        run_id=f"run-{expected}",
        tui=tui,
    )

    assert result.status == expected
    assert result.answer == answer
    assert not any(isinstance(item, FinalAnswer) for item in emitted)
    errors = [item for item in emitted if isinstance(item, ErrorNotification)]
    assert len(errors) == 1
    assert errors[0].status == expected
    assert [
        item.text for item in emitted if isinstance(item, MessageDelta)
    ] == ["partial visible text"]
