"""GX4 named snapshot + rewind orchestration.

Consumes B8 ReviewService.create/restore. Never lives under appserver/handlers/.
History checkpoints stay stored (forward nav = rewind to a later id).
Conversation truncation is a session/items read-surface projection, not a delete.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .review import ReviewService
from .sessions import SessionStore


class CheckpointRewindError(Exception):
    def __init__(self, message: str, *, code: str = "checkpoint_rewind") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CheckpointRewindService:
    """Named snapshots plus rewind = snapshot + restore + truncate + refill."""

    def __init__(self, reviews: ReviewService, sessions: SessionStore) -> None:
        self._reviews = reviews
        self._sessions = sessions

    def _items(self, session_id: str) -> list[dict[str, Any]]:
        store = getattr(self._sessions, "_task_store", None)
        if store is None:
            return []
        items, _, _ = store.events(session_id, 0)
        return list(items)

    def _last_items_seq(self, session_id: str) -> int:
        items = self._items(session_id)
        if not items:
            return 0
        return int(items[-1].get("seq") or 0)

    def visible_items(self, session_id: str) -> list[dict[str, Any]]:
        record = self._sessions.get(session_id)
        cutoff = getattr(record, "projection_until_seq", None) if record is not None else None
        items = self._items(session_id)
        if cutoff is None:
            return items
        return [item for item in items if int(item.get("seq") or 0) <= int(cutoff)]

    def snapshot_create(
        self,
        *,
        session_id: str,
        name: str,
        user_prompt: str | None = None,
    ) -> dict[str, Any]:
        record = self._sessions.get(session_id)
        if record is None:
            raise CheckpointRewindError(f"unknown session: {session_id}", code="unknown_session")
        if not str(name or "").strip():
            raise CheckpointRewindError("name is required", code="invalid_name")
        prompt = user_prompt
        if prompt is None:
            prompt = getattr(record, "last_user_prompt", None)
        created = self._reviews.create_checkpoint(
            session_id=session_id,
            workspace=record.workspace_root,
            reason="named_snapshot",
            name=str(name).strip(),
            user_prompt=prompt,
            items_seq=self._last_items_seq(session_id),
        )
        return created

    def rewind(
        self,
        *,
        checkpoint_id: str,
        confirm: bool,
        session_id: str,
    ) -> dict[str, Any]:
        if confirm is not True:
            raise CheckpointRewindError("rewind requires explicit confirm=true", code="confirm_required")
        record = self._sessions.get(session_id)
        if record is None:
            raise CheckpointRewindError(f"unknown session: {session_id}", code="unknown_session")
        target = self._reviews.read_checkpoint(checkpoint_id, session_id=session_id)
        restore_point = self._reviews.create_checkpoint(
            session_id=session_id,
            workspace=Path(str(target.get("workspace") or record.workspace_root)),
            reason="pre-rewind",
            name=None,
            user_prompt=None,
            items_seq=self._last_items_seq(session_id),
        )
        restored = self._reviews.restore_checkpoint(checkpoint_id, session_id=session_id)
        before = self.visible_items(session_id)
        target_seq = int(target.get("items_seq") or 0)
        record.projection_until_seq = target_seq
        after = self.visible_items(session_id)
        truncated = max(0, len(before) - len(after))
        return {
            "restore_point": restore_point["checkpoint_id"],
            "restored_files": int(target.get("file_count") or 0),
            "truncated_messages": truncated,
            "refill_prompt": target.get("user_prompt"),
            "checkpoint_id": checkpoint_id,
            "diff_hash": restored.get("diff_hash"),
            "previous_diff_hash": restored.get("previous_diff_hash"),
            "stale_reviews": restored.get("stale_reviews") or [],
        }
