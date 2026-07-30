import json
import time
import asyncio
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..utils.atomic_file import atomic_write_text


_TASK_LOCK = threading.RLock()


class TaskInput(BaseModel):
    operation: str = Field(description="Operation: create, list, get, start, block, unblock, done, abandon, rename")
    id: str = Field(default="", description="Task ID (e.g. T1, T1.1)")
    summary: str = Field(default="", description="Task summary (for create/rename)")
    status: str = Field(default="", description="Status filter for list")
    event_summary: str = Field(default="", description="Short note for state transitions")


def _tasks_dir() -> Path:
    from ..config.settings import get_data_dir
    from ..core.session_runtime import current_session_id

    d = get_data_dir() / "tasks" / current_session_id()
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_session_tasks(session_id: str) -> int:
    """Remove one validated session's task document during session reset."""
    from ..config.settings import get_data_dir
    from ..memory.long_term import validate_session_id

    resolved = validate_session_id(session_id)
    directory = get_data_dir() / "tasks" / resolved
    if not directory.exists():
        return 0
    with _TASK_LOCK, _task_file_lock(directory):
        task_file = directory / "tasks.json"
        existed = task_file.exists()
        task_file.unlink(missing_ok=True)
    return int(existed and not task_file.exists())


@contextmanager
def _task_file_lock(directory: Path):
    """Serialize read-modify-write transactions across OS processes."""
    lock_path = directory / ".tasks.lock"
    stream = lock_path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _load_tasks(directory: Path) -> dict:
    p = directory / "tasks.json"
    if p.exists():
        document = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("task store root must be an object")
        if not isinstance(document.get("tasks", {}), dict):
            raise ValueError("task store tasks must be an object")
        next_id = document.get("next_id", 1)
        if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id < 1:
            raise ValueError("task store next_id must be a positive integer")
        document.setdefault("tasks", {})
        document.setdefault("next_id", 1)
        return document
    return {"tasks": {}, "next_id": 1}


def _save_tasks(directory: Path, data: dict) -> None:
    p = directory / "tasks.json"
    atomic_write_text(
        p,
        json.dumps(data, indent=2, ensure_ascii=False),
    )


def _manage_tasks_locked(
    directory: Path,
    operation: str,
    id: str = "",
    summary: str = "",
    status: str = "",
    event_summary: str = "",
) -> str:
    data = _load_tasks(directory)
    tasks = data.get("tasks", {})

    if operation == "create":
        tid = f"T{data.get('next_id', 1)}"
        tasks[tid] = {
            "id": tid,
            "summary": summary,
            "status": "open",
            "created": time.time(),
            "history": [{"status": "open", "ts": time.time(), "note": summary}],
        }
        data["next_id"] = data.get("next_id", 1) + 1
        _save_tasks(directory, data)
        return f"Created task {tid}: {summary}"

    if operation == "list":
        filt = status or ""
        lines = []
        for tid, t in tasks.items():
            if filt and t["status"] != filt:
                continue
            lines.append(f"{t['id']} [{t['status']}] {t['summary']}")
        return "\n".join(lines) if lines else "[no tasks]"

    if operation == "get":
        t = tasks.get(id)
        if not t:
            return f"[error: task {id} not found]"
        return json.dumps(t, indent=2, ensure_ascii=False)

    t = tasks.get(id)
    if not t:
        return f"[error: task {id} not found]"

    if operation == "start":
        t["status"] = "in_progress"
        t["history"].append({"status": "in_progress", "ts": time.time(), "note": event_summary})
    elif operation == "block":
        t["status"] = "blocked"
        t["history"].append({"status": "blocked", "ts": time.time(), "note": event_summary})
    elif operation == "unblock":
        t["status"] = "open"
        t["history"].append({"status": "open", "ts": time.time(), "note": event_summary})
    elif operation == "done":
        t["status"] = "done"
        t["history"].append({"status": "done", "ts": time.time(), "note": event_summary})
    elif operation == "abandon":
        t["status"] = "abandoned"
        t["history"].append({"status": "abandoned", "ts": time.time(), "note": event_summary})
    elif operation == "rename":
        t["summary"] = summary
    else:
        return f"[error: unknown operation '{operation}']"

    _save_tasks(directory, data)
    return f"Task {id} -> {t['status']}" if operation != "rename" else f"Task {id} renamed to: {summary}"


def manage_tasks(
    operation: str,
    id: str = "",
    summary: str = "",
    status: str = "",
    event_summary: str = "",
) -> str:
    directory = _tasks_dir()
    try:
        with _TASK_LOCK, _task_file_lock(directory):
            return _manage_tasks_locked(
                directory,
                operation,
                id,
                summary,
                status,
                event_summary,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"[error: task store unavailable: {exc}]"


async def manage_tasks_async(
    operation: str,
    id: str = "",
    summary: str = "",
    status: str = "",
    event_summary: str = "",
) -> str:
    await asyncio.sleep(0)
    return manage_tasks(operation, id, summary, status, event_summary)


task_tool = StructuredTool(
    name="task",
    description="Persistent task management. Operations: create, list, get, start, block, unblock, done, abandon, rename.",
    func=manage_tasks,
    coroutine=manage_tasks_async,
    args_schema=TaskInput,
)
