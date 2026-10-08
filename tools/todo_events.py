"""F5-2：把 tasks.json 投影成 V17 快照，并经现有通知出口发 event/todo_updated。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable

from RxyCode.RxyCode1_1_0.protocol.todo import TodoItem, TodoSnapshot

_SINK: Callable[[dict], None] | None = None


def bind_todo_sink(sink: Callable[[dict], None] | None) -> None:
    global _SINK
    _SINK = sink


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_snapshot(session_id: str) -> TodoSnapshot:
    return TodoSnapshot(
        session_id=session_id,
        root_session_id=session_id,
        run_id=None,
        list_id="default",
        revision=0,
        scope="turn",
        source="model",
        items=[],
        updated_at=_now(),
    )


def snapshot_from_document(session_id: str, document: dict) -> TodoSnapshot:
    from RxyCode.RxyCode1_1_0.tools.todo_write import _canonical_status, _stored_content

    items: list[TodoItem] = []
    for key, row in (document.get("tasks") or {}).items():
        if not isinstance(row, dict):
            continue
        status = _canonical_status(row.get("status")) or "pending"
        items.append(
            TodoItem(
                id=str(row.get("id") or key),
                content=_stored_content(row),
                status=status,  # type: ignore[arg-type]
                priority=row.get("priority"),
            )
        )
    return TodoSnapshot(
        session_id=session_id,
        root_session_id=session_id,
        run_id=None,
        list_id="default",
        revision=int(document.get("revision") or 0),
        scope="turn",
        source="model",
        items=items,
        updated_at=_now(),
    )


def read_todo_snapshot(session_id: str) -> TodoSnapshot:
    from RxyCode.RxyCode1_1_0.config.settings import get_data_dir
    from RxyCode.RxyCode1_1_0.memory.long_term import validate_session_id

    path = get_data_dir() / "tasks" / validate_session_id(session_id) / "tasks.json"
    if not path.exists():
        return _empty_snapshot(session_id)
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return _empty_snapshot(session_id)
    return snapshot_from_document(session_id, document)


def make_todo_event(snapshot: TodoSnapshot) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "seq": int(snapshot.revision),
        "timestamp": snapshot.updated_at,
        "snapshot": snapshot.model_dump(mode="json"),
    }


def emit_snapshot(snapshot: TodoSnapshot) -> dict:
    event = make_todo_event(snapshot)
    message = {"jsonrpc": "2.0", "method": "event/todo_updated", "params": event}
    if _SINK is not None:
        _SINK(message)
    return event


def emit_saved_document(session_id: str, document: dict) -> dict:
    return emit_snapshot(snapshot_from_document(session_id, document))


def project_todo(session_id: str) -> dict:
    """投影入口。没有台账时也发出 items=[]、revision 0 的事件。"""
    return emit_snapshot(read_todo_snapshot(session_id))
