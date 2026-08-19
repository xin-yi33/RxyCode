"""PhaseG-B5 Thread/Turn/Item/Child isolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from appserver.project_store import ProjectStore
from appserver.server import AppServer
from appserver.sessions import SessionStore
from appserver.task_store import DesktopTaskStore
from protocol.handshake import CapabilitySnapshot
from protocol.requests import TurnInterruptRequest, TurnStartRequest


@pytest.mark.asyncio
async def test_fork_does_not_mutate_parent(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    parent = server._sessions.create(tmp_path, title="parent")
    server._sessions.update_status(parent.session_id, "succeeded")
    server._task_store.append_event(
        parent.session_id,
        {"method": "event/done", "params": {"session_id": parent.session_id, "status": "succeeded"}},
    )
    parent_before = server._sessions.get(parent.session_id)
    assert parent_before is not None
    parent_events_before, _, _ = server._task_store.events(parent.session_id, 0)
    await server._handle_session_fork({"session_id": parent.session_id}, 1)
    result = next(item["result"] for item in sent if "result" in item)
    assert result["forked_from"] == parent.session_id
    assert result["session_id"] != parent.session_id
    assert result["parent_session_id"] is None
    assert result["root_session_id"] == result["session_id"]
    parent_after = server._sessions.get(parent.session_id)
    assert parent_after is not None
    assert parent_after.title == "parent"
    assert parent_after.status == parent_before.status
    assert parent_after.updated_at == parent_before.updated_at
    parent_events_after, _, _ = server._task_store.events(parent.session_id, 0)
    assert len(parent_events_after) == len(parent_events_before)
    child_events, _, _ = server._task_store.events(result["session_id"], 0)
    assert len(child_events) == len(parent_events_before)
    parent_ids = {item.get("event_id") for item in parent_events_before}
    child_ids = {item.get("event_id") for item in child_events}
    assert parent_ids.isdisjoint(child_ids)


@pytest.mark.asyncio
async def test_archive_hidden_and_restorable(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="arc")
    await server._handle_session_archive({"session_id": record.session_id}, 2)
    listed = server._sessions.list()
    assert all(item.session_id != record.session_id for item in listed)
    await server._handle_session_unarchive({"session_id": record.session_id}, 3)
    assert any(item.session_id == record.session_id for item in server._sessions.list())


@pytest.mark.asyncio
async def test_retry_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="t")
    server._sessions.remember_turn(
        record.session_id,
        "req-1",
        {"status": "succeeded", "text": "once", "run_id": "r1"},
    )
    before, _, _ = server._task_store.events(record.session_id, 0)
    await server._handle_turn_retry(
        {"session_id": record.session_id, "request_id": "req-1"},
        4,
    )
    await server._handle_turn_retry(
        {"session_id": record.session_id, "request_id": "req-1"},
        5,
    )
    results = [item["result"] for item in sent if "result" in item]
    assert results[0]["text"] == "once"
    assert results[1]["text"] == "once"
    after, _, _ = server._task_store.events(record.session_id, 0)
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_child_items_do_not_mix_into_parent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    parent = server._sessions.create(tmp_path, title="parent")
    child = server._sessions.ensure_child(
        session_id="child-1",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
        agent_id="explore",
        trigger="task",
        budget={"max_steps": 4},
        permission_snapshot={"mode": "read_only"},
        lease_id="lease-1",
    )
    server._persist_notification(
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": child.session_id,
                "parent_session_id": parent.session_id,
                "root_session_id": parent.session_id,
                "tool": "bash",
            },
        }
    )
    server._persist_notification(
        {
            "method": "child_session/approval_required",
            "params": {
                "session_id": child.session_id,
                "parent_session_id": parent.session_id,
                "root_session_id": parent.session_id,
                "approval_id": "appr-1",
            },
        }
    )
    parent_items, _, _ = server._task_store.events(parent.session_id, 0)
    child_items, _, _ = server._task_store.events(child.session_id, 0)
    assert parent_items == []
    assert any(item.get("method") == "event/tool_begin" for item in child_items)
    assert any(item.get("method") == "child_session/approval_required" for item in child_items)
    assert child.budget["max_steps"] == 4
    assert child.permission_snapshot["mode"] == "read_only"
    tree = server._sessions.tree(parent.session_id)
    assert {item.session_id for item in tree} == {parent.session_id, child.session_id}


@pytest.mark.asyncio
async def test_steer_without_running_turn_denied(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="s")
    await server._handle_turn_steer({"session_id": record.session_id, "text": "go"}, 6)
    err = sent[0]["error"]
    assert err["data"]["error_code"] == "TURN_NOT_RUNNING"


@pytest.mark.asyncio
async def test_child_fail_cancel_orphan_are_auditable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    parent = server._sessions.create(tmp_path, title="p")
    failed = server._sessions.ensure_child(
        session_id="c-fail",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
    )
    cancelled = server._sessions.ensure_child(
        session_id="c-cancel",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
    )
    running = server._sessions.ensure_child(
        session_id="c-run",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
    )
    server._sessions.update_status(running.session_id, "running")
    server._sessions.record_child_terminal(failed.session_id, "failed", reason="budget")
    server._sessions.record_child_terminal(cancelled.session_id, "cancelled", reason="user")
    await server._handle_session_trash({"session_id": parent.session_id}, 7)
    fail_events, _, _ = server._task_store.events("c-fail", 0)
    cancel_events, _, _ = server._task_store.events("c-cancel", 0)
    orphan_events, _, _ = server._task_store.events("c-run", 0)
    parent_events, _, _ = server._task_store.events(parent.session_id, 0)
    assert any(item.get("method") == "child_session/failed" for item in fail_events)
    assert any(item.get("method") == "child_session/cancelled" for item in cancel_events)
    assert any(item.get("method") == "child_session/orphaned" for item in orphan_events)
    assert all(
        item.get("method")
        not in {"child_session/failed", "child_session/cancelled", "child_session/orphaned"}
        for item in parent_events
    )
    orphan = server._sessions.get("c-run")
    assert orphan is not None
    assert orphan.status == "orphaned"
    assert orphan.orphan_reason == "parent_trashed"


def test_list_filters_and_item_pagination(tmp_path: Path) -> None:
    store = DesktopTaskStore(tmp_path / "tasks.json", persistent=True)
    sessions = SessionStore(task_store=store)
    a = sessions.create(tmp_path / "a", title="a")
    b = sessions.create(tmp_path / "b", title="b")
    sessions.update_status(a.session_id, "succeeded")
    child = sessions.ensure_child(
        session_id="kid",
        parent_session_id=a.session_id,
        workspace_root=tmp_path / "a",
        root_session_id=a.session_id,
    )
    for index in range(3):
        store.append_event(
            a.session_id,
            {"method": "event/step", "params": {"session_id": a.session_id, "n": index}},
        )
    by_ws = sessions.list(workspace_root=str(tmp_path / "a"))
    assert {item.session_id for item in by_ws} == {a.session_id, child.session_id}
    assert [item.session_id for item in sessions.list(status="succeeded")] == [a.session_id]
    kids = sessions.list(parent_session_id=a.session_id)
    assert [item.session_id for item in kids] == ["kid"]
    page, latest, gap = store.events(a.session_id, 0, limit=2)
    assert len(page) == 2
    assert latest == 2
    assert gap is False
    rest, rest_cursor, _ = store.events(a.session_id, 2, limit=2)
    assert len(rest) == 1
    assert rest_cursor == 3
    assert b.session_id not in {item.session_id for item in by_ws}


def test_restart_reloads_thread_tree(tmp_path: Path) -> None:
    path = tmp_path / "desktop" / "tasks.json"
    store = DesktopTaskStore(path, persistent=True)
    first = SessionStore(task_store=store)
    parent = first.create(tmp_path, title="keep")
    first.ensure_child(
        session_id="kid-persist",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
        agent_id="explore",
    )
    store.append_event(
        "kid-persist",
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": "kid-persist",
                "parent_session_id": parent.session_id,
                "root_session_id": parent.session_id,
            },
        },
    )
    second = SessionStore(task_store=DesktopTaskStore(path, persistent=True))
    reloaded = second.get("kid-persist")
    assert reloaded is not None
    assert reloaded.parent_session_id == parent.session_id
    assert reloaded.root_session_id == parent.session_id
    events, cursor, gap = second._task_store.events("kid-persist", 0) if second._task_store else ([], 0, False)
    assert events
    assert cursor >= 1
    assert gap is False
    parent_events, _, _ = second._task_store.events(parent.session_id, 0) if second._task_store else ([], 0, False)
    assert parent_events == []


def test_two_children_keep_separate_budget_and_lease(tmp_path: Path) -> None:
    store = DesktopTaskStore(tmp_path / "tasks.json", persistent=True)
    sessions = SessionStore(task_store=store)
    parent = sessions.create(tmp_path, title="p")
    a = sessions.ensure_child(
        session_id="c-a",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
        budget={"max_steps": 2},
        permission_snapshot={"mode": "read_only"},
        lease_id="lease-a",
    )
    b = sessions.ensure_child(
        session_id="c-b",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
        budget={"max_steps": 9},
        permission_snapshot={"mode": "leased_write"},
        lease_id="lease-b",
    )
    assert a.budget != b.budget
    assert a.permission_snapshot != b.permission_snapshot
    assert a.lease_id != b.lease_id
    assert parent.budget == {}
    assert parent.lease_id is None


@pytest.mark.asyncio
async def test_turn_start_and_interrupt_methods(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="t")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "turn/interrupt",
            "params": {"session_id": record.session_id},
        }
    )
    assert any("result" in item for item in sent)
    assert TurnStartRequest(session_id=record.session_id, text="hi").method == "turn/start"
    assert TurnInterruptRequest(session_id=record.session_id).method == "turn/interrupt"


@pytest.mark.asyncio
async def test_retry_inflight_same_request_id_does_not_reenter(
    tmp_path: Path, monkeypatch
) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="t")
    server._inflight_turns[record.session_id] = "req-live"
    await server._handle_turn_retry(
        {"session_id": record.session_id, "request_id": "req-live", "text": "again"},
        21,
    )
    result = next(item["result"] for item in sent if "result" in item)
    assert result["idempotent"] is True
    assert result["status"] == "running"


def test_project_and_time_filters(tmp_path: Path) -> None:
    ws = tmp_path / "proj"
    ws.mkdir()
    projects = ProjectStore(tmp_path / "projects.json", persistent=True)
    project = projects.add(str(ws), display_name="P")
    store = DesktopTaskStore(tmp_path / "tasks.json", persistent=True)
    sessions = SessionStore(task_store=store)
    inside = sessions.create(ws, title="in")
    sessions.create(tmp_path / "other", title="out")
    listed = sessions.list(workspace_root=project["path"])
    assert [item.session_id for item in listed] == [inside.session_id]
    bounded = sessions.list(
        updated_after="1970-01-01T00:00:00Z",
        updated_before="2999-01-01T00:00:00Z",
        created_after="1970-01-01T00:00:00Z",
        created_before="2999-01-01T00:00:00Z",
    )
    assert inside.session_id in {item.session_id for item in bounded}


def test_persist_child_copies_budget_and_corrects_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    parent = server._sessions.create(tmp_path, title="p")
    server._persist_notification(
        {
            "method": "child_session/created",
            "params": {
                "session_id": "c-ctx",
                "parent_session_id": parent.session_id,
                "root_session_id": "wrong-root",
                "agent_id": "explore",
                "budget": {"max_steps": 5},
                "permission_snapshot": {"mode": "read_only"},
                "lease_id": "lease-x",
            },
        }
    )
    child = server._sessions.get("c-ctx")
    assert child is not None
    assert child.root_session_id == parent.session_id
    assert child.budget == {"max_steps": 5}
    assert child.permission_snapshot == {"mode": "read_only"}
    assert child.lease_id == "lease-x"


def test_unarchive_clears_persisted_archived_at(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    store = DesktopTaskStore(path, persistent=True)
    first = SessionStore(task_store=store)
    record = first.create(tmp_path, title="arc")
    first.archive(record.session_id)
    first.unarchive(record.session_id)
    second = SessionStore(task_store=DesktopTaskStore(path, persistent=True))
    reloaded = second.get(record.session_id)
    assert reloaded is not None
    assert reloaded.archived_at is None
    assert any(item.session_id == record.session_id for item in second.list())


@pytest.mark.asyncio
async def test_retry_older_request_id_is_still_idempotent(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    record = server._sessions.create(tmp_path, title="t")
    server._sessions.remember_turn(record.session_id, "A", {"status": "succeeded", "text": "a"})
    server._sessions.remember_turn(record.session_id, "B", {"status": "succeeded", "text": "b"})
    await server._handle_turn_retry({"session_id": record.session_id, "request_id": "A"}, 30)
    result = next(item["result"] for item in sent if "result" in item)
    assert result["text"] == "a"


def test_ensure_child_repairs_existing_root_and_budget(tmp_path: Path) -> None:
    sessions = SessionStore()
    parent = sessions.create(tmp_path, title="p")
    child = sessions.ensure_child(
        session_id="c1",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id="wrong",
    )
    assert child.root_session_id == parent.session_id
    again = sessions.ensure_child(
        session_id="c1",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id="still-wrong",
        budget={"max_steps": 8},
        lease_id="lease-2",
    )
    assert again.root_session_id == parent.session_id
    assert again.budget == {"max_steps": 8}
    assert again.lease_id == "lease-2"


def test_worker_consumes_steer_queue() -> None:
    source = Path(__file__).resolve().parents[2] / "appserver" / "agent_worker.py"
    text = source.read_text(encoding="utf-8")
    assert "while self._steer_queue:" in text
    assert "self._steer_queue.pop(0)" in text
    assert "session.prompt(self._agent, extra" in text


def test_thread_fork_capability_is_honest() -> None:
    assert CapabilitySnapshot().thread_fork is True


def test_h5_fixtures_exist() -> None:
    root = Path(__file__).resolve().parent / "fixtures"
    required = (
        "h5-success.json",
        "h5-denied.json",
        "h5-timeout.json",
        "h5-reconnect.json",
        "h5-child-tree.json",
        "h5-cancel.json",
        "h5-crash.json",
        "h5-replay.json",
    )
    for name in required:
        path = root / name
        assert path.is_file(), name
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["card"] == "PhaseG-B5"


async def _noop(_message: dict) -> None:
    return None
