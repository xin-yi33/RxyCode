"""GX16-B: thread/side_chat/create|close, read-only projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.server import AppServer
from appserver.side_chat import SideChatService
from protocol.requests import ThreadSideChatCloseRequest, ThreadSideChatCreateRequest


def test_protocol_methods() -> None:
    assert ThreadSideChatCreateRequest.model_fields["method"].default == "thread/side_chat/create"
    assert ThreadSideChatCloseRequest.model_fields["method"].default == "thread/side_chat/close"


def test_side_chat_projects_not_copies(tmp_path: Path) -> None:
    server = AppServer(stub=True)
    parent = server._sessions.create(tmp_path, title="main")
    svc = SideChatService(server._sessions)
    created = svc.create(
        thread_id=parent.session_id,
        context_projection=[{"role": "user", "text": "hi"}],
    )
    assert created["context_copied"] is False
    assert created["budget_tag"] == "side"
    side = svc.get(created["side_thread_id"])
    assert side["usage"]["budget_tag"] == "side"
    assert side["context_projection"][0]["text"] == "hi"
    svc.close(side_thread_id=created["side_thread_id"])
    assert svc.get(created["side_thread_id"])["closed"] is True
    other = svc.create(thread_id=parent.session_id)
    svc.close_for_parent(parent.session_id)
    assert svc.get(other["side_thread_id"])["closed"] is True


@pytest.mark.asyncio
async def test_appserver_side_chat_rpc_and_promote_confirm(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    parent = server._sessions.create(tmp_path, title="main")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "thread/side_chat/create",
            "params": {"thread_id": parent.session_id},
        }
    )
    created = next(item["result"] for item in sent if item.get("id") == 1)
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "thread/side_chat/close",
            "params": {"side_thread_id": created["side_thread_id"], "promote": True},
        }
    )
    err = next(item["error"] for item in sent if item.get("id") == 2)
    assert err["data"]["error_code"] == "confirm_required"


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
