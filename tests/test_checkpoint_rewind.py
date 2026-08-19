"""GX4-B: named snapshots + rewind on the session/items read surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.checkpoint_rewind import CheckpointRewindError
from appserver.server import AppServer
from protocol.requests import CheckpointRewindRequest, CheckpointSnapshotCreateRequest


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    return tmp_path


async def _prompt(server: AppServer, session_id: str, text: str, req_id: int) -> None:
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "session/prompt",
            "params": {"session_id": session_id, "text": text},
        }
    )
    for task in list(server._prompt_tasks):
        await task


def test_b8_create_restore_still_exist() -> None:
    assert CheckpointSnapshotCreateRequest.model_fields["method"].default == "checkpoint/snapshot/create"
    assert CheckpointRewindRequest.model_fields["method"].default == "checkpoint/rewind"
    snap = CheckpointSnapshotCreateRequest(name="before", session_id="s")
    assert snap.name == "before"
    rewind = CheckpointRewindRequest(checkpoint_id="cp_x", confirm=True, session_id="s")
    assert rewind.confirm is True


@pytest.mark.asyncio
async def test_named_snapshot_and_rewind_via_session_items(tmp_path: Path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    async def no_worker(**kwargs):
        return None

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    monkeypatch.setattr(server, "_run_prompt", no_worker)
    session = server._sessions.create(root, title="gx4")
    await _prompt(server, session.session_id, "first prompt", 10)
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "checkpoint/snapshot/create",
            "params": {"session_id": session.session_id, "name": "before-edit"},
        }
    )
    named = next(item["result"] for item in sent if item.get("id") == 1)
    assert named["name"] == "before-edit"
    assert named["user_prompt"] == "first prompt"
    (root / "a.txt").write_text("two\n", encoding="utf-8")
    await _prompt(server, session.session_id, "second prompt", 11)
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "checkpoint/snapshot/create",
            "params": {"session_id": session.session_id, "name": "after-edit"},
        }
    )
    later = next(item["result"] for item in sent if item.get("id") == 2)
    with pytest.raises(CheckpointRewindError, match="confirm"):
        server._checkpoint_rewind.rewind(
            checkpoint_id=named["checkpoint_id"],
            confirm=False,
            session_id=session.session_id,
        )
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "checkpoint/rewind",
            "params": {
                "session_id": session.session_id,
                "checkpoint_id": named["checkpoint_id"],
                "confirm": True,
            },
        }
    )
    result = next(item["result"] for item in sent if item.get("id") == 3)
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("one")
    assert result["refill_prompt"] == "first prompt"
    assert result["truncated_messages"] >= 1
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/items",
            "params": {"session_id": session.session_id},
        }
    )
    items = next(item["result"] for item in sent if item.get("id") == 4)["items"]
    texts = [str((row.get("params") or {}).get("text") or "") for row in items]
    assert "first prompt" in texts
    assert "second prompt" not in texts
    listed = server._reviews.list_checkpoints(session.session_id)
    ids = {item["checkpoint_id"] for item in listed}
    assert named["checkpoint_id"] in ids
    assert later["checkpoint_id"] in ids
    assert result["restore_point"] in ids
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "checkpoint/rewind",
            "params": {
                "session_id": session.session_id,
                "checkpoint_id": later["checkpoint_id"],
                "confirm": True,
            },
        }
    )
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("two")


@pytest.mark.asyncio
async def test_appserver_snapshot_rewind_rpc(tmp_path: Path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    async def no_worker(**kwargs):
        return None

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    monkeypatch.setattr(server, "_run_prompt", no_worker)
    session = server._sessions.create(root, title="gx4")
    await _prompt(server, session.session_id, "hello", 20)
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "checkpoint/snapshot/create",
            "params": {"session_id": session.session_id, "name": "snap-1"},
        }
    )
    created = next(item["result"] for item in sent if item.get("id") == 1)
    assert created["name"] == "snap-1"
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    await _prompt(server, session.session_id, "later", 21)
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "checkpoint/rewind",
            "params": {
                "session_id": session.session_id,
                "checkpoint_id": created["checkpoint_id"],
                "confirm": False,
            },
        }
    )
    err = next(item["error"] for item in sent if item.get("id") == 2)
    assert err["data"]["error_code"] == "confirm_required"
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "checkpoint/rewind",
            "params": {
                "session_id": session.session_id,
                "checkpoint_id": created["checkpoint_id"],
                "confirm": True,
            },
        }
    )
    rewound = next(item["result"] for item in sent if item.get("id") == 3)
    assert rewound["refill_prompt"] == "hello"
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("one")
    assert rewound["restore_point"]
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "session/items",
            "params": {"session_id": session.session_id},
        }
    )
    items = next(item["result"] for item in sent if item.get("id") == 4)["items"]
    texts = [str((row.get("params") or {}).get("text") or "") for row in items]
    assert "later" not in texts


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
    assert not hasattr(__import__("appserver.checkpoint_rewind", fromlist=["CheckpointRewindService"]).CheckpointRewindService, "record_message")
