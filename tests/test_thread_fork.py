"""GX8-B: thread/fork from a user message; thread/pin; session/rename+archive reused."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.server import AppServer
from appserver.thread_fork import ThreadForkError, ThreadForkService
from protocol.requests import (
    SessionArchiveRequest,
    SessionForkRequest,
    SessionRenameRequest,
    ThreadForkRequest,
    ThreadPinRequest,
)


def test_probe_reuse_rename_archive_and_new_fork() -> None:
    assert SessionRenameRequest.model_fields["method"].default == "session/rename"
    assert SessionArchiveRequest.model_fields["method"].default == "session/archive"
    assert SessionForkRequest.model_fields["method"].default == "session/fork"
    assert ThreadForkRequest.model_fields["method"].default == "thread/fork"
    fork = ThreadForkRequest(thread_id="t", message_id="m1", edited_text="edit")
    assert fork.edited_text == "edit"
    assert ThreadPinRequest(thread_id="t").pinned is True


def test_fork_from_user_message_keeps_parent(tmp_path: Path) -> None:
    server = AppServer(stub=True)
    parent = server._sessions.create(tmp_path, title="src")
    parent.permission_snapshot = {"profile": "ask"}
    svc = ThreadForkService(server._sessions)
    svc.add_message(parent.session_id, message_id="u1", role="user", text="first")
    svc.add_message(parent.session_id, message_id="a1", role="assistant", text="ok")
    svc.add_message(parent.session_id, message_id="u2", role="user", text="second")
    with pytest.raises(ThreadForkError, match="user message"):
        svc.fork(thread_id=parent.session_id, message_id="a1")
    result = svc.fork(thread_id=parent.session_id, message_id="u1", edited_text="first edited")
    assert result["forked_from"] == parent.session_id
    assert result["copied_messages"] == 1
    assert result["permission_snapshot"] == {}
    child_msgs = svc.messages(result["thread_id"])
    assert child_msgs[-1]["text"] == "first edited"
    assert [item["message_id"] for item in svc.messages(parent.session_id)] == ["u1", "a1", "u2"]
    pinned = svc.pin(parent.session_id, pinned=True)
    assert pinned["pinned"] is True
    assert server._sessions.get(parent.session_id).pinned is True


@pytest.mark.asyncio
async def test_appserver_thread_fork_and_pin_rpc(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    parent = server._sessions.create(tmp_path, title="src")
    server._thread_fork.add_message(parent.session_id, message_id="u1", role="user", text="hi")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "thread/fork",
            "params": {"thread_id": parent.session_id, "message_id": "u1"},
        }
    )
    forked = next(item["result"] for item in sent if item.get("id") == 1)
    assert forked["thread_id"] != parent.session_id
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "thread/pin",
            "params": {"thread_id": parent.session_id, "pinned": True},
        }
    )
    pin = next(item["result"] for item in sent if item.get("id") == 2)
    assert pin["pinned"] is True


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
