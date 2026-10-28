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


MODEL_GONE_RAW = (
    "APIStatusError: Error code: 410 - {'type': 'error', 'error': "
    "{'type': 'ModelDeprecated', 'message': 'Model deepseek-flash is deprecated'}}"
)


@pytest.mark.asyncio
async def test_model_deprecated_answer_is_failed_not_completed(
    session_workspace: Path,
) -> None:
    """2026-10-28 现场回归：服务商 410 被 agent 吞成友好文案字符串返回时，
    终态必须是 failed（徽标「失败」），不是 succeeded+FinalAnswer 的
    绿色「已完成」；结构化 code 要能进 run.error 载荷。"""
    session, tui, emitted = _stack(session_workspace)

    # 现场形态：agent 把异常吞成「处理未完成，请重试。\n原因：<原始报文>」。
    swallowed = f"处理未完成，请重试。\n原因：{MODEL_GONE_RAW}"
    result = await session.prompt(
        _StreamingAgent(swallowed, tui),
        "use a deprecated model",
        mode="build",
        run_id="run-model-deprecated",
        tui=tui,
    )

    assert result.status == "failed"
    assert result.error_code == "MODEL_UNAVAILABLE"
    assert "ModelDeprecated" in result.error_raw or "410" in result.error_raw
    assert not any(isinstance(item, FinalAnswer) for item in emitted)
    errors = [item for item in emitted if isinstance(item, ErrorNotification)]
    assert len(errors) == 1
    assert errors[0].status == "failed"


@pytest.mark.asyncio
async def test_model_unavailable_message_alone_still_carries_code(
    session_workspace: Path,
) -> None:
    """ swallow 路径只回了新文案（无原始报文）时，own-message 识别
    仍给出 MODEL_UNAVAILABLE —— 界面才能给「切换模型」。"""
    session, tui, emitted = _stack(session_workspace)

    friendly = to_user_facing_error(
        MODEL_GONE_RAW,
        model_name="deepseek-flash",
        provider_name="OpenCode Go",
    )
    assert "停用" in friendly
    result = await session.prompt(
        _StreamingAgent(friendly, tui),
        "use a deprecated model",
        mode="build",
        run_id="run-model-deprecated-2",
        tui=tui,
    )

    assert result.status == "failed"
    assert result.error_code == "MODEL_UNAVAILABLE"
    assert not any(isinstance(item, FinalAnswer) for item in emitted)


@pytest.mark.asyncio
async def test_cancelled_friendly_message_is_cancelled_not_succeeded(
    session_workspace: Path,
) -> None:
    """「操作已取消。」也曾被 classify 判成 succeeded+FinalAnswer。"""
    session, tui, emitted = _stack(session_workspace)

    result = await session.prompt(
        _StreamingAgent("操作已取消。", tui),
        "cancel please",
        mode="build",
        run_id="run-user-cancelled",
        tui=tui,
    )

    assert result.status == "cancelled"
    assert not any(isinstance(item, FinalAnswer) for item in emitted)
