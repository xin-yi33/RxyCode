"""Durable Desktop task metadata kept outside user workspaces.

The renderer owns presentation state, while this store owns only task
metadata and protocol replay cursors.  It deliberately never writes into a
workspace root and never stores prompt contents or credentials.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
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

_logger = logging.getLogger(__name__)


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

# 回放事件后台 flush 的合并窗口：让一波连续事件只写一次盘。
_BUFFER_FLUSH_DELAY_SECONDS = 0.2


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
        # Buffered event flush state (append_event_buffered). The flusher task
        # is created lazily on the caller's event loop.
        self._event_dirty = False
        self._flush_task: asyncio.Task[None] | None = None
        # Bumped by purge and by task-metadata writes. A buffered event
        # snapshot carries the generation it observed; _save_snapshot drops
        # the round when a newer write has already landed.
        self._drop_generation = 0
        self._load()

    def _claim(self, session_id: str) -> None:
        self._owned.add(session_id)
        self._dropped.discard(session_id)

    def _note_metadata_write(self) -> None:
        """Task rows changed. An older event snapshot must not write them back."""
        self._drop_generation += 1

    def _arm_metadata_flush(self) -> bool:
        """Coalesce a metadata rewrite into the existing event flusher.

        Memory is already updated. With a running loop the cross-process
        read/merge/replace waits for the same ~0.2s burst window as replay
        events, and ``flush_pending`` still drains it on shutdown. No loop
        means the caller is synchronous, so the immediate save stays.
        """
        if not self.persistent:
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        self._event_dirty = True
        task = self._flush_task
        if task is None or task.done():
            self._flush_task = loop.create_task(self._flush_buffered_events())
        return True

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

    def _merge_state(
        self,
        disk: dict[str, Any],
        source: dict[str, Any],
        owned: set[str],
        dropped: set[str],
    ) -> dict[str, Any]:
        """Merge the owned slices of *source* over *disk* (disk wins nothing we own)."""
        tasks = dict(disk.get("tasks") or {})
        events = {
            str(key): list(value)
            for key, value in (disk.get("events") or {}).items()
            if isinstance(value, list)
        }
        for session_id in dropped:
            tasks.pop(session_id, None)
            events.pop(session_id, None)
        for session_id in owned - dropped:
            memory_task = source["tasks"].get(session_id)
            if isinstance(memory_task, dict):
                tasks[session_id] = memory_task
            memory_events = source["events"].get(session_id)
            if isinstance(memory_events, list):
                events[session_id] = self._union_events(
                    events.get(session_id) or [],
                    memory_events,
                )
        return {"tasks": tasks, "events": events}

    def _write_merged(self, merged: dict[str, Any]) -> None:
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
            merged = self._merge_state(disk, self._data, self._owned, self._dropped)
            self._data = merged
            self._write_merged(merged)
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
        restart_gate: Any = _UNSET,
        defer: bool = False,
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
        gate = _pick(restart_gate, "restart_gate")
        if isinstance(gate, dict):
            task["restart_gate"] = gate
        self._data["tasks"][session_id] = task
        self._note_metadata_write()
        if defer and self._arm_metadata_flush():
            return dict(task)
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

    def update_restart_gate(self, session_id: str, gate: dict[str, Any]) -> bool:
        """Persist the stall-restart gate on the session row.

        A later upsert that omits ``restart_gate`` keeps this value. The
        ledger of granted seconds stays in the worker and is not written here.
        """
        task = self._data["tasks"].get(session_id)
        if not isinstance(task, dict):
            return False
        self._claim(session_id)
        task["restart_gate"] = {
            "restart_count": int(gate.get("restart_count") or 0),
            "first_restart_at": gate.get("first_restart_at"),
        }
        task["updated_at"] = _now()
        self._note_metadata_write()
        self._save()
        return True

    def rename(self, session_id: str, title: str) -> dict[str, Any]:
        task = self._require(session_id)
        self._claim(session_id)
        clean = title.strip()
        if not clean:
            raise ValueError("title is required")
        task["title"] = clean
        task["updated_at"] = _now()
        self._note_metadata_write()
        self._save()
        return dict(task)

    def trash(self, session_id: str) -> dict[str, Any]:
        task = self._require(session_id)
        self._claim(session_id)
        task["trashed_at"] = _now()
        task["updated_at"] = _now()
        self._note_metadata_write()
        self._save()
        return dict(task)

    def restore(self, session_id: str) -> dict[str, Any]:
        task = self._require(session_id)
        self._claim(session_id)
        task["trashed_at"] = None
        task["updated_at"] = _now()
        self._note_metadata_write()
        self._save()
        return dict(task)

    def purge(self, session_id: str) -> None:
        self._require(session_id)
        self._owned.discard(session_id)
        self._dropped.add(session_id)
        # Invalidate any buffered-flush snapshot taken before this purge; the
        # generation check inside _save_snapshot runs under the same file
        # lock that the purge's own save below is serialized by.
        self._note_metadata_write()
        del self._data["tasks"][session_id]
        self._data["events"].pop(session_id, None)
        self._save()

    def _append_event_record(self, session_id: str, event: dict[str, Any]) -> int:
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
        return seq

    def append_event(self, session_id: str, event: dict[str, Any]) -> int:
        seq = self._append_event_record(session_id, event)
        self._save()
        return seq

    def append_event_buffered(
        self,
        session_key: str,
        method: str,
        payload: dict[str, Any],
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> int:
        """Append a replay event and flush it from a coalesced background task.

        The in-memory change is identical to :meth:`append_event` and happens
        on the caller's event-loop thread, but the expensive cross-process
        save (lock + re-read + merge + full rewrite + fsync) is deferred: a
        flusher task batches events for ~0.2s and persists a shallow snapshot
        via ``asyncio.to_thread``, so a steady stream of tool events can no
        longer freeze the appserver loop for seconds.

        Durability trade-off (intentional): if the process is killed before
        the flusher lands, up to ~0.2s of trailing transcript events may be
        lost.  These are display-replay records, not the execution truth;
        graceful shutdown calls :meth:`flush_pending` to bound the window.
        """
        seq = self._append_event_record(session_key, {"method": method, "params": payload})
        if not self.persistent:
            return seq
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
        if loop is None:
            # Synchronous callers have no loop to host the flusher; keep the
            # previous immediate-durability behavior for that path.
            self._save()
            return seq
        self._event_dirty = True
        task = self._flush_task
        if task is None or task.done():
            self._flush_task = loop.create_task(self._flush_buffered_events())
        return seq

    async def _flush_buffered_events(self) -> None:
        try:
            # Yield once so a burst of events coalesces into a single write.
            await asyncio.sleep(_BUFFER_FLUSH_DELAY_SECONDS)
            while self._event_dirty:
                self._event_dirty = False
                snapshot = self._event_snapshot()
                await asyncio.to_thread(self._save_snapshot, snapshot)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never let a disk failure kill the caller's loop.  The events
            # stay in memory and re-arm the dirty flag so the next buffered
            # append or flush_pending retries the write.
            self._event_dirty = True
            _logger.exception("failed to flush buffered session events")

    def _event_snapshot(self) -> dict[str, Any]:
        """Frozen view of the owned state for the off-loop save.

        Built on the event-loop thread with no interleaved awaits: the
        container structure is copied, each session's event list gets a
        ``list(...)`` shallow copy, and the immutable event dicts are shared
        by reference.  ``owned``/``dropped``/``_drop_generation`` travel with
        the snapshot so the writer thread never iterates live sets.
        """
        return {
            "tasks": {
                str(key): dict(value) if isinstance(value, dict) else value
                for key, value in self._data["tasks"].items()
            },
            "events": {
                str(key): list(value)
                for key, value in self._data["events"].items()
                if isinstance(value, list)
            },
            "owned": set(self._owned),
            "dropped": set(self._dropped),
            "drop_generation": self._drop_generation,
        }

    def _save_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Persist a frozen snapshot with the same cross-process merge as _save().

        Live memory is deliberately left untouched: events appended while
        this writer thread was merging must survive (the dirty loop
        re-flushes them), so unlike :meth:`_save` this never assigns
        ``self._data`` and never clears ``self._dropped``.  A purge that
        interleaved after the snapshot was taken bumps ``_drop_generation``
        (purge and task-metadata writes). Because the comparison happens
        under the same file lock that serializes those saves, aborting this
        round and retrying with a fresh snapshot cannot restore an older
        model, title, status, usage, or a purged session.
        """
        if not self.persistent:
            return
        if not snapshot["owned"] and not snapshot["dropped"]:
            return
        with _cross_process_lock(self.path):
            if snapshot["drop_generation"] != self._drop_generation:
                self._event_dirty = True
                return
            disk = self._read_disk()
            merged = self._merge_state(
                disk,
                {"tasks": snapshot["tasks"], "events": snapshot["events"]},
                snapshot["owned"],
                snapshot["dropped"],
            )
            self._write_merged(merged)

    async def flush_pending(self, timeout: float = 5.0) -> None:
        """Wait until every buffered event has been flushed to disk.

        Used by graceful shutdown and by tests.  Raises ``TimeoutError`` if
        the queue did not drain before the deadline.
        """
        deadline = time.monotonic() + timeout
        while True:
            task = self._flush_task
            if not self._event_dirty and (task is None or task.done()):
                return
            if task is None or task.done():
                task = asyncio.get_running_loop().create_task(self._flush_buffered_events())
                self._flush_task = task
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("DesktopTaskStore flush did not drain in time")
            done, _pending = await asyncio.wait({task}, timeout=remaining)
            if not done:
                raise TimeoutError("DesktopTaskStore flush did not drain in time")

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
