"""PhaseG-B9 worktree lifecycle."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from appserver.permission import PermissionStore
from appserver.server import AppServer
from appserver.worktree_service import WorktreeError, WorktreeService
from appserver.workspace import canonicalize as canonicalize_path


def _perms() -> PermissionStore:
    store = PermissionStore(persistent=False)
    store.set_profile("workspace_write")
    return store


def _git(cwd: Path, *args: str) -> None:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "b9@example.com")
    _git(tmp_path, "config", "user.name", "B9")
    (tmp_path / "README.md").write_text("hi\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "base")
    return tmp_path


def test_create_failure_leaves_no_half_tree(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    dest = tmp_path / "already"
    dest.mkdir()
    (dest / "x").write_text("n", encoding="utf-8")
    service = WorktreeService()
    with pytest.raises(WorktreeError) as exc:
        service.create(root, dest=str(dest), session_id="s", permission_store=_perms())
    assert exc.value.code == "WORKTREE_EXISTS"
    assert dest.is_dir()
    assert list(dest.iterdir())


def test_prune_requires_confirm(tmp_path: Path) -> None:
    service = WorktreeService()
    with pytest.raises(WorktreeError) as exc:
        service.prune(tmp_path, confirm=False)
    assert exc.value.code == "CONFIRM_REQUIRED"


def test_close_refuses_uncommitted(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    dest = tmp_path / "wt1"
    service = WorktreeService()
    created = service.create(root, dest=str(dest), session_id="s", permission_store=_perms())
    (dest / "dirty.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorktreeError) as exc:
        service.close(
            root,
            created["worktree_id"],
            force=False,
            confirm=True,
            session_id="s",
            permission_store=_perms(),
        )
    assert exc.value.code == "UNCOMMITTED_CHANGES"
    assert dest.exists()


def test_handoff_can_rollback(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    dest = tmp_path / "wt-h"
    service = WorktreeService()
    created = service.create(root, dest=str(dest), session_id="s1", permission_store=_perms())
    rec = service.handoff(
        source_session="s1",
        target_session="s2",
        target_path=created["path"],
        workspace=root,
        permission_store=_perms(),
        confirm=True,
    )
    assert rec["target_session"] == "s2"
    assert Path(service.session_root("s2") or "") == Path(created["path"]).resolve()
    assert created["worktree_id"]
    owned = [item for item in service._records.values() if item["worktree_id"] == created["worktree_id"]]
    assert owned and owned[0]["session_id"] == "s2"
    listed_s1 = service.list(root, session_id="s1")
    listed_s2 = service.list(root, session_id="s2")
    assert all(canonicalize_path(row["path"]) != Path(created["path"]).resolve() for row in listed_s1)
    assert any(canonicalize_path(row["path"]) == Path(created["path"]).resolve() for row in listed_s2)
    rolled = service.rollback_handoff(
        rec["handoff_id"],
        session_id="s1",
        permission_store=_perms(),
        confirm=True,
        workspace=root,
    )
    assert rolled["rolled_back"] is True
    assert Path(service.session_root("s2") or "missing") != Path(created["path"]).resolve()
    assert service._records[created["worktree_id"]]["session_id"] == "s1"


@pytest.mark.asyncio
async def test_create_requires_permission(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    root = _repo(tmp_path)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(root, title="p")
    await server._handle_worktree_create(
        {"session_id": session.session_id, "dest": str(tmp_path / "wt2")},
        1,
    )
    err = next(item["error"] for item in sent if "error" in item)
    assert err["data"]["error_code"] == "PERMISSION_DENIED"


def test_rollback_rejects_foreign_session(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    dest = tmp_path / "wt-r"
    service = WorktreeService()
    created = service.create(root, dest=str(dest), session_id="s1", permission_store=_perms())
    rec = service.handoff(
        source_session="s1",
        target_session="s2",
        target_path=created["path"],
        workspace=root,
        permission_store=_perms(),
        confirm=True,
    )
    with pytest.raises(WorktreeError) as exc:
        service.rollback_handoff(
            rec["handoff_id"],
            session_id="s9",
            permission_store=_perms(),
            workspace=root,
        )
    assert exc.value.code == "SESSION_MISMATCH"
    again = service.rollback_handoff(
        rec["handoff_id"],
        session_id="s1",
        permission_store=_perms(),
        workspace=root,
    )
    twice = service.rollback_handoff(
        rec["handoff_id"],
        session_id="s1",
        permission_store=_perms(),
        workspace=root,
    )
    assert again["rolled_back"] is True
    assert twice["rolled_back"] is True
