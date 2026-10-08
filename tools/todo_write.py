"""todo_write：模型自维护任务台账（F5-1）。

升级 tools/task_tool.py 的持久 store，不建第四套。状态枚举以 UPDATE-02 V17 为
权威；旧 task/task_manage 与 todo_write 双向读写同一 store。校验（至多一个
in_progress、content 不丢）是 harness 真值：拒绝时不落盘。
"""
from __future__ import annotations

import time
from pathlib import Path
from datetime import datetime, timezone

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from RxyCode.RxyCode1_1_0.log.logger import get_current_run_id
from RxyCode.RxyCode1_1_0.protocol.todo import TodoItem, TodoSnapshot

from RxyCode.RxyCode1_1_0.core.session_runtime import current_session_id
from RxyCode.RxyCode1_1_0.memory.long_term import validate_session_id

from .task_tool import (
    _TASK_LOCK,
    _load_tasks,
    _save_tasks,
    _task_file_lock,
    _tasks_dir,
)

TODO_STATUSES = ("pending", "in_progress", "completed", "blocked", "cancelled")
_LEGACY_STATUS = {"open": "pending", "done": "completed", "abandoned": "cancelled"}

# Read, render, and restore never call a summarizer. This counter stays 0.
todo_summary_llm_calls = 0


class TodoItemIn(BaseModel):
    id: str
    content: str | None = None
    status: str | None = None
    priority: str | None = None


class TodoWriteInput(BaseModel):
    todos: list[TodoItemIn]
    merge: bool = True


class TodoWriteResult(str):
    """Model-facing summary string with the snapshot from this same call."""

    snapshot: TodoSnapshot
    text: str

    def __new__(cls, text: str, snapshot: TodoSnapshot):
        obj = str.__new__(cls, text)
        obj.text = text
        obj.snapshot = snapshot
        return obj


def _canonical_status(status: str | None) -> str | None:
    if status is None or status == "":
        return "pending"
    mapped = _LEGACY_STATUS.get(str(status), str(status))
    if mapped not in TODO_STATUSES:
        return None
    return mapped


def _stored_content(row: dict) -> str:
    return str(row.get("content") or row.get("summary") or "")


def _session_directory(session_id: str | None) -> Path:
    if session_id:
        from RxyCode.RxyCode1_1_0.config.settings import get_data_dir

        directory = get_data_dir() / "tasks" / validate_session_id(session_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory
    return _tasks_dir()


def read_todo_models(session_id: str | None = None) -> list[TodoItem]:
    directory = _session_directory(session_id)
    with _TASK_LOCK, _task_file_lock(directory):
        document = _load_tasks(directory)
    items: list[TodoItem] = []
    for key, row in document.get("tasks", {}).items():
        if not isinstance(row, dict):
            continue
        items.append(
            TodoItem(
                id=str(row.get("id") or key),
                content=_stored_content(row),
                status=_canonical_status(row.get("status")),  # type: ignore[arg-type]
                priority=row.get("priority"),
            )
        )
    return items


def _merge(current: dict[str, dict], incoming: list[TodoItemIn]) -> list[dict]:
    rows = {key: dict(row) for key, row in current.items()}
    order = list(rows)
    for item in incoming:
        row = rows.get(item.id, {"id": item.id, "history": [], "created": time.time()})
        if item.content is not None:
            row["content"] = item.content
            row["summary"] = item.content
        if item.status is not None:
            row["status"] = item.status if _canonical_status(item.status) is None else _canonical_status(item.status)
        if item.priority is not None:
            row["priority"] = item.priority
        row["id"] = item.id
        rows[item.id] = row
        if item.id not in order:
            order.append(item.id)
    return [rows[key] for key in order]


def _replace(incoming: list[TodoItemIn]) -> list[dict]:
    rows = []
    for item in incoming:
        rows.append(
            {
                "id": item.id,
                "content": item.content or "",
                "summary": item.content or "",
                "status": item.status if _canonical_status(item.status) is None else _canonical_status(item.status),
                "priority": item.priority,
                "created": time.time(),
                "history": [],
            }
        )
    return rows


def _validate(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    unknown = [str(row["id"]) for row in rows if _canonical_status(row.get("status")) is None]
    if unknown:
        errors.append("unknown status: " + ", ".join(unknown))
    active = [str(row["id"]) for row in rows if _canonical_status(row.get("status")) == "in_progress"]
    if len(active) > 1:
        errors.append("in_progress conflict: " + ", ".join(active))
    for row in rows:
        if not _stored_content(row).strip():
            errors.append(f"content missing: {row['id']}")
    return errors


def render_todo_summary(rows: list[dict]) -> str:
    lines = [
        f"- [{_canonical_status(row.get('status'))}] {row['id']} {_stored_content(row)}".rstrip()
        for row in rows
    ]
    lines.append(f"todos: {len(rows)}")
    return "\n".join(lines)


def _snapshot(rows: list[dict], revision: int, session_id: str) -> TodoSnapshot:
    run_id = str(get_current_run_id() or "").strip() or None
    return TodoSnapshot(
        session_id=session_id,
        root_session_id=session_id,
        run_id=run_id,
        list_id="default",
        revision=revision,
        scope="turn",
        source="model",
        items=[
            TodoItem(
                id=str(row["id"]),
                content=_stored_content(row),
                status=_canonical_status(row.get("status")),  # type: ignore[arg-type]
                priority=row.get("priority"),
            )
            for row in rows
        ],
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def todo_write(
    todos: list[dict] | list[TodoItemIn] | None = None,
    merge: bool = True,
    session_id: str | None = None,
) -> TodoWriteResult | str:
    parsed = [item if isinstance(item, TodoItemIn) else TodoItemIn.model_validate(item) for item in (todos or [])]
    bound = session_id or current_session_id()
    directory = _session_directory(bound)
    with _TASK_LOCK, _task_file_lock(directory):
        document = _load_tasks(directory)
        current = document.get("tasks", {})
        merged_rows = _merge(current, parsed) if merge else _replace(parsed)
        errors = _validate(merged_rows)
        if errors:
            return "[todo_write rejected] " + "; ".join(errors)
        stored: dict[str, dict] = {}
        for row in merged_rows:
            previous = current.get(row["id"], {})
            history = list(previous.get("history") or row.get("history") or [])
            history.append(
                {
                    "status": _canonical_status(row.get("status")),
                    "ts": time.time(),
                    "note": "todo_write",
                }
            )
            content = _stored_content(row)
            stored[str(row["id"])] = {
                "id": str(row["id"]),
                "summary": content,
                "content": content,
                "status": _canonical_status(row.get("status")),
                "priority": row.get("priority"),
                "created": previous.get("created", row.get("created", time.time())),
                "history": history,
            }
        for key in list(stored):
            if key.startswith("T") and key[1:].isdigit():
                document["next_id"] = max(int(document.get("next_id") or 1), int(key[1:]) + 1)
        revision = int(document.get("revision") or 0) + 1
        document["tasks"] = stored
        document["revision"] = revision
        _save_tasks(directory, document)
        snapshot = _snapshot(list(stored.values()), revision, bound)
    return TodoWriteResult(render_todo_summary(list(stored.values())), snapshot)


def _todo_write_text(todos: list | None = None, merge: bool = True) -> str:
    return todo_write(todos, merge=merge)


async def todo_write_async(
    todos: list[TodoItemIn] | None = None,
    merge: bool = True,
) -> str:
    return _todo_write_text(todos, merge=merge)


todo_write_tool = StructuredTool(
    name="todo_write",
    description=(
        "Update the session checklist the user sees live. Use it when the work "
        "has 3 or more steps. Keep at most one item in_progress. Mark an item "
        "completed only from verification evidence, and do not batch those flips."
    ),
    func=_todo_write_text,
    coroutine=todo_write_async,
    args_schema=TodoWriteInput,
)
