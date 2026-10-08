"""layer=module F5-2 todo events and todo/get on the appserver channel."""
from __future__ import annotations

import json

import pytest

from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.config import settings
from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    return tmp_path


def test_mo_f5_2_01_write_emits_one_event_on_the_job_status_channel(data_dir):
    """layer=module MO-F5-2-01 写后恰一发，通道同 event/job_status。"""
    server = AppServer(stub=True)
    notes: list[dict] = []
    server._schedule_notification = lambda message: notes.append(message)
    token = bind_session("sess_evt")
    try:
        todo_write([{"id": "t1", "content": "搭骨架", "status": "pending"}], merge=True)
        from RxyCode.RxyCode1_1_0.tools.task_tool import manage_tasks

        manage_tasks("create", summary="旧任务")
    finally:
        reset_session_binding(token)
    todo_events = [note for note in notes if note.get("method") == "event/todo_updated"]
    assert len(todo_events) == 2
    stored = json.loads((data_dir / "tasks" / "sess_evt" / "tasks.json").read_text(encoding="utf-8"))
    assert [note["params"]["snapshot"]["revision"] for note in todo_events] == [1, stored["revision"]]
    for note in todo_events:
        assert set(note["params"]) == {"event_id", "seq", "timestamp", "snapshot"}
    server._emit_notification(
        {"jsonrpc": "2.0", "method": "event/job_status", "params": {"session_id": "sess_evt", "job_id": "j", "state": "running"}}
    )
    assert any(note.get("method") == "event/job_status" for note in notes)
    assert any(note.get("method") == "event/todo_updated" for note in notes)
    stored_events, _, _ = server._task_store.events("sess_evt", 0)
    persisted = [item for item in stored_events if item["method"] == "event/todo_updated"]
    assert len(persisted) == 2
    assert set(persisted[0]["params"]) == {"event_id", "seq", "timestamp", "snapshot"}


def test_worker_prompt_sink_forwards_todo_write(data_dir):
    """Worker 的 prompt 出口把 todo_write 收成协议通知，而不是丢掉。"""
    import inspect

    from RxyCode.RxyCode1_1_0.appserver.agent_worker import AgentWorker, bind_worker_todo_sink
    from RxyCode.RxyCode1_1_0.appserver.emitter import model_to_notification
    from RxyCode.RxyCode1_1_0.tools.todo_events import bind_todo_sink

    source = inspect.getsource(AgentWorker._handle_prompt)
    assert "bind_worker_todo_sink" in source
    sent: list[dict] = []

    def emit(model) -> None:
        sent.append(model_to_notification(model))

    bind_worker_todo_sink(emit)
    try:
        token = bind_session("sess_worker")
        try:
            todo_write([{"id": "t1", "content": "worker", "status": "pending"}], merge=True)
        finally:
            reset_session_binding(token)
    finally:
        bind_todo_sink(None)
    assert sent[0]["method"] == "event/todo_updated"
    assert sent[0]["params"]["snapshot"]["session_id"] == "sess_worker"


@pytest.mark.asyncio
async def test_mo_f5_2_02_todo_get_three_states(data_dir, monkeypatch):
    """layer=module MO-F5-2-02 todo/get 三态，不经过模型。"""
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    monkeypatch.setattr("RxyCode.RxyCode1_1_0.appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "todo/get", "params": {"session_id": "sess_get"}}
    )
    empty = next(item["result"] for item in sent if item.get("id") == 1)
    assert empty["items"] == []
    assert empty["revision"] == 0

    token = bind_session("sess_get")
    try:
        written = todo_write([{"id": "t1", "content": "搭骨架", "status": "in_progress"}], merge=True)
        sent.clear()
        await server._dispatch(
            {"jsonrpc": "2.0", "id": 2, "method": "todo/get", "params": {"session_id": "sess_get"}}
        )
        current = next(item["result"] for item in sent if item.get("id") == 2)
        assert current["revision"] == written.snapshot.revision
        assert current["items"][0]["content"] == "搭骨架"
        sent.clear()
        todo_write([{"id": "t2", "content": "另一件", "status": "in_progress"}], merge=True)
    finally:
        reset_session_binding(token)
    await server._dispatch(
        {"jsonrpc": "2.0", "id": 3, "method": "todo/get", "params": {"session_id": "sess_get"}}
    )
    after_reject = next(item["result"] for item in sent if item.get("id") == 3)
    assert after_reject["revision"] == current["revision"]
    assert [item["id"] for item in after_reject["items"]] == ["t1"]
