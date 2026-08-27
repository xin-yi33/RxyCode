"""PhaseG-B4 project/workspace path boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.project_routes import handle_project_rpc
from appserver.project_store import ProjectStore
from appserver.server import AppServer
from appserver.workspace import PathBoundaryError, assert_inside_workspace, canonicalize


def test_display_name_separated_from_real_path(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects.json")
    project = store.add(str(tmp_path), display_name="Nice Name")
    assert project["display_name"] == "Nice Name"
    assert project["path"] == str(canonicalize(tmp_path))
    assert project["path"] != "Nice Name"


def test_remove_does_not_delete_files(tmp_path: Path) -> None:
    marker = tmp_path / "keep.txt"
    marker.write_text("safe", encoding="utf-8")
    store = ProjectStore(tmp_path / "projects.json")
    project = store.add(str(tmp_path), display_name="x")
    store.remove(project["project_id"])
    assert marker.is_file()
    assert store.list() == []


def test_two_projects_do_not_share_cwd(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    store = ProjectStore(tmp_path / "projects.json")
    pa = store.add(str(a), display_name="A")
    pb = store.add(str(b), display_name="B")
    assert pa["path"] != pb["path"]
    import os

    before = os.getcwd()
    store.set_active(pa["project_id"])
    store.set_active(pb["project_id"])
    assert os.getcwd() == before


def test_outside_and_symlink_rejected(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    outside = tmp_path / "outside.txt"
    ws.mkdir()
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(PathBoundaryError) as err:
        assert_inside_workspace(ws, outside)
    assert err.value.code == "PATH_OUTSIDE_WORKSPACE"
    link = ws / "escape"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    with pytest.raises(PathBoundaryError) as err:
        assert_inside_workspace(ws, link)
    assert err.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_missing_dir_rejected(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects.json")
    with pytest.raises(PathBoundaryError) as err:
        store.add(str(tmp_path / "missing"))
    assert err.value.code == "PATH_NOT_FOUND"


def test_workspace_status_non_git(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "p.json")
    store.add(str(tmp_path))
    result = handle_project_rpc(
        store,
        "workspace/status",
        {"workspace_root": str(tmp_path)},
    )
    assert result["is_git"] is False
    assert result["error_code"] == "NOT_A_GIT_REPO"


@pytest.mark.asyncio
async def test_new_thread_must_bind_existing_workspace(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    await server._handle_session_new({"workspace_root": str(tmp_path / "nope")}, 1)
    err = sent[0]["error"]
    assert err["data"]["error_code"] == "PATH_NOT_FOUND"

    sent.clear()
    await server._handle_session_new({"workspace_root": str(tmp_path)}, 2)
    result = next(item["result"] for item in sent if "result" in item)
    assert result["workspace_root"] == str(canonicalize(tmp_path))


@pytest.mark.asyncio
async def test_workspace_change_event(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    server._projects = ProjectStore(tmp_path / "projects.json")
    await server._handle_project_method(
        "project/add", {"path": str(tmp_path), "display_name": "P"}, 3
    )
    assert any(item.get("method") == "event/workspace_changed" for item in sent)


def test_unregistered_workspace_status_rejected(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "p.json")
    with pytest.raises(PathBoundaryError) as err:
        handle_project_rpc(store, "workspace/status", {"workspace_root": str(tmp_path)})
    assert err.value.code == "PATH_OUTSIDE_WORKSPACE"


def test_git_branch_when_head_exists(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    store = ProjectStore(tmp_path / "p.json")
    store.add(str(tmp_path))
    result = handle_project_rpc(store, "workspace/status", {"workspace_root": str(tmp_path)})
    assert result["is_git"] is True
    assert result["branch"] == "main"
