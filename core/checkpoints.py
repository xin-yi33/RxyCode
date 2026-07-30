"""Durable, dependency-free execution checkpoints.

The graph owns when checkpoints are taken.  This module owns the persistence
contract: stable identities, strict durable-state selection, atomic JSON
writes, interrupted-task recovery, corruption isolation, and bounded completed
history. Active replay roots are retained even when they exceed that bound.
Runtime dependencies are deliberately excluded from every serialization path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from RxyCode.RxyCode1_1_0.config.credential_store import atomic_write_text
from RxyCode.RxyCode1_1_0.config.settings import get_data_dir


CHECKPOINT_VERSION = 1
DEFAULT_RETENTION_LIMIT = 50
DURABLE_STATE_FIELDS = frozenset(
    {
        "user_input",
        "session_id",
        "task_tree",
        "memory_context",
        "conversation_history",
        "current_task_id",
        "execution_results",
        "parallel_tasks",
        "parallel_requested",
        "reflections",
        "failure_attribution",
        "replan_count",
        "reflection_action",
        "final_verification",
        "compression_count",
        "final_response",
        "phase",
        "error",
    }
)
FORBIDDEN_RUNTIME_FIELDS = frozenset(
    {
        "_llm",
        "_memory",
        "_tui",
        "_tool_orchestrator",
        "_tracer",
        "_checkpoint_store",
        "_checkpoint_mode",
        "_checkpoint_key_input",
        "_hooks",
        "_hook_audit",
        "_model_router",
        "_trajectory",
    }
)

_CHECKPOINT_ID_PATTERN = re.compile(r"^cp_[0-9a-f]{32}$")
_STORE_LOCK = threading.RLock()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utcnow()).isoformat()


def stable_checkpoint_id(session_id: str, user_input: str, mode: str) -> str:
    """Return a filesystem-safe ID scoped to one logical execution."""
    if not all(isinstance(value, str) for value in (session_id, user_input, mode)):
        raise TypeError("session_id, user_input, and mode must be strings")
    identity = json.dumps(
        [session_id, user_input, mode],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "cp_" + hashlib.sha256(identity).hexdigest()[:32]


def _validate_checkpoint_id(checkpoint_id: str) -> None:
    if not isinstance(checkpoint_id, str) or not _CHECKPOINT_ID_PATTERN.fullmatch(
        checkpoint_id
    ):
        raise ValueError(f"Invalid checkpoint_id: {checkpoint_id!r}")


def _jsonable(value: Any) -> Any:
    """Convert supported durable values without stringifying unknown objects."""
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("Checkpoint mappings must use string keys")
            if key in FORBIDDEN_RUNTIME_FIELDS:
                continue
            result[key] = _jsonable(nested)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    raise TypeError(
        f"Unsupported checkpoint value type: {type(value).__name__}; "
        "runtime dependencies cannot be persisted"
    )


def _durable_state(state: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise TypeError("state must be a mapping")
    return {
        key: _jsonable(state[key])
        for key in DURABLE_STATE_FIELDS
        if key in state
    }


def _atomic_write_json(path: Path, document: Mapping[str, Any]) -> None:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    atomic_write_text(path, payload + "\n")


def _validate_document(document: Any, expected_id: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("checkpoint root must be an object")
    required_types: dict[str, type] = {
        "version": int,
        "checkpoint_id": str,
        "attempt_id": str,
        "session_id": str,
        "user_input": str,
        "mode": str,
        "created_at": str,
        "updated_at": str,
        "completed": bool,
        "state": dict,
        "recovery_notes": list,
    }
    for key, expected_type in required_types.items():
        if not isinstance(document.get(key), expected_type):
            raise ValueError(f"checkpoint field {key!r} has an invalid type")
    if document["version"] != CHECKPOINT_VERSION:
        raise ValueError(f"unsupported checkpoint version {document['version']!r}")
    if document["checkpoint_id"] != expected_id:
        raise ValueError("checkpoint ID does not match its filename")
    _validate_checkpoint_id(document["checkpoint_id"])
    from RxyCode.RxyCode1_1_0.execution.tool_journal import validate_attempt_id

    validate_attempt_id(document["attempt_id"])
    if document.get("completed_at") is not None and not isinstance(
        document["completed_at"], str
    ):
        raise ValueError("checkpoint field 'completed_at' has an invalid type")
    for key in document["state"]:
        if key not in DURABLE_STATE_FIELDS:
            raise ValueError(f"checkpoint contains non-durable state field {key!r}")
    return document


class CheckpointStore:
    """Filesystem store for resumable execution snapshots."""

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        retention_limit: int = DEFAULT_RETENTION_LIMIT,
    ) -> None:
        if (
            not isinstance(retention_limit, int)
            or isinstance(retention_limit, bool)
            or retention_limit < 1
        ):
            raise ValueError("retention_limit must be a positive integer")
        self.directory = (
            Path(directory) if directory is not None else get_data_dir() / "checkpoints"
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.retention_limit = retention_limit

    @staticmethod
    def checkpoint_id(session_id: str, user_input: str, mode: str) -> str:
        return stable_checkpoint_id(session_id, user_input, mode)

    def _path(self, checkpoint_id: str) -> Path:
        _validate_checkpoint_id(checkpoint_id)
        return self.directory / f"{checkpoint_id}.json"

    def begin_attempt(
        self,
        session_id: str,
        user_input: str,
        mode: str,
    ) -> dict[str, Any]:
        """Return one durable attempt for a top-level request.

        An unfinished checkpoint keeps its attempt ID across process restarts.
        A completed checkpoint is replaced with a fresh attempt so an ordinary
        repeated user request cannot collide with an earlier tool result.
        """
        from RxyCode.RxyCode1_1_0.execution.tool_journal import new_attempt_id

        checkpoint_id = stable_checkpoint_id(session_id, user_input, mode)
        path = self._path(checkpoint_id)
        with _STORE_LOCK:
            existing = self._read_document(path)
            if existing is not None and not existing["completed"]:
                return existing

            now = _timestamp()
            document: dict[str, Any] = {
                "version": CHECKPOINT_VERSION,
                "checkpoint_id": checkpoint_id,
                "attempt_id": new_attempt_id(),
                "session_id": session_id,
                "user_input": user_input,
                "mode": mode,
                "created_at": now,
                "updated_at": now,
                "completed": False,
                "completed_at": None,
                "state": {},
                "recovery_notes": [],
            }
            _atomic_write_json(path, document)
            self._prune_locked()
            return document

    def save(
        self,
        session_id: str,
        user_input: str,
        mode: str,
        state: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Atomically save durable state and enforce the retention bound."""
        checkpoint_id = stable_checkpoint_id(session_id, user_input, mode)
        path = self._path(checkpoint_id)
        with _STORE_LOCK:
            existing = self._read_document(path)
            from RxyCode.RxyCode1_1_0.execution.tool_journal import new_attempt_id

            now = _timestamp()
            document: dict[str, Any] = {
                "version": CHECKPOINT_VERSION,
                "checkpoint_id": checkpoint_id,
                "attempt_id": (
                    existing["attempt_id"] if existing else new_attempt_id()
                ),
                "session_id": session_id,
                "user_input": user_input,
                "mode": mode,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
                "completed": existing["completed"] if existing else False,
                "completed_at": existing.get("completed_at") if existing else None,
                "state": _durable_state(state),
                "recovery_notes": existing["recovery_notes"] if existing else [],
            }
            _atomic_write_json(path, document)
            self._prune_locked()
            return document

    def load(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Load a checkpoint and normalize interrupted tasks for safe replay."""
        path = self._path(checkpoint_id)
        with _STORE_LOCK:
            document = self._read_document(path)
            if document is None:
                return None
            if self._recover_interrupted_tasks(document):
                document["updated_at"] = _timestamp()
                _atomic_write_json(path, document)
            return document

    def list(
        self,
        *,
        session_id: str | None = None,
        include_completed: bool = True,
    ) -> list[dict[str, Any]]:
        """List valid checkpoints newest first; corrupt files are quarantined."""
        with _STORE_LOCK:
            documents: list[dict[str, Any]] = []
            for path in self.directory.glob("cp_*.json"):
                document = self._read_document(path)
                if document is None:
                    continue
                if session_id is not None and document["session_id"] != session_id:
                    continue
                if not include_completed and document["completed"]:
                    continue
                documents.append(document)
            return sorted(
                documents,
                key=lambda item: (item["updated_at"], item["checkpoint_id"]),
                reverse=True,
            )

    def mark_complete(self, checkpoint_id: str) -> bool:
        """Mark a checkpoint completed without deleting its audit history."""
        path = self._path(checkpoint_id)
        with _STORE_LOCK:
            document = self._read_document(path)
            if document is None:
                return False
            now = _timestamp()
            document["completed"] = True
            document["completed_at"] = now
            document["updated_at"] = now
            _atomic_write_json(path, document)
            return True

    def reset(
        self,
        checkpoint_id: str | None = None,
        *,
        session_id: str | None = None,
    ) -> int:
        """Delete one checkpoint, one session's checkpoints, or all snapshots."""
        if checkpoint_id is not None and session_id is not None:
            raise ValueError("Specify checkpoint_id or session_id, not both")
        with _STORE_LOCK:
            if checkpoint_id is not None:
                path = self._path(checkpoint_id)
                if not path.is_file():
                    return 0
                path.unlink()
                return 1

            removed = 0
            for path in list(self.directory.glob("cp_*.json")):
                if session_id is not None:
                    document = self._read_document(path)
                    if document is None or document["session_id"] != session_id:
                        continue
                path.unlink(missing_ok=True)
                removed += 1
            return removed

    def _read_document(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw = json.load(stream)
            return _validate_document(raw, path.stem)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            self._quarantine_locked(path)
            return None

    def _quarantine_locked(self, path: Path) -> None:
        if not path.exists():
            return
        corrupt_dir = self.directory / "corrupt"
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        stamp = _utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        target = corrupt_dir / f"{path.stem}.{stamp}.{uuid4().hex[:8]}.json"
        try:
            os.replace(path, target)
        except OSError:
            return
        self._prune_corrupt_locked(corrupt_dir)

    def _prune_corrupt_locked(self, corrupt_dir: Path) -> None:
        files = sorted(
            (path for path in corrupt_dir.glob("*.json") if path.is_file()),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        for path in files[: -self.retention_limit]:
            path.unlink(missing_ok=True)

    def _prune_locked(self) -> None:
        documents: list[tuple[Path, dict[str, Any]]] = []
        for path in self.directory.glob("cp_*.json"):
            document = self._read_document(path)
            if document is not None:
                documents.append((path, document))
        excess = len(documents) - self.retention_limit
        if excess <= 0:
            return
        # Active snapshots are replay-safety roots: evicting one can orphan a
        # pending side-effect journal and allow a duplicate external action.
        # Retention is therefore a hard bound only for completed snapshots.
        documents.sort(
            key=lambda item: (
                0 if item[1]["completed"] else 1,
                item[1]["updated_at"],
                item[1]["checkpoint_id"],
            )
        )
        completed = [item for item in documents if item[1]["completed"]]
        for path, _document in completed[:excess]:
            path.unlink(missing_ok=True)

    @staticmethod
    def _recover_interrupted_tasks(document: dict[str, Any]) -> bool:
        tree = document["state"].get("task_tree")
        if not isinstance(tree, dict) or not isinstance(tree.get("nodes"), dict):
            return False

        changed = False
        recovered_at = _timestamp()
        phase = document["state"].get("phase")
        for task_id, node in tree["nodes"].items():
            if not isinstance(node, dict):
                continue
            previous = node.get("status")
            if previous not in {"running", "re_planning"}:
                continue
            # Executor commits its result before transitioning the graph to
            # validation. Replaying that task could duplicate a side effect;
            # the validator is the next safe boundary.
            if (
                previous == "running"
                and phase == "validating"
                and node.get("result") is not None
            ):
                continue
            node["status"] = "pending"
            message = (
                f"[checkpoint recovery] reset interrupted status {previous} "
                f"to pending at {recovered_at}"
            )
            history = node.setdefault("error_history", [])
            if isinstance(history, list):
                history.append(message)
            document["recovery_notes"].append(
                {
                    "event": "interrupted_task_recovered",
                    "at": recovered_at,
                    "task_id": str(task_id),
                    "from_status": previous,
                    "to_status": "pending",
                    "reason": "process ended before the task reached a terminal state",
                }
            )
            changed = True
        if changed:
            document["state"]["phase"] = "executing"
            document["state"]["current_task_id"] = None
            document["state"]["parallel_tasks"] = []
        return changed
