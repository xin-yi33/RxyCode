"""Durable Desktop task metadata kept outside user workspaces.

The renderer owns presentation state, while this store owns only task
metadata and protocol replay cursors.  It deliberately never writes into a
workspace root and never stores prompt contents or credentials.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    from ..config.settings import get_data_dir
except ImportError:
    from config.settings import get_data_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _cross_process_lock(path: Path) -> Iterator[None]:
    """Exclusive lock so two windows cannot replace the same JSON file."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() < 1:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + 5.0
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    time.sleep(0.02)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


_UNSET = object()


class DesktopTaskStore:
    """Small atomic JSON store for task summaries and ordered event metadata."""

    def __init__(self, path: Path | str | None = None, *, persistent: bool = True) -> None:
        self.path = Path(path) if path is not None else get_data_dir() / "desktop" / "tasks.json"
        self.persistent = persistent
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {"tasks": {}, "events": {}}
        # Sessions this process has written. A save must not replace the rest.
        self._owned: set[str] = set()
        self._dropped: set[str] = set()
        self._load()

    def _claim(self, session_id: str) -> None:
        self._owned.add(session_id)
        self._dropped.discard(session_id)

    def _read_disk(self) -> dict[str, Any]:
        empty: dict[str, Any] = {"tasks": {}, "events": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return empty
        if not isinstance(value, dict):
            return empty
        tasks = value.get("tasks")
        events = value.get("events")
        loaded: dict[str, Any] = {
            "tasks": tasks if isinstance(tasks, dict) else {},
            "events": {},
        }
        if isinstance(events, dict):
            normalized: dict[str, list[dict[str, Any]]] = {}
            for session_id, raw_events in events.items():
                if not isinstance(raw_events, list):
                    continue
                session_events: list[dict[str, Any]] = []
                for storage_seq, raw_event in enumerate(raw_events, start=1):
                    if not isinstance(raw_event, dict):
                        continue
                    item = dict(raw_event)
                    old_seq = item.get("seq")
                    if "protocol_seq" not in item and isinstance(old_seq, int):
                        item["protocol_seq"] = old_seq
                    item["seq"] = storage_seq
                    session_events.append(item)
                normalized[str(session_id)] = session_events
            loaded["events"] = normalized
        return loaded

    def _load(self) -> None:
        if not self.persistent:
            return
        self._data = self._read_disk()

    def _union_events(
        self,
        disk_events: list[dict[str, Any]],
        memory_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [*disk_events, *memory_events]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("event_id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            ordered.append(dict(item))
        for index, item in enumerate(ordered, start=1):
            item["seq"] = index
        return ordered

    def _merge_owned(self, disk: dict[str, Any]) -> dict[str, Any]:
        tasks = dict(disk.get("tasks") or {})
        events = {
            str(key): list(value)
            for key, value in (disk.get("events") or {}).items()
            if isinstance(value, list)
        }
        for session_id in self._dropped:
            tasks.pop(session_id, None)
            events.pop(session_id, None)
        for session_id in self._owned - self._dropped:
            memory_task = self._data["tasks"].get(session_id)
            if isinstance(memory_task, dict):
                tasks[session_id] = memory_task
            memory_events = self._data["events"].get(session_id)
            if isinstance(memory_events, list):
                events[session_id] = self._union_events(
                    events.get(session_id) or [],
                    memory_events,
                )
        return {"tasks": tasks, "events": events}

    def _save(self) -> None:
        if not self.persistent:
            return
        if not self._owned and not self._dropped:
            return
        # 废弃代码（2026-09-22）：把内存里的整份 tasks.json 直接 replace。
        # 第二扇窗口保存时会抹掉第一扇窗口的会话和事件。
        # payload = json.dumps(self._data, ...)
        # os.replace(temp_name, self.path)
        with _cross_process_lock(self.path):
            disk = self._read_disk()
            merged = self._merge_owned(disk)
            self._data = merged
            payload = json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True)
            fd, temp_name = tempfile.mkstemp(prefix="tasks-", suffix=".json", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, self.path)
            finally:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
            self._dropped.clear()

    def upsert(
        self,
        *,
        session_id: str,
        title: str,
        workspace_root: Path | str,
        model_id: str | None = None,
        provider_id: str | None = None,
        status: str = "queued",
        created_at: str | None = None,
        updated_at: str | None = None,
        trashed_at: str | None = None,
        deleted_at: Any = _UNSET,
        restored_at: Any = _UNSET,
        associated_files: Any = _UNSET,
        list_category: Any = _UNSET,
        usage: dict[str, Any] | None = None,
        archived_at: Any = _UNSET,
        forked_from: Any = _UNSET,
        parent_session_id: Any = _UNSET,
        root_session_id: Any = _UNSET,
        last_turn_request_id: Any = _UNSET,
        last_user_prompt: Any = _UNSET,
        last_turn_result: Any = _UNSET,
        turn_results: Any = _UNSET,
        agent_id: Any = _UNSET,
        trigger: Any = _UNSET,
        budget: Any = _UNSET,
        permission_snapshot: Any = _UNSET,
        lease_id: Any = _UNSET,
        orphan_reason: Any = _UNSET,
        pinned: Any = _UNSET,
        generated_title: Any = _UNSET,
        title_is_manual: Any = _UNSET,
        title_source: Any = _UNSET,
        title_llm_pass: Any = _UNSET,
    ) -> dict[str, Any]:
        old = self._data["tasks"].get(session_id)
        self._claim(session_id)
        now = _now()

        def _pick(value: Any, key: str, default: Any = None) -> Any:
            if value is _UNSET:
                return (old or {}).get(key, default)
            return value

        task = {
            "session_id": session_id,
            "title": title,
            "workspace_root": str(workspace_root),
            "model_id": model_id,
            "provider_id": provider_id,
            "status": status,
            "created_at": created_at or (old or {}).get("created_at") or now,
            "updated_at": updated_at or now,
            "trashed_at": trashed_at,
            "deleted_at": _pick(deleted_at, "deleted_at"),
            "restored_at": _pick(restored_at, "restored_at"),
            "associated_files": list(_pick(associated_files, "associated_files", []) or []),
            "list_category": _pick(list_category, "list_category"),
            "archived_at": _pick(archived_at, "archived_at"),
            "forked_from": _pick(forked_from, "forked_from"),
            "parent_session_id": _pick(parent_session_id, "parent_session_id"),
            "root_session_id": _pick(root_session_id, "root_session_id") or session_id,
            "last_turn_request_id": _pick(last_turn_request_id, "last_turn_request_id"),
            "last_user_prompt": _pick(last_user_prompt, "last_user_prompt"),
            "last_turn_result": _pick(last_turn_result, "last_turn_result"),
            "turn_results": _pick(turn_results, "turn_results", {}) or {},
            "agent_id": _pick(agent_id, "agent_id"),
            "trigger": _pick(trigger, "trigger"),
            "budget": _pick(budget, "budget", {}) or {},
            "permission_snapshot": _pick(permission_snapshot, "permission_snapshot", {}) or {},
            "lease_id": _pick(lease_id, "lease_id"),
            "orphan_reason": _pick(orphan_reason, "orphan_reason"),
            "pinned": bool(_pick(pinned, "pinned", False)),
            "generated_title": _pick(generated_title, "generated_title"),
            "title_is_manual": bool(_pick(title_is_manual, "title_is_manual", False)),
            "title_source": _pick(title_source, "title_source", "default"),
            "title_llm_pass": int(_pick(title_llm_pass, "title_llm_pass", 0) or 0),
            "child_count": int((old or {}).get("child_count", 0) or 0),
            "usage": usage or (old or {}).get("usage") or {
                "input_tokens": None,
                "output_tokens": None,
                "cache_hit_tokens": None,
                "cache_write_tokens": None,
                "cache_hit_rate": None,
                "reporting_status": "not_reported",
            },
        }
        self._data["tasks"][session_id] = task
        self._save()
        return dict(task)

    def list(self, *, include_trashed: bool = False) -> list[dict[str, Any]]:
        values = list(self._data["tasks"].values())
        if not include_trashed:
            values = [item for item in values if item.get("trashed_at") is None]
        return sorted(values, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    def get(self, session_id: str) -> dict[str, Any] | None:
        task = self._data["tasks"].get(session_id)
        return dict(task) if isinstance(task, dict) else None

    def rename(self, session_id: str, title: str) -> dict[str, Any]:
        task = self._require(session_id)
        self._claim(session_id)
        clean = title.strip()
        if not clean:
            raise ValueError("title is required")
        task["title"] = clean
        task["updated_at"] = _now()
        self._save()
        return dict(task)

    def trash(self, session_id: str) -> dict[str, Any]:
        task = self._require(session_id)
        self._claim(session_id)
        task["trashed_at"] = _now()
        task["updated_at"] = _now()
        self._save()
        return dict(task)

    def restore(self, session_id: str) -> dict[str, Any]:
        task = self._require(session_id)
        self._claim(session_id)
        task["trashed_at"] = None
        task["updated_at"] = _now()
        self._save()
        return dict(task)

    def purge(self, session_id: str) -> None:
        self._require(session_id)
        self._owned.discard(session_id)
        self._dropped.add(session_id)
        del self._data["tasks"][session_id]
        self._data["events"].pop(session_id, None)
        self._save()

    def append_event(self, session_id: str, event: dict[str, Any]) -> int:
        self._claim(session_id)
        events = self._data["events"].setdefault(session_id, [])
        if not isinstance(events, list):
            events = []
            self._data["events"][session_id] = events
        seq = len(events) + 1
        value = dict(event)
        protocol_seq = value.pop("seq", None)
        value["seq"] = seq
        if isinstance(protocol_seq, int):
            value["protocol_seq"] = protocol_seq
        if not value.get("event_id"):
            value["event_id"] = uuid.uuid4().hex
        if not value.get("ts"):
            value["ts"] = _now()
        events.append(value)
        self._save()
        return seq

    def copy_events(self, source_id: str, dest_id: str) -> int:
        """Snapshot events into dest. Does not mutate source."""
        raw = self._data["events"].get(source_id, [])
        self._claim(dest_id)
        copied = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            value = copy.deepcopy(item)
            value["event_id"] = uuid.uuid4().hex
            value["seq"] = index
            copied.append(value)
        self._data["events"][dest_id] = copied
        self._save()
        return len(copied)

    def events(self, session_id: str, cursor: int = 0, *, limit: int | None = None) -> tuple[list[dict[str, Any]], int, bool]:
        values = self._data["events"].get(session_id, [])
        if not isinstance(values, list):
            return [], cursor, False
        ordered = [item for item in values if isinstance(item, dict)]
        latest = int(ordered[-1].get("seq", 0)) if ordered else 0
        selected = [item for item in ordered if int(item.get("seq", 0)) > cursor]
        expected = cursor + 1
        gap = bool(selected and int(selected[0].get("seq", expected)) > expected)
        if limit is not None and limit >= 0:
            selected = selected[:limit]
        if selected:
            latest = int(selected[-1].get("seq", latest))
        elif limit is not None:
            latest = cursor
        return selected, latest, gap

    def has_user_turn(self, session_id: str) -> bool:
        return bool(self.first_user_text(session_id))

    def first_user_text(self, session_id: str) -> str:
        for item in self._data["events"].get(session_id, []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("method") not in {"session/prompt", "event/user_message"}:
                continue
            params = item.get("params") if isinstance(item.get("params"), dict) else {}
            text = str(params.get("text") or params.get("content") or "").strip()
            if text:
                return text
        return ""

    def _require(self, session_id: str) -> dict[str, Any]:
        task = self._data["tasks"].get(session_id)
        if not isinstance(task, dict):
            raise KeyError(session_id)
        return task
