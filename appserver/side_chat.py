"""GX16 read-only side chat derived from a parent thread.

Does not copy parent messages; projects them. Independent usage. Close on parent archive/delete.
Never lives under appserver/handlers/.
"""

from __future__ import annotations

from typing import Any

from .sessions import SessionStore


class SideChatError(Exception):
    def __init__(self, message: str, *, code: str = "side_chat") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SideChatService:
    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions
        self._sides: dict[str, dict[str, Any]] = {}
        self._by_parent: dict[str, list[str]] = {}

    def create(self, *, thread_id: str, context_projection: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        parent = self._sessions.get(thread_id)
        if parent is None:
            raise SideChatError(f"unknown thread: {thread_id}", code="unknown_thread")
        child = self._sessions.create(
            parent.workspace_root,
            title=f"{parent.title} (side)",
            model_id=parent.model_id,
            provider_id=parent.provider_id,
        )
        child.parent_session_id = parent.session_id
        child.root_session_id = parent.root_session_id or parent.session_id
        self._sessions._persist(child)
        record = {
            "side_thread_id": child.session_id,
            "parent_thread_id": parent.session_id,
            "context_projection": list(context_projection or []),
            "context_copied": False,
            "usage": {"input_tokens": 0, "output_tokens": 0, "budget_tag": "side"},
            "closed": False,
        }
        self._sides[child.session_id] = record
        self._by_parent.setdefault(parent.session_id, []).append(child.session_id)
        return {
            "side_thread_id": child.session_id,
            "context_tokens": len(record["context_projection"]),
            "context_copied": False,
            "budget_tag": "side",
        }

    def close(self, *, side_thread_id: str) -> dict[str, Any]:
        record = self._sides.get(side_thread_id)
        if record is None:
            raise SideChatError(f"unknown side chat: {side_thread_id}", code="unknown_side")
        record["closed"] = True
        return {"side_thread_id": side_thread_id, "closed": True}

    def close_for_parent(self, parent_thread_id: str) -> int:
        count = 0
        for side_id in list(self._by_parent.get(parent_thread_id) or []):
            self.close(side_thread_id=side_id)
            count += 1
        return count

    def get(self, side_thread_id: str) -> dict[str, Any]:
        record = self._sides.get(side_thread_id)
        if record is None:
            raise SideChatError(f"unknown side chat: {side_thread_id}", code="unknown_side")
        return dict(record)
