"""GX13-B: B12 event probe + event/agent_needs_input."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.needs_input import NEEDS_INPUT_EVENTS, RESPONSE_EVENTS, NeedsInputClassifier
from appserver.server import AppServer
from protocol.notifications import AgentNeedsInput
from protocol.server_requests import ApprovalRequest, QuestionRequest


def test_probe_uses_real_b12_names() -> None:
    assert ApprovalRequest.model_fields["method"].default == "approval/request"
    assert QuestionRequest.model_fields["method"].default == "question/request"
    assert "approval/request" in NEEDS_INPUT_EVENTS
    assert "question/request" in NEEDS_INPUT_EVENTS
    assert "event/done" in RESPONSE_EVENTS
    assert "approval/requested" not in NEEDS_INPUT_EVENTS
    assert AgentNeedsInput.model_fields["method"].default == "event/agent_needs_input"


def test_classify_priority_and_stream_ignored() -> None:
    clf = NeedsInputClassifier()
    assert clf.classify({"method": "approval/request"}) == "needs_input"
    assert clf.classify({"method": "event/done"}) == "response"
    assert clf.classify({"method": "event/message_delta"}) is None
    first = clf.emit_payload(
        {"method": "approval/request", "params": {"session_id": "s", "request_id": "r1", "text": "allow write?"}}
    )
    assert first["kind"] == "needs_input"
    assert first["preview"]
    assert clf.emit_payload(
        {"method": "approval/request", "params": {"session_id": "s", "request_id": "r1"}}
    ) is None


@pytest.mark.asyncio
async def test_appserver_emits_needs_input(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    payload = server._maybe_emit_needs_input(
        {
            "method": "question/request",
            "params": {"session_id": "s1", "question_id": "q1", "question": "Which file?"},
        }
    )
    assert payload["method"] == "event/agent_needs_input"
    await server._drain_emit_writes()
    assert any(item.get("method") == "event/agent_needs_input" for item in sent)


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
