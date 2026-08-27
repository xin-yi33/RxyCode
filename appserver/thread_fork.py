"""GX8 message-level thread/fork and thread/pin.

session/fork copies the whole thread. This service forks from a user message.
Does not copy approval policy or child sessions. Never under appserver/handlers/.
"""

from __future__ import annotations

from typing import Any

from .sessions import SessionStore


class ThreadForkError(Exception):
    def __init__(self, message: str, *, code: str = "thread_fork") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ThreadForkService:
    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions
        self._messages: dict[str, list[dict[str, Any]]] = {}

    def add_message(self, thread_id: str, *, message_id: str, role: str, text: str) -> dict[str, Any]:
        item = {"message_id": message_id, "role": role, "text": text}
        self._messages.setdefault(thread_id, []).append(item)
        return dict(item)

    def messages(self, thread_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self._messages.get(thread_id) or []]

    def pin(self, thread_id: str, *, pinned: bool = True) -> dict[str, Any]:
        record = self._sessions.get(thread_id)
        if record is None:
            raise ThreadForkError(f"unknown thread: {thread_id}", code="unknown_thread")
        record.pinned = bool(pinned)
        self._sessions._persist(record)
        return {"thread_id": thread_id, "pinned": record.pinned}

    def fork(
        self,
        *,
        thread_id: str,
        message_id: str,
        edited_text: str | None = None,
    ) -> dict[str, Any]:
        src = self._sessions.get(thread_id)
        if src is None:
            raise ThreadForkError(f"unknown thread: {thread_id}", code="unknown_thread")
        rows = self._messages.get(thread_id) or []
        index = next((i for i, item in enumerate(rows) if item["message_id"] == message_id), None)
        if index is None:
            raise ThreadForkError(f"unknown message: {message_id}", code="unknown_message")
        cutoff = rows[index]
        if cutoff.get("role") != "user":
            raise ThreadForkError("fork point must be a user message", code="invalid_fork_point")
        copied = [dict(item) for item in rows[: index + 1]]
        if edited_text is not None:
            copied[-1] = {**copied[-1], "text": edited_text}
        child = self._sessions.create(
            src.workspace_root,
            title=f"{src.title} (fork)",
            model_id=src.model_id,
            provider_id=src.provider_id,
        )
        child.forked_from = src.session_id
        child.root_session_id = child.session_id
        child.parent_session_id = None
        child.permission_snapshot = {}
        self._sessions._persist(child)
        self._messages[child.session_id] = copied
        return {
            "thread_id": child.session_id,
            "forked_from": src.session_id,
            "message_id": message_id,
            "copied_messages": len(copied),
            "workspace_root": str(child.workspace_root),
            "permission_snapshot": dict(child.permission_snapshot),
        }
