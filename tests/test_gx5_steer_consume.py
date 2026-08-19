"""GX5-B path A: consume B5 turn/steer and turn/interrupt. No new protocol."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.server import AppServer
from protocol.requests import TurnInterruptRequest, TurnSteerRequest


def test_probe_steer_and_interrupt_already_exist() -> None:
    assert TurnSteerRequest.model_fields["method"].default == "turn/steer"
    steer = TurnSteerRequest(session_id="s", text="nudge")
    assert steer.text == "nudge"
    assert TurnInterruptRequest.model_fields["method"].default == "turn/interrupt"
    assert TurnInterruptRequest(session_id="s").method == "turn/interrupt"


@pytest.mark.asyncio
async def test_appserver_steer_not_running_and_idle_interrupt(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="gx5")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "turn/steer",
            "params": {"session_id": session.session_id, "text": "steer now"},
        }
    )
    err = next(item["error"] for item in sent if item.get("id") == 1)
    assert err["data"]["error_code"] == "TURN_NOT_RUNNING"
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "turn/interrupt",
            "params": {"session_id": session.session_id},
        }
    )
    result = next(item["result"] for item in sent if item.get("id") == 2)
    assert result["session_id"] == session.session_id
    assert result["cancelled"] is False


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
