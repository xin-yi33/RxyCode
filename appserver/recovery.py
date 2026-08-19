"""PhaseG-B12 notifications, replay cursors, and orphan recovery.

Never forges completed. Incomplete / unknown / interrupted states become
``recovery_required``. Frontend J12 may only consume these projections.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .lifecycle import RECOVERY_REQUIRED, mark_incomplete_recovery_required
from .settings import redact_text

NOTIFY_KINDS = (
    "turn.background",
    "approval.needed",
    "input.needed",
    "command.long",
    "turn.failed",
)
STATUS_TO_RECOVERY = {
    "running": RECOVERY_REQUIRED,
    "queued": RECOVERY_REQUIRED,
    "active": RECOVERY_REQUIRED,
    "approval": RECOVERY_REQUIRED,
    "submitted": RECOVERY_REQUIRED,
    "interrupted": RECOVERY_REQUIRED,
    "unknown": RECOVERY_REQUIRED,
    "recovery_required": RECOVERY_REQUIRED,
}
TERMINAL_KEEP = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


class RecoveryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def classify_status(status: str | None) -> str:
    raw = (status or "unknown").strip() or "unknown"
    if raw == "completed":
        return RECOVERY_REQUIRED
    if raw in TERMINAL_KEEP:
        return raw
    return STATUS_TO_RECOVERY.get(raw, RECOVERY_REQUIRED)


class RecoveryService:
    def __init__(self, path: Path | None = None, *, persistent: bool = True, task_store: Any = None) -> None:
        self.persistent = persistent
        self.path = path or Path(os.environ.get("RXYCODE_DATA_DIR", ".")) / "desktop" / "recovery.json"
        if persistent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._task_store = task_store
        self._data: dict[str, Any] = {
            "notifications": [],
            "cursors": {},
            "seen": {},
            "orphans": [],
        }
        self._load()

    def _load(self) -> None:
        if not self.persistent:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self._data.update(raw)
            self._data.setdefault("notifications", [])
            self._data.setdefault("cursors", {})
            self._data.setdefault("seen", {})
            self._data.setdefault("orphans", [])

    def _save(self) -> None:
        if not self.persistent:
            return
        payload = json.dumps(self._data, ensure_ascii=False, indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="recovery-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def notify(
        self,
        kind: str,
        *,
        session_id: str,
        dedupe_key: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if kind not in NOTIFY_KINDS:
            raise RecoveryError("NOTIFY_KIND_INVALID", f"unknown notification kind: {kind}")
        key = dedupe_key or f"{kind}:{session_id}"
        existing = (self._data.get("seen") or {}).get(key)
        if existing:
            for row in self._data.get("notifications") or []:
                if row.get("notification_id") == existing:
                    return {**row, "duplicate": True}
        record = {
            "notification_id": uuid.uuid4().hex[:12],
            "kind": kind,
            "session_id": session_id,
            "dedupe_key": key,
            "payload": {
                name: redact_text(value) if isinstance(value, str) else value
                for name, value in (payload or {}).items()
            },
            "acked": False,
            "created_at": _now(),
        }
        self._data.setdefault("notifications", []).append(record)
        self._data.setdefault("seen", {})[key] = record["notification_id"]
        self._save()
        return {**record, "duplicate": False}

    def list_notifications(self, session_id: str | None = None, *, include_acked: bool = False) -> list[dict[str, Any]]:
        rows = [dict(item) for item in self._data.get("notifications") or [] if isinstance(item, dict)]
        if session_id:
            rows = [row for row in rows if row.get("session_id") == session_id]
        if not include_acked:
            rows = [row for row in rows if not row.get("acked")]
        return rows

    def ack(self, notification_id: str) -> dict[str, Any]:
        for row in self._data.get("notifications") or []:
            if row.get("notification_id") == notification_id:
                row["acked"] = True
                row["acked_at"] = _now()
                self._save()
                return dict(row)
        raise RecoveryError("NOTIFY_NOT_FOUND", "unknown notification_id")

    def save_cursor(self, session_id: str, cursor: int) -> dict[str, Any]:
        if cursor < 0:
            raise RecoveryError("CURSOR_INVALID", "cursor must be >= 0")
        previous = self.cursor(session_id)
        entry = {"cursor": max(previous, int(cursor)), "updated_at": _now()}
        self._data.setdefault("cursors", {})[session_id] = entry
        self._save()
        return {"session_id": session_id, **entry}

    def cursor(self, session_id: str) -> int:
        entry = (self._data.get("cursors") or {}).get(session_id) or {}
        return int(entry.get("cursor") or 0)

    def replay(self, session_id: str, cursor: int | None = None, *, limit: int = 100) -> dict[str, Any]:
        start = self.cursor(session_id) if cursor is None else int(cursor)
        events: list[dict[str, Any]] = []
        next_cursor = start
        gap = False
        if self._task_store is not None:
            events, next_cursor, gap = self._task_store.events(session_id, start, limit=limit)
        stored = self.cursor(session_id)
        if next_cursor > stored:
            self.save_cursor(session_id, next_cursor)
        return {
            "session_id": session_id,
            "events": events,
            "cursor": start,
            "next_cursor": next_cursor,
            "gap": gap,
            "duplicate_connection": False,
        }

    def reconnect(self, session_id: str, cursor: int | None = None) -> dict[str, Any]:
        """Disconnect then reconnect: reuse saved cursor, flag a duplicate replay."""
        replayed = self.replay(session_id, cursor)
        replayed["duplicate_connection"] = cursor is not None and cursor < self.cursor(session_id)
        return replayed

    def project_status(self, status: str | None) -> str:
        return classify_status(status)

    def restore_after_restart(self, task_store: Any | None = None) -> dict[str, Any]:
        store = task_store if task_store is not None else self._task_store
        originals: dict[str, str] = {}
        if store is not None:
            for task in store.list(include_trashed=True):
                sid = str(task.get("session_id") or "")
                if sid:
                    originals[sid] = str(task.get("status") or "unknown")
        changed = mark_incomplete_recovery_required(store) if store is not None else []
        projected = []
        if store is not None:
            for task in store.list(include_trashed=True):
                previous = originals.get(str(task.get("session_id") or ""), str(task.get("status") or "unknown"))
                mapped = classify_status(previous)
                if mapped == RECOVERY_REQUIRED and previous not in TERMINAL_KEEP:
                    if previous != RECOVERY_REQUIRED:
                        store.upsert(
                            session_id=str(task.get("session_id")),
                            title=str(task.get("title") or "task"),
                            workspace_root=task.get("workspace_root") or ".",
                            model_id=task.get("model_id"),
                            provider_id=task.get("provider_id"),
                            status=RECOVERY_REQUIRED,
                            created_at=task.get("created_at"),
                            trashed_at=task.get("trashed_at"),
                            usage=task.get("usage"),
                        )
                    projected.append(
                        {
                            "session_id": task.get("session_id"),
                            "previous_status": previous,
                            "status": RECOVERY_REQUIRED,
                        }
                    )
        return {
            "recovered": [{"session_id": sid, "previous_status": prev} for sid, prev in changed],
            "projected": projected,
            "forged_complete": False,
        }

    def reclaim_orphans(self, live_session_ids: set[str] | None = None) -> list[dict[str, Any]]:
        store = self._task_store
        if store is None:
            return []
        live = live_session_ids or set()
        reclaimed: list[dict[str, Any]] = []
        for task in store.list(include_trashed=True):
            session_id = str(task.get("session_id") or "")
            status = str(task.get("status") or "unknown")
            if not session_id or status in TERMINAL_KEEP:
                continue
            if session_id in live:
                continue
            mapped = classify_status(status)
            if mapped != RECOVERY_REQUIRED:
                continue
            if any(item.get("session_id") == session_id for item in self._data.get("orphans") or []):
                continue
            if status == RECOVERY_REQUIRED and session_id not in live:
                item = {"session_id": session_id, "previous_status": status, "status": RECOVERY_REQUIRED}
                if item not in (self._data.get("orphans") or []):
                    self._data.setdefault("orphans", []).append(item)
                    reclaimed.append(item)
                continue
            store.upsert(
                session_id=session_id,
                title=str(task.get("title") or "task"),
                workspace_root=task.get("workspace_root") or ".",
                model_id=task.get("model_id"),
                provider_id=task.get("provider_id"),
                status=RECOVERY_REQUIRED,
                created_at=task.get("created_at"),
                trashed_at=task.get("trashed_at"),
                usage=task.get("usage"),
            )
            item = {"session_id": session_id, "previous_status": status, "status": RECOVERY_REQUIRED}
            reclaimed.append(item)
            self._data.setdefault("orphans", []).append(item)
        self._save()
        return reclaimed

    def observe_event(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Map live protocol events onto the public notification kinds."""
        params = params or {}
        session_id = str(params.get("session_id") or params.get("root_session_id") or "")
        if not session_id:
            return None
        kind = None
        if method in {"turn/started", "event/task_started"} and params.get("background"):
            kind = "turn.background"
        elif method in {"approval/request", "event/approval"}:
            kind = "approval.needed"
        elif method in {"question/request", "event/question"}:
            kind = "input.needed"
        elif method in {"event/execution", "command/start"}:
            long_running = bool(params.get("background") or params.get("long_running"))
            duration = params.get("duration_s") or params.get("elapsed")
            try:
                long_running = long_running or float(duration or 0) >= 5
            except (TypeError, ValueError):
                pass
            if long_running or params.get("kind") in {"command", "background"}:
                kind = "command.long"
        elif method in {"turn/failed", "event/error"}:
            kind = "turn.failed"
        elif method == "event/task_complete" and params.get("status") in {"failed", "error"}:
            kind = "turn.failed"
        if kind is None:
            return None
        token = (
            params.get("event_id")
            or params.get("request_id")
            or params.get("turn_id")
            or params.get("approval_id")
        )
        if token:
            key = f"{kind}:{session_id}:{token}"
        else:
            key = f"{kind}:{session_id}:{method}:{uuid.uuid4().hex[:8]}"
        return self.notify(kind, session_id=session_id, dedupe_key=key)

    def initialize_catchup(self, session_id: str) -> dict[str, Any]:
        """Thread metadata + item replay after initialize / reconnect."""
        meta = None
        if self._task_store is not None:
            try:
                meta = self._task_store._require(session_id)
            except KeyError:
                meta = None
        replayed = self.replay(session_id)
        return {
            "session_id": session_id,
            "thread": {
                "session_id": session_id,
                "status": classify_status((meta or {}).get("status")),
                "title": (meta or {}).get("title"),
            } if meta else None,
            "items": replayed["events"],
            "next_cursor": replayed["next_cursor"],
            "gap": replayed["gap"],
        }

    def status(self, session_id: str | None = None) -> dict[str, Any]:
        store = self._task_store
        tasks = []
        if store is not None:
            for task in store.list(include_trashed=True):
                if session_id and task.get("session_id") != session_id:
                    continue
                tasks.append(
                    {
                        "session_id": task.get("session_id"),
                        "status": classify_status(task.get("status")),
                        "raw_status": task.get("status"),
                    }
                )
        return {
            "tasks": tasks,
            "cursor": self.cursor(session_id) if session_id else None,
            "notifications": self.list_notifications(session_id),
        }
