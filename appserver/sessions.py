"""In-process session registry for appserver."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .task_store import DesktopTaskStore


@dataclass
class AppSessionRecord:
    session_id: str
    workspace_root: Path
    title: str = "New task"
    model_id: str | None = None
    provider_id: str | None = None
    status: str = "queued"
    trashed_at: str | None = None
    deleted_at: str | None = None
    restored_at: str | None = None
    associated_files: list[str] = field(default_factory=list)
    list_category: str | None = None
    archived_at: str | None = None
    forked_from: str | None = None
    parent_session_id: str | None = None
    root_session_id: str | None = None
    last_turn_request_id: str | None = None
    last_turn_result: dict[str, object] | None = None
    turn_results: dict[str, dict[str, object]] = field(default_factory=dict)
    agent_id: str | None = None
    trigger: str | None = None
    budget: dict[str, object] = field(default_factory=dict)
    permission_snapshot: dict[str, object] = field(default_factory=dict)
    lease_id: str | None = None
    orphan_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""
    usage: dict[str, object] = field(
        default_factory=lambda: {
            "input_tokens": None,
            "output_tokens": None,
            "cache_hit_tokens": None,
            "cache_write_tokens": None,
            "cache_hit_rate": None,
            "reporting_status": "not_reported",
        }
    )


class SessionStore:
    """Track multiple concurrent sessions in one appserver process."""

    def __init__(self, *, task_store: DesktopTaskStore | None = None) -> None:
        self._sessions: dict[str, AppSessionRecord] = {}
        self._task_store = task_store
        if task_store is not None:
            for task in task_store.list(include_trashed=True):
                self._sessions[str(task["session_id"])] = self._from_task(task)

    def create(
        self,
        workspace_root: Path | str,
        *,
        title: str = "新任务",
        model_id: str | None = None,
        provider_id: str | None = None,
    ) -> AppSessionRecord:
        session_id = uuid.uuid4().hex[:12]
        record = AppSessionRecord(
            session_id=session_id,
            workspace_root=Path(workspace_root),
            title=title,
            model_id=model_id,
            provider_id=provider_id,
            root_session_id=session_id,
        )
        self._sessions[session_id] = record
        self._persist(record)
        return record

    def set_workspace(self, session_id: str, workspace_root: Path | str) -> AppSessionRecord | None:
        record = self.get(session_id)
        if record is None:
            return None
        record.workspace_root = Path(workspace_root)
        self._touch(record)
        self._persist(record)
        return record

    def get(self, session_id: str) -> AppSessionRecord | None:
        return self._sessions.get(session_id)

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def set_model(
        self, session_id: str, model_id: str, provider_id: str | None = None
    ) -> AppSessionRecord:
        record = self._sessions.get(session_id)
        if record is None:
            raise KeyError(session_id)
        record.model_id = model_id
        record.provider_id = provider_id
        self._persist(record)
        return record

    def list(
        self,
        *,
        include_trashed: bool = False,
        include_archived: bool = False,
        workspace_root: str | None = None,
        status: str | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        parent_session_id: str | None = None,
    ) -> list[AppSessionRecord]:
        values = list(self._sessions.values())
        if not include_trashed:
            values = [record for record in values if record.trashed_at is None]
        if not include_archived:
            values = [record for record in values if not record.archived_at]
        if workspace_root:
            wanted = str(Path(workspace_root))
            values = [record for record in values if str(record.workspace_root) == wanted]
        if status:
            values = [record for record in values if record.status == status]
        if updated_after:
            values = [record for record in values if record.updated_at >= updated_after]
        if updated_before:
            values = [record for record in values if record.updated_at <= updated_before]
        if created_after:
            values = [record for record in values if record.created_at >= created_after]
        if created_before:
            values = [record for record in values if record.created_at <= created_before]
        if parent_session_id:
            values = [
                record for record in values if record.parent_session_id == parent_session_id
            ]
        return sorted(values, key=lambda record: record.updated_at, reverse=True)

    def child_count(self, session_id: str) -> int:
        return sum(
            1
            for record in self._sessions.values()
            if record.parent_session_id == session_id and record.trashed_at is None
        )

    def tree(self, session_id: str) -> list[AppSessionRecord]:
        record = self._require(session_id)
        root_id = record.root_session_id or record.session_id
        nodes = [
            item
            for item in self._sessions.values()
            if (item.root_session_id or item.session_id) == root_id
        ]
        if record not in nodes:
            nodes.append(record)
        return sorted(nodes, key=lambda item: item.created_at or item.session_id)

    def archive(self, session_id: str) -> AppSessionRecord:
        record = self._require(session_id)
        record.archived_at = _now()
        self._touch(record)
        self._persist(record)
        return record

    def unarchive(self, session_id: str) -> AppSessionRecord:
        record = self._require(session_id)
        record.archived_at = None
        self._touch(record)
        self._persist(record)
        return record

    def fork(self, session_id: str) -> AppSessionRecord:
        """Copy history into an independent thread. Parent is not a parent_session."""
        parent = self._require(session_id)
        child = self.create(
            parent.workspace_root,
            title=f"{parent.title} (fork)",
            model_id=parent.model_id,
            provider_id=parent.provider_id,
        )
        child.forked_from = parent.session_id
        child.root_session_id = child.session_id
        child.parent_session_id = None
        self._persist(child)
        if self._task_store is not None:
            self._task_store.copy_events(parent.session_id, child.session_id)
        return child

    def ensure_child(
        self,
        *,
        session_id: str,
        parent_session_id: str,
        workspace_root: Path | str,
        root_session_id: str | None = None,
        title: str | None = None,
        agent_id: str | None = None,
        trigger: str | None = None,
        budget: dict[str, object] | None = None,
        permission_snapshot: dict[str, object] | None = None,
        lease_id: str | None = None,
    ) -> AppSessionRecord:
        existing = self._sessions.get(session_id)
        parent = self._sessions.get(parent_session_id)
        expected_root = (
            (parent.root_session_id if parent is not None else None) or parent_session_id
        )
        if existing is not None:
            if existing.root_session_id != expected_root:
                existing.root_session_id = expected_root
            if existing.parent_session_id != parent_session_id:
                existing.parent_session_id = parent_session_id
            if budget:
                existing.budget = dict(budget)
            if permission_snapshot:
                existing.permission_snapshot = dict(permission_snapshot)
            if lease_id:
                existing.lease_id = lease_id
            if agent_id:
                existing.agent_id = agent_id
            if trigger:
                existing.trigger = trigger
            self._persist(existing)
            return existing
        if root_session_id and root_session_id != expected_root:
            root_session_id = expected_root
        root = root_session_id or expected_root
        record = AppSessionRecord(
            session_id=session_id,
            workspace_root=Path(workspace_root),
            title=title or "Child session",
            model_id=parent.model_id if parent is not None else None,
            provider_id=parent.provider_id if parent is not None else None,
            parent_session_id=parent_session_id,
            root_session_id=root,
            agent_id=agent_id,
            trigger=trigger,
            budget=dict(budget or {}),
            permission_snapshot=dict(permission_snapshot or {}),
            lease_id=lease_id,
        )
        self._sessions[session_id] = record
        self._persist(record)
        return record

    def record_child_terminal(
        self,
        session_id: str,
        status: str,
        *,
        reason: str | None = None,
    ) -> AppSessionRecord:
        record = self._require(session_id)
        record.status = status
        if status == "orphaned":
            record.orphan_reason = reason
        self._touch(record)
        self._persist(record)
        if self._task_store is not None:
            method = {
                "failed": "child_session/failed",
                "cancelled": "child_session/cancelled",
                "orphaned": "child_session/orphaned",
                "succeeded": "child_session/completed",
            }.get(status, "child_session/failed")
            self._task_store.append_event(
                session_id,
                {
                    "method": method,
                    "params": {
                        "session_id": session_id,
                        "parent_session_id": record.parent_session_id,
                        "root_session_id": record.root_session_id,
                        "status": status,
                        "reason": reason,
                    },
                },
            )
        return record

    def mark_orphans(
        self, parent_id: str, *, reason: str = "parent_closed"
    ) -> list[AppSessionRecord]:
        orphans: list[AppSessionRecord] = []
        for record in list(self._sessions.values()):
            if record.parent_session_id != parent_id:
                continue
            if record.trashed_at is not None:
                continue
            if record.status in {"succeeded", "cancelled", "failed", "orphaned"}:
                continue
            orphans.append(
                self.record_child_terminal(record.session_id, "orphaned", reason=reason)
            )
        return orphans

    def remember_turn(
        self, session_id: str, request_id: str, result: dict[str, object]
    ) -> None:
        record = self._sessions.get(session_id)
        if record is None:
            return
        record.last_turn_request_id = request_id
        record.last_turn_result = dict(result)
        record.turn_results[request_id] = dict(result)
        self._persist(record)

    def turn_result(self, session_id: str, request_id: str) -> dict[str, object] | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        stored = record.turn_results.get(request_id)
        if isinstance(stored, dict):
            return dict(stored)
        if record.last_turn_request_id == request_id and isinstance(record.last_turn_result, dict):
            return dict(record.last_turn_result)
        return None

    def rename(self, session_id: str, title: str) -> AppSessionRecord:
        record = self._require(session_id)
        clean = title.strip()
        if not clean:
            raise ValueError("title is required")
        record.title = clean
        self._touch(record)
        self._persist(record)
        return record

    def trash(self, session_id: str) -> AppSessionRecord:
        record = self._require(session_id)
        stamp = _now()
        if not record.list_category:
            record.list_category = "archive" if record.archived_at else "recent"
        record.trashed_at = stamp
        record.deleted_at = stamp
        self._touch(record)
        self._persist(record)
        self.mark_orphans(session_id, reason="parent_trashed")
        return record

    def enqueue_scheduled(self, session_id: str, *, kind: str, text: str, origin: str = "schedule") -> dict[str, object]:
        """B5 Thread channel: restore a trashed session and append a scheduled message."""
        record = self.get(session_id)
        if record is None:
            raise KeyError(session_id)
        if record.trashed_at:
            record = self.restore(session_id)
        if self._task_store is None:
            raise RuntimeError("task store required")
        method = {
            "session": "event/user_message",
            "command": "event/command",
            "skill": "event/skill",
        }.get(kind, "event/user_message")
        seq = self._task_store.append_event(
            record.session_id,
            {
                "method": method,
                "params": {
                    "session_id": record.session_id,
                    "text": text,
                    "kind": kind,
                    "origin": origin,
                    "channel": "b5-thread",
                },
            },
        )
        self._touch(record)
        self._persist(record)
        return {"session_id": record.session_id, "seq": seq, "method": method, "channel": "b5-thread"}

    def restore(self, session_id: str) -> AppSessionRecord:
        record = self._require(session_id)
        record.trashed_at = None
        record.deleted_at = None
        record.restored_at = _now()
        if record.list_category == "archive" and not record.archived_at:
            record.archived_at = record.restored_at
        self._touch(record)
        self._persist(record)
        return record

    def remember_associated(self, session_id: str, paths: list[str]) -> AppSessionRecord:
        record = self._require(session_id)
        seen: set[str] = set()
        unique: list[str] = []
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            unique.append(path)
        record.associated_files = unique
        self._persist(record)
        return record

    def list_deleted(self) -> list[AppSessionRecord]:
        return [record for record in self._sessions.values() if record.deleted_at or record.trashed_at]

    def purge(self, session_id: str) -> None:
        self._require(session_id)
        self._sessions.pop(session_id, None)
        if self._task_store is not None and self._task_store.get(session_id) is not None:
            self._task_store.purge(session_id)

    def update_status(self, session_id: str, status: str) -> AppSessionRecord | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        record.status = status
        self._touch(record)
        self._persist(record)
        return record

    def update_usage(self, session_id: str, usage: dict[str, object]) -> AppSessionRecord | None:
        record = self._sessions.get(session_id)
        if record is None:
            return None
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_hit_tokens",
            "cache_write_tokens",
            "cache_hit_rate",
            "reporting_status",
        ):
            if key in usage:
                record.usage[key] = usage[key]
        self._touch(record)
        self._persist(record)
        return record

    def _require(self, session_id: str) -> AppSessionRecord:
        record = self._sessions.get(session_id)
        if record is None:
            raise KeyError(session_id)
        return record

    @staticmethod
    def _from_task(task: dict) -> AppSessionRecord:
        return AppSessionRecord(
            session_id=str(task["session_id"]),
            workspace_root=Path(str(task["workspace_root"])),
            title=str(task.get("title") or "New task"),
            model_id=task.get("model_id"),
            provider_id=task.get("provider_id"),
            status=str(task.get("status") or "queued"),
            trashed_at=task.get("trashed_at"),
            deleted_at=task.get("deleted_at") or task.get("trashed_at"),
            restored_at=task.get("restored_at"),
            associated_files=list(task.get("associated_files") or []),
            list_category=task.get("list_category"),
            archived_at=task.get("archived_at"),
            forked_from=task.get("forked_from"),
            parent_session_id=task.get("parent_session_id"),
            root_session_id=task.get("root_session_id") or str(task["session_id"]),
            last_turn_request_id=task.get("last_turn_request_id"),
            last_turn_result=task.get("last_turn_result"),
            turn_results=dict(task.get("turn_results") or {}),
            agent_id=task.get("agent_id"),
            trigger=task.get("trigger"),
            budget=dict(task.get("budget") or {}),
            permission_snapshot=dict(task.get("permission_snapshot") or {}),
            lease_id=task.get("lease_id"),
            orphan_reason=task.get("orphan_reason"),
            created_at=str(task.get("created_at") or ""),
            updated_at=str(task.get("updated_at") or ""),
            usage=dict(task.get("usage") or {}),
        )

    @staticmethod
    def _touch(record: AppSessionRecord) -> None:
        record.updated_at = _now()

    def _persist(self, record: AppSessionRecord) -> None:
        if self._task_store is None:
            return
        if not record.created_at:
            record.created_at = _now()
        if not record.updated_at:
            record.updated_at = record.created_at
        self._task_store.upsert(
            session_id=record.session_id,
            title=record.title,
            workspace_root=record.workspace_root,
            model_id=record.model_id,
            provider_id=record.provider_id,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            trashed_at=record.trashed_at,
            deleted_at=record.deleted_at,
            restored_at=record.restored_at,
            associated_files=record.associated_files,
            list_category=record.list_category,
            usage=record.usage,
            archived_at=record.archived_at,
            forked_from=record.forked_from,
            parent_session_id=record.parent_session_id,
            root_session_id=record.root_session_id or record.session_id,
            last_turn_request_id=record.last_turn_request_id,
            last_turn_result=record.last_turn_result,
            turn_results=record.turn_results,
            agent_id=record.agent_id,
            trigger=record.trigger,
            budget=record.budget,
            permission_snapshot=record.permission_snapshot,
            lease_id=record.lease_id,
            orphan_reason=record.orphan_reason,
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
