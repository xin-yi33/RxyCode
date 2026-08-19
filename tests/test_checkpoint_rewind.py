"""GX4-B: named snapshots + checkpoint/rewind orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.checkpoint_rewind import CheckpointRewindError, CheckpointRewindService
from appserver.review import ReviewService
from appserver.server import AppServer
from protocol.requests import CheckpointRewindRequest, CheckpointSnapshotCreateRequest


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    return tmp_path


def test_b8_create_restore_still_exist() -> None:
    assert CheckpointSnapshotCreateRequest.model_fields["method"].default == "checkpoint/snapshot/create"
    assert CheckpointRewindRequest.model_fields["method"].default == "checkpoint/rewind"
    snap = CheckpointSnapshotCreateRequest(name="before", session_id="s")
    assert snap.name == "before"
    rewind = CheckpointRewindRequest(checkpoint_id="cp_x", confirm=True, session_id="s")
    assert rewind.confirm is True


def test_named_snapshot_and_rewind_orchestration(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    reviews = ReviewService()
    server = AppServer(stub=True)
    session = server._sessions.create(root, title="gx4")
    svc = CheckpointRewindService(reviews, server._sessions)
    svc.record_message(session.session_id, role="user", text="first prompt")
    named = svc.snapshot_create(
        session_id=session.session_id,
        name="before-edit",
        user_prompt="first prompt",
    )
    assert named["name"] == "before-edit"
    assert named["seq"] == 1
    assert named["reason"] == "named_snapshot"
    (root / "a.txt").write_text("two\n", encoding="utf-8")
    svc.record_message(session.session_id, role="user", text="second prompt")
    later = svc.snapshot_create(session_id=session.session_id, name="after-edit")
    assert later["seq"] == 2
    with pytest.raises(CheckpointRewindError, match="confirm"):
        svc.rewind(checkpoint_id=named["checkpoint_id"], confirm=False, session_id=session.session_id)
    result = svc.rewind(
        checkpoint_id=named["checkpoint_id"],
        confirm=True,
        session_id=session.session_id,
    )
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("one")
    assert result["refill_prompt"] == "first prompt"
    assert result["truncated_messages"] >= 1
    assert result["restore_point"].startswith("cp_")
    listed = reviews.list_checkpoints(session.session_id)
    ids = {item["checkpoint_id"] for item in listed}
    assert named["checkpoint_id"] in ids
    assert later["checkpoint_id"] in ids
    assert result["restore_point"] in ids
    forward = svc.rewind(checkpoint_id=later["checkpoint_id"], confirm=True, session_id=session.session_id)
    assert (root / "a.txt").read_text(encoding="utf-8").startswith("two")
    assert forward["restore_point"].startswith("cp_")


@pytest.mark.asyncio
async def test_appserver_snapshot_rewind_rpc(tmp_path: Path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._permissions.set_profile("workspace_write")
    session = server._sessions.create(root, title="gx4")
    server._checkpoint_rewind.record_message(session.session_id, role="user", text="hello")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "checkpoint/snapshot/create",
            "params": {
                "session_id": session.session_id,
                "name": "snap-1",
                "user_prompt": "hello",
            },
        }
    )
    created = next(item["result"] for item in sent if item.get("id") == 1)
    assert created["name"] == "snap-1"
    (root / "a.txt").write_text("changed\n", encoding="utf-8")
    server._checkpoint_rewind.record_message(session.session_id, role="assistant", text="ok")
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


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
