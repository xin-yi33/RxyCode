"""PhaseG-B17 recycle bin."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from appserver.sessions import SessionStore
from appserver.task_store import DesktopTaskStore
from appserver.trash_service import TrashError, TrashService
from appserver.workspace import is_inside
from protocol.schema import export_schema


def test_soft_delete_restore_and_index(tmp_path: Path) -> None:
    store = SessionStore(task_store=DesktopTaskStore(persistent=False))
    trash = TrashService(store)
    record = store.create(tmp_path, title="keep-me")
    trash.index.upsert(record.session_id, record.title)
    assert trash.index.searchable(record.session_id)
    deleted = trash.delete(record.session_id)
    assert deleted["deleted_at"]
    assert deleted["list_category"] == "recent"
    assert store.list() == []
    assert trash.list_deleted()["threads"][0]["session_id"] == record.session_id
    assert not trash.index.searchable(record.session_id)
    live = store.get(record.session_id)
    assert live is not None
    assert live.title == "keep-me"
    restored = trash.restore(record.session_id)
    assert restored["restored_at"]
    assert restored["list_category"] == "recent"
    assert any(item.session_id == record.session_id for item in store.list())
    assert trash.index.searchable(record.session_id)


def test_restore_returns_to_archive_category(tmp_path: Path) -> None:
    store = SessionStore(task_store=DesktopTaskStore(persistent=False))
    trash = TrashService(store)
    record = store.create(tmp_path, title="archived")
    store.archive(record.session_id)
    trash.delete(record.session_id)
    assert store.list() == []
    assert store.list(include_archived=True) == []
    restored = trash.restore(record.session_id)
    assert restored["list_category"] == "archive"
    assert restored["archived_at"]
    assert store.list() == []
    assert any(item.session_id == record.session_id for item in store.list(include_archived=True))


def test_purge_requires_confirm_and_path_safety(tmp_path: Path) -> None:
    store = SessionStore(task_store=DesktopTaskStore(persistent=False))
    trash = TrashService(store)
    record = store.create(tmp_path, title="gone")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    deleted = trash.delete(record.session_id)
    assoc = Path(deleted["associated_dir"])
    extra = tmp_path / "notes" / "thread.md"
    extra.parent.mkdir()
    extra.write_text("gone-too", encoding="utf-8")
    store.remember_associated(record.session_id, deleted["associated_files"] + [str(extra)])
    assert assoc.exists()
    with pytest.raises(TrashError) as missing:
        trash.purge(record.session_id, confirm_purge=False)
    assert missing.value.code == "PURGE_UNCONFIRMED"
    with pytest.raises(TrashError) as truthy:
        trash.purge(record.session_id, confirm_purge="false")  # type: ignore[arg-type]
    assert truthy.value.code == "PURGE_UNCONFIRMED"
    with pytest.raises(TrashError) as outside_err:
        trash.purge(record.session_id, confirm_purge=True, extra_paths=[str(outside)])
    assert outside_err.value.code == "PATH_OUTSIDE_WORKSPACE"
    assert outside.exists()
    assert assoc.exists()
    result = trash.purge(record.session_id, confirm_purge=True, extra_paths=["notes/thread.md"])
    assert result["purged"] is True
    assert store.get(record.session_id) is None
    assert not assoc.exists()
    assert not extra.exists()


def test_purge_keeps_record_if_files_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionStore(task_store=DesktopTaskStore(persistent=False))
    trash = TrashService(store)
    record = store.create(tmp_path, title="partial")
    trash.delete(record.session_id)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("locked")

    monkeypatch.setattr("appserver.trash_service.shutil.rmtree", boom)
    with pytest.raises(TrashError) as err:
        trash.purge(record.session_id, confirm_purge=True)
    assert err.value.code == "PURGE_INCOMPLETE"
    assert store.get(record.session_id) is not None


def test_refuse_symlink_journal_and_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    thread_root = workspace / ".rxy-thread"
    thread_root.mkdir()
    journal = thread_root / ".purge-journal"
    try:
        journal.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    store = SessionStore(task_store=DesktopTaskStore(persistent=False))
    trash = TrashService(store)
    record = store.create(workspace, title="link")
    trash.delete(record.session_id)
    with pytest.raises(TrashError) as err:
        trash.purge(record.session_id, confirm_purge=True)
    assert err.value.code == "PATH_OUTSIDE_WORKSPACE"
    assert store.get(record.session_id) is not None
    assert list(outside.iterdir()) == []
    manifest = Path(trash.associated_dir(workspace, record.session_id) / "associated_files.json")
    if manifest.exists() and not manifest.is_symlink():
        manifest.unlink()
    try:
        manifest.symlink_to(outside / "leaked.json")
    except OSError:
        return
    with pytest.raises(TrashError):
        trash.delete(record.session_id)
    assert not (outside / "leaked.json").exists()


def test_path_containment_case_and_prefix() -> None:
    if os.name == "nt":
        root = Path(r"C:\workspace")
        assert is_inside(root, Path(r"C:\Workspace\a.txt"))
        assert not is_inside(root, Path(r"C:\workspace2\a.txt"))
    else:
        root = Path("/workspace")
        assert is_inside(root, Path("/workspace/a.txt"))
        assert not is_inside(root, Path("/Workspace/a.txt"))
        assert not is_inside(root, Path("/workspace2/a.txt"))


def test_windows_case_and_prefix_sibling(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    sibling = tmp_path / "workspace2"
    workspace.mkdir()
    sibling.mkdir()
    (sibling / "steal.txt").write_text("no", encoding="utf-8")
    extra = workspace / "keep-relative.txt"
    extra.write_text("yes", encoding="utf-8")
    store = SessionStore(task_store=DesktopTaskStore(persistent=False))
    trash = TrashService(store)
    record = store.create(workspace, title="case")
    deleted = trash.delete(record.session_id)
    assoc = Path(deleted["associated_dir"])
    assert is_inside(workspace.resolve(), assoc.resolve())
    assert not is_inside(workspace.resolve(), sibling.resolve())
    with pytest.raises(TrashError) as prefix:
        trash.purge(record.session_id, confirm_purge=True, extra_paths=[str(sibling / "steal.txt")])
    assert prefix.value.code == "PATH_OUTSIDE_WORKSPACE"
    assert (sibling / "steal.txt").exists()
    result = trash.purge(record.session_id, confirm_purge=True, extra_paths=["keep-relative.txt"])
    assert result["purged"] is True
    assert not assoc.exists()
    assert not extra.exists()


def test_schema_has_thread_trash_methods() -> None:
    defs = export_schema()["$defs"]
    assert "ThreadDeleteRequest" in defs
    assert "ThreadPurgeRequest" in defs
    assert "ThreadListDeletedRequest" in defs
    props = defs["ThreadPurgeRequest"]["properties"]
    assert "confirm_purge" in props
    assert defs["ThreadPurgeRequest"]["properties"]["confirm_purge"]["type"] == "boolean"
    assert "ThreadMetadata" in defs
    meta = defs["ThreadMetadata"]["properties"]
    assert "deleted_at" in meta
    assert "restored_at" in meta
    assert "list_category" in meta
    schema_path = Path(__file__).resolve().parents[1] / "protocol" / "schema.json"
    on_disk = json.loads(schema_path.read_text(encoding="utf-8"))
    disk_defs = on_disk["$defs"]
    assert "ThreadMetadata" in disk_defs
    assert "deleted_at" in disk_defs["ThreadMetadata"]["properties"]
    assert "restored_at" in disk_defs["ThreadMetadata"]["properties"]
    assert "ThreadPurgeRequest" in disk_defs
    assert "confirm_purge" in disk_defs["ThreadPurgeRequest"]["properties"]


@pytest.mark.asyncio
async def test_protocol_thread_trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from appserver.server import AppServer

    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="t")
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "thread/delete", "params": {"session_id": record.session_id}}
    )
    assert next(item["result"] for item in sent if item.get("id") == 1)["deleted_at"]
    sent.clear()
    await server._dispatch({"jsonrpc": "2.0", "id": 2, "method": "thread/list_deleted", "params": {}})
    listed = next(item["result"] for item in sent if item.get("id") == 2)
    assert listed["threads"]
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "thread/purge", "params": {"session_id": record.session_id}}
    )
    err = next(item["error"] for item in sent if item.get("id") == 3)
    assert err["data"]["error_code"] == "PURGE_UNCONFIRMED"
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "thread/purge",
            "params": {"session_id": record.session_id, "confirm_purge": "false"},
        }
    )
    err_false = next(item["error"] for item in sent if item.get("id") == 4)
    assert err_false["data"]["error_code"] == "PURGE_UNCONFIRMED"
    sent.clear()
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "thread/purge",
            "params": {"session_id": record.session_id, "confirm_purge": True},
        }
    )
    purged = next(item["result"] for item in sent if item.get("id") == 5)
    assert purged["purged"] is True


@pytest.mark.asyncio
async def test_protocol_thread_restore_to_category(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from appserver.server import AppServer

    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    recent = server._sessions.create(tmp_path, title="recent")
    archived = server._sessions.create(tmp_path, title="archived")
    server._sessions.archive(archived.session_id)
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "thread/delete", "params": {"session_id": recent.session_id}}
    )
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "thread/delete", "params": {"session_id": archived.session_id}}
    )
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "thread/restore", "params": {"session_id": recent.session_id}}
    )
    recent_out = next(item["result"] for item in sent if item.get("id") == 3)
    assert recent_out["list_category"] == "recent"
    assert recent_out["deleted_at"] is None
    assert any(item.session_id == recent.session_id for item in server._sessions.list())
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 4, "method": "thread/restore", "params": {"session_id": archived.session_id}}
    )
    archived_out = next(item["result"] for item in sent if item.get("id") == 4)
    assert archived_out["list_category"] == "archive"
    assert archived_out["archived_at"]
    assert server._sessions.list() == [item for item in server._sessions.list() if item.session_id != archived.session_id]
    assert any(item.session_id == archived.session_id for item in server._sessions.list(include_archived=True))


@pytest.mark.asyncio
async def test_session_purge_still_works_without_confirm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from appserver.server import AppServer

    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="legacy")
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "session/trash", "params": {"session_id": record.session_id}}
    )
    sent.clear()
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 2, "method": "session/purge", "params": {"session_id": record.session_id}}
    )
    result = next(item["result"] for item in sent if item.get("id") == 2)
    assert result["ok"] is True
    assert server._sessions.get(record.session_id) is None
