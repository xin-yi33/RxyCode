"""GX4 named snapshot + rewind orchestration.

Consumes B8 ReviewService.create/restore. Never lives under appserver/handlers/.
History checkpoints stay stored (forward nav = rewind to a later id).
Conversation truncation is a read-surface projection, not a delete.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .review import ReviewError, ReviewService
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
        self._messages: dict[str, list[dict[str, Any]]] = {}
        self._cutoff_seq: dict[str, int] = {}

    def record_message(self, session_id: str, *, role: str, text: str) -> dict[str, Any]:
        rows = self._messages.setdefault(session_id, [])
        seq = 1 + len(rows)
        item = {"seq": seq, "role": role, "text": text, "hidden": False}
        rows.append(item)
        return dict(item)

    def visible_messages(self, session_id: str) -> list[dict[str, Any]]:
        cutoff = self._cutoff_seq.get(session_id)
        rows = self._messages.get(session_id) or []
        if cutoff is None:
            return [dict(item) for item in rows if not item.get("hidden")]
        return [dict(item) for item in rows if int(item["seq"]) <= cutoff and not item.get("hidden")]

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
            visible = self.visible_messages(session_id)
            users = [item for item in visible if item.get("role") == "user"]
            prompt = str(users[-1]["text"]) if users else None
        created = self._reviews.create_checkpoint(
            session_id=session_id,
            workspace=record.workspace_root,
            reason="named_snapshot",
            name=str(name).strip(),
            user_prompt=prompt,
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
        )
        restored = self._reviews.restore_checkpoint(checkpoint_id, session_id=session_id)
        target_seq = int(target.get("seq") or 0)
        before = self.visible_messages(session_id)
        self._cutoff_seq[session_id] = target_seq
        after = self.visible_messages(session_id)
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
