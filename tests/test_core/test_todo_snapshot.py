"""layer=unit F5-2 TodoSnapshot contract and projection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from RxyCode.RxyCode1_1_0.config import settings
from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.protocol.todo import TodoItem, TodoSnapshot


REPO = Path(__file__).resolve().parents[2]
SNAPSHOT_KEYS = {
    "session_id",
    "root_session_id",
    "run_id",
    "list_id",
    "revision",
    "scope",
    "source",
    "explanation",
    "items",
    "updated_at",
}
EVENT_KEYS = {"event_id", "seq", "timestamp", "snapshot"}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    return tmp_path


def test_u_f5_2_01_snapshot_field_contract():
    """layer=unit U-F5-2-01 快照字段契约。"""
    assert set(TodoSnapshot.model_fields) == SNAPSHOT_KEYS
    assert set(TodoItem.model_fields) >= {"id", "content", "status"}
    assert not (REPO / "core" / "todo_snapshot.py").exists()
    sample = TodoSnapshot(
        session_id="sess",
        root_session_id="sess",
        list_id="default",
        revision=1,
        scope="turn",
        source="model",
        items=[TodoItem(id="t1", content="搭骨架", status="pending")],
        updated_at="2026-10-08T00:00:00+00:00",
    )
    assert sample.scope == "turn"
    assert sample.source == "model"
    assert sample.list_id == "default"
    with pytest.raises(ValidationError):
        TodoSnapshot.model_validate({**sample.model_dump(), "extra": 1})
    with pytest.raises(ValidationError):
        TodoItem(id="t1", content="x", status="nope")
    with pytest.raises(ValidationError):
        TodoSnapshot.model_validate({"session_id": "sess"})
    from RxyCode.RxyCode1_1_0.protocol.notifications import TodoUpdatedNotification

    with pytest.raises(ValidationError):
        TodoUpdatedNotification(
            event_id="e",
            seq=1,
            timestamp="t",
            snapshot={"session_id": "sess"},
        )


def test_u_f5_2_02_revision_comes_from_the_store(data_dir):
    """layer=unit U-F5-2-02 revision 来自 store，会话之间互不影响。"""
    from RxyCode.RxyCode1_1_0.tools.todo_events import read_todo_snapshot
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    token = bind_session("sess_a")
    try:
        first = todo_write([{"id": "a", "content": "一", "status": "pending"}], merge=True)
        second = todo_write([{"id": "a", "status": "completed"}], merge=True)
    finally:
        reset_session_binding(token)
    stored = json.loads((data_dir / "tasks" / "sess_a" / "tasks.json").read_text(encoding="utf-8"))
    assert first.snapshot.revision == 1
    assert second.snapshot.revision == stored["revision"] == 2
    assert read_todo_snapshot("sess_a").revision == stored["revision"]

    other = bind_session("sess_b")
    try:
        isolated = todo_write([{"id": "b", "content": "二", "status": "pending"}], merge=True)
    finally:
        reset_session_binding(other)
    assert isolated.snapshot.revision == 1
    assert read_todo_snapshot("sess_a").revision == 2


def test_u_f5_2_03_empty_projection_emits_and_reject_does_not(data_dir):
    """layer=unit U-F5-2-03 空清单必须发事件，拒绝写入不发。"""
    from RxyCode.RxyCode1_1_0.tools.todo_events import bind_todo_sink, project_todo
    from RxyCode.RxyCode1_1_0.tools.todo_write import todo_write

    seen: list[dict] = []
    bind_todo_sink(seen.append)
    event = project_todo("sess_empty")
    assert set(event) == EVENT_KEYS
    assert event["snapshot"]["items"] == []
    assert event["snapshot"]["revision"] == 0
    assert len(seen) == 1
    assert "items" not in seen[0] or seen[0].get("method") == "event/todo_updated"

    token = bind_session("sess_empty")
    try:
        todo_write([{"id": "t1", "content": "有", "status": "in_progress"}], merge=True)
        before = len(seen)
        rejected = todo_write(
            [{"id": "t2", "content": "另一件", "status": "in_progress"}],
            merge=True,
        )
    finally:
        reset_session_binding(token)
    assert str(rejected).startswith("[todo_write rejected]")
    assert len(seen) == before
