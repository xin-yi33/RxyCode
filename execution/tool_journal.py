"""Crash-safe journal for side-effecting tool invocations.

The journal deliberately implements *at-most-once replay*, not distributed
exactly-once execution.  A process can die after an external side effect but
before the result is committed.  Such a call remains ``pending`` and is
blocked on resume so an unknown side effect is never repeated automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time as _time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from RxyCode.RxyCode1_1_0.config.credential_store import atomic_write_text
from RxyCode.RxyCode1_1_0.config.settings import get_data_dir


JOURNAL_VERSION = 1
DEFAULT_RETENTION_LIMIT = 100
DEFAULT_MAX_RESULT_CHARS = 30_000

_ATTEMPT_ID_PATTERN = re.compile(r"^att_[0-9a-f]{32}$")
_CALL_KEY_PATTERN = re.compile(r"^call_[0-9a-f]{64}$")
_CHECKPOINT_ID_PATTERN = re.compile(r"^cp_[0-9a-f]{32}$")
_JOURNAL_LOCK = threading.RLock()


class ToolJournalError(RuntimeError):
    """Base class for fail-closed journal errors."""


class ToolJournalCorruptionError(ToolJournalError):
    """Raised after a corrupt journal is quarantined."""


class ToolJournalStateError(ToolJournalError):
    """Raised when a journal transition would weaken replay safety."""


class ToolJournalBusyError(ToolJournalError):
    """Raised when the interprocess lock is held by another process.

    Distinct from :class:`ToolJournalStateError` so callers can retry only the
    transient lock-contention case instead of treating it as a permanent block.
    """


#: Number of times a reserve/commit retries a transient lock-busy error before
#: failing closed. Non-blocking OS locks (msvcrt.locking LK_NBLCK on Windows)
#: can momentarily contend between the journal lock and the per-directory file
#: lock; a bounded retry removes that flakiness without weakening replay safety.
_JOURNAL_LOCK_RETRIES = 5
_JOURNAL_LOCK_BACKOFF = 0.05


@contextmanager
def _interprocess_lock(directory: Path):
    """Take a non-blocking OS lock for cross-process atomic transitions."""
    lock_path = directory / ".journal.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ToolJournalBusyError("tool journal is busy") from exc
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ToolJournalBusyError("tool journal is busy") from exc
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


@contextmanager
def _interprocess_lock_retry(directory: Path):
    """Acquire the interprocess lock, retrying transient busy errors.

    A genuine state/corruption error propagates immediately; only
    :class:`ToolJournalBusyError` (another process momentarily holds the lock)
    is retried with a small linear backoff.
    """
    last_exc: ToolJournalBusyError | None = None
    for attempt in range(_JOURNAL_LOCK_RETRIES):
        try:
            with _interprocess_lock(directory):
                yield
                return
        except ToolJournalBusyError as exc:
            last_exc = exc
            if attempt + 1 >= _JOURNAL_LOCK_RETRIES:
                raise
            _time.sleep(_JOURNAL_LOCK_BACKOFF * (attempt + 1))
    if last_exc is not None:  # pragma: no cover - defensive
        raise last_exc


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_attempt_id() -> str:
    """Return a filesystem-safe ID for one top-level request attempt."""
    return f"att_{uuid4().hex}"


def validate_attempt_id(attempt_id: str) -> str:
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_PATTERN.fullmatch(
        attempt_id
    ):
        raise ValueError(f"Invalid attempt_id: {attempt_id!r}")
    return attempt_id


def _canonical_value(value: Any) -> Any:
    """Build deterministic hash material without stringifying unknown objects."""
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    value_type = type(value)
    return {"unsupported_type": f"{value_type.__module__}.{value_type.__qualname__}"}


def arguments_digest(args: Any) -> str:
    """Hash arguments so plaintext credentials never enter the journal."""
    payload = json.dumps(
        _canonical_value(args),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stable_call_key(tool: str, args_digest: str, ordinal: int) -> str:
    """Identify one logical occurrence inside an attempt.

    ReAct proxy calls do not expose the model's tool-call ID.  The stable key
    therefore combines the canonical tool, an argument digest, and an
    occurrence ordinal for identical calls.  A materially changed resumed
    plan is a new logical call rather than a replay of the old one.
    """
    material = json.dumps(
        [str(tool).strip().lower(), args_digest, ordinal],
        separators=(",", ":"),
    ).encode("utf-8")
    return "call_" + hashlib.sha256(material).hexdigest()


def _safe_tool_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).strip().lower())
    return (cleaned or "unknown")[:80]


def _clean_result(result: Any, max_chars: int) -> str:
    text = str(result)
    text = "".join(char for char in text if char in "\n\r\t" or ord(char) >= 32)
    text = re.sub(
        r"(?i)\b(api[_-]?key|authorization|password|passwd|secret|token)"
        r"\s*([:=])\s*([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer ***", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", text)
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head
    return (
        text[:head]
        + f"\n[journal result truncated: {len(text) - max_chars} chars omitted]\n"
        + text[-tail:]
    )


@dataclass(frozen=True)
class JournalCall:
    key: str
    tool: str
    args_digest: str
    ordinal: int


@dataclass(frozen=True)
class JournalReservation:
    action: Literal["execute", "reuse", "uncertain"]
    result: str | None = None


class ToolJournalBinding:
    """Request-local stable-call allocator bound through a ContextVar."""

    def __init__(
        self,
        journal: "ToolExecutionJournal",
        attempt_id: str,
        checkpoint_id: str | None = None,
    ) -> None:
        self.journal = journal
        self.attempt_id = validate_attempt_id(attempt_id)
        if checkpoint_id is not None and not _CHECKPOINT_ID_PATTERN.fullmatch(
            checkpoint_id
        ):
            raise ValueError(f"Invalid checkpoint_id: {checkpoint_id!r}")
        self.checkpoint_id = checkpoint_id
        self._ordinals: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def next_call(self, tool: str, args: Any) -> JournalCall:
        canonical_tool = str(tool).strip().lower()
        digest = arguments_digest(args)
        signature = (canonical_tool, digest)
        with self._lock:
            ordinal = self._ordinals.get(signature, 0)
            self._ordinals[signature] = ordinal + 1
        return JournalCall(
            key=stable_call_key(canonical_tool, digest, ordinal),
            tool=canonical_tool,
            args_digest=digest,
            ordinal=ordinal,
        )


class ToolExecutionJournal:
    """Atomic JSON store for pending/completed mutating calls."""

    def __init__(
        self,
        directory: str | Path | None = None,
        *,
        retention_limit: int = DEFAULT_RETENTION_LIMIT,
        max_result_chars: int = DEFAULT_MAX_RESULT_CHARS,
    ) -> None:
        if (
            not isinstance(retention_limit, int)
            or isinstance(retention_limit, bool)
            or retention_limit < 1
        ):
            raise ValueError("retention_limit must be a positive integer")
        if (
            not isinstance(max_result_chars, int)
            or isinstance(max_result_chars, bool)
            or max_result_chars < 1000
        ):
            raise ValueError("max_result_chars must be an integer >= 1000")
        self.directory = (
            Path(directory)
            if directory is not None
            else get_data_dir() / "tool_journal"
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.retention_limit = retention_limit
        self.max_result_chars = max_result_chars

    def binding(
        self,
        attempt_id: str,
        checkpoint_id: str | None = None,
    ) -> ToolJournalBinding:
        return ToolJournalBinding(self, attempt_id, checkpoint_id)

    def _path(self, attempt_id: str) -> Path:
        validate_attempt_id(attempt_id)
        return self.directory / f"{attempt_id}.json"

    @staticmethod
    def _new_document(
        attempt_id: str,
        checkpoint_id: str | None,
    ) -> dict[str, Any]:
        now = _utc_timestamp()
        return {
            "version": JOURNAL_VERSION,
            "attempt_id": attempt_id,
            "checkpoint_id": checkpoint_id,
            "created_at": now,
            "updated_at": now,
            "completed": False,
            "completed_at": None,
            "poisoned": False,
            "entries": {},
        }

    def reserve(
        self,
        attempt_id: str,
        call: JournalCall,
        *,
        checkpoint_id: str | None = None,
    ) -> JournalReservation:
        """Atomically reserve a call before an external side effect."""
        if not _CALL_KEY_PATTERN.fullmatch(call.key):
            raise ValueError("Invalid journal call key")
        path = self._path(attempt_id)
        with _JOURNAL_LOCK, _interprocess_lock_retry(self.directory):
            self._assert_no_orphan_attempt_locked(attempt_id, checkpoint_id)
            document = self._read(path, poison_checkpoint_id=checkpoint_id)
            if document is None:
                document = self._new_document(attempt_id, checkpoint_id)
            elif document.get("checkpoint_id") != checkpoint_id:
                raise ToolJournalStateError("journal checkpoint scope changed")
            entry = document["entries"].get(call.key)
            if entry is not None:
                if entry["status"] == "completed":
                    return JournalReservation("reuse", str(entry["result"]))
                return JournalReservation("uncertain")
            if any(
                candidate.get("status") == "pending"
                and candidate.get("tool") == _safe_tool_name(call.tool)
                and candidate.get("args_digest") == call.args_digest
                for candidate in document["entries"].values()
            ):
                # A model retry may receive a different/random call ID and the
                # request-local allocator advances to a new ordinal.  Neither
                # is allowed to bypass an unknown outcome for the same action.
                return JournalReservation("uncertain")
            if document["completed"]:
                raise ToolJournalStateError("cannot add a call to a sealed attempt")
            now = _utc_timestamp()
            document["entries"][call.key] = {
                "status": "pending",
                "tool": _safe_tool_name(call.tool),
                "args_digest": call.args_digest,
                "ordinal": call.ordinal,
                "created_at": now,
                "completed_at": None,
                "result": None,
            }
            document["updated_at"] = now
            self._write(path, document)
            self._prune_locked()
            return JournalReservation("execute")

    def complete(self, attempt_id: str, call: JournalCall, result: Any) -> str:
        """Commit a verified, cleaned result after successful execution."""
        path = self._path(attempt_id)
        with _JOURNAL_LOCK, _interprocess_lock_retry(self.directory):
            document = self._read(path)
            if document is None:
                raise ToolJournalStateError("pending journal entry is missing")
            entry = document["entries"].get(call.key)
            if entry is None or entry.get("status") != "pending":
                raise ToolJournalStateError("call is not pending")
            cleaned = _clean_result(result, self.max_result_chars)
            now = _utc_timestamp()
            entry["status"] = "completed"
            entry["completed_at"] = now
            entry["result"] = cleaned
            document["updated_at"] = now
            self._write(path, document)
            return cleaned

    def mark_attempt_complete(self, attempt_id: str) -> bool:
        """Seal an attempt only when no side effect has an unknown outcome."""
        path = self._path(attempt_id)
        with _JOURNAL_LOCK, _interprocess_lock(self.directory):
            document = self._read(path)
            if document is None:
                return False
            if any(
                entry.get("status") == "pending"
                for entry in document["entries"].values()
            ):
                return False
            now = _utc_timestamp()
            document["completed"] = True
            document["completed_at"] = now
            document["updated_at"] = now
            self._write(path, document)
            self._prune_locked()
            return True

    def has_pending(self, attempt_id: str) -> bool:
        path = self._path(attempt_id)
        with _JOURNAL_LOCK, _interprocess_lock(self.directory):
            document = self._read(path)
            if document is None:
                return False
            return any(
                entry.get("status") == "pending"
                for entry in document["entries"].values()
            )

    def load(self, attempt_id: str) -> dict[str, Any] | None:
        with _JOURNAL_LOCK, _interprocess_lock(self.directory):
            document = self._read(self._path(attempt_id))
            return json.loads(json.dumps(document)) if document is not None else None

    def _read(
        self,
        path: Path,
        *,
        poison_checkpoint_id: str | None = None,
        allow_poison: bool = False,
    ) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            document = self._validate_document(raw, path.stem)
            if document["poisoned"] and not allow_poison:
                raise ToolJournalCorruptionError(
                    "tool journal is poisoned; side effect outcome is unknown"
                )
            return document
        except ToolJournalCorruptionError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            self._quarantine_locked(path)
            poison = self._new_document(path.stem, poison_checkpoint_id)
            poison["poisoned"] = True
            self._write(path, poison)
            raise ToolJournalCorruptionError(
                "tool journal is corrupt; side effect outcome is unknown"
            ) from exc

    @staticmethod
    def _validate_document(document: Any, expected_attempt: str) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise ValueError("journal root must be an object")
        required = {
            "version": int,
            "attempt_id": str,
            "created_at": str,
            "updated_at": str,
            "completed": bool,
            "poisoned": bool,
            "entries": dict,
        }
        for key, expected_type in required.items():
            if not isinstance(document.get(key), expected_type):
                raise ValueError(f"invalid journal field {key!r}")
        if document["version"] != JOURNAL_VERSION:
            raise ValueError("unsupported journal version")
        if document["attempt_id"] != expected_attempt:
            raise ValueError("journal attempt does not match filename")
        validate_attempt_id(document["attempt_id"])
        checkpoint_id = document.get("checkpoint_id")
        if checkpoint_id is not None and (
            not isinstance(checkpoint_id, str)
            or not _CHECKPOINT_ID_PATTERN.fullmatch(checkpoint_id)
        ):
            raise ValueError("invalid journal checkpoint_id")
        if document.get("completed_at") is not None and not isinstance(
            document["completed_at"], str
        ):
            raise ValueError("invalid completed_at")
        for call_key, entry in document["entries"].items():
            if not isinstance(call_key, str) or not _CALL_KEY_PATTERN.fullmatch(call_key):
                raise ValueError("invalid journal call key")
            if not isinstance(entry, dict) or entry.get("status") not in {
                "pending",
                "completed",
            }:
                raise ValueError("invalid journal entry")
            if not isinstance(entry.get("tool"), str):
                raise ValueError("invalid journal tool")
            if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("args_digest", ""))):
                raise ValueError("invalid argument digest")
            if not isinstance(entry.get("ordinal"), int) or entry["ordinal"] < 0:
                raise ValueError("invalid journal ordinal")
            if entry["status"] == "completed" and not isinstance(
                entry.get("result"), str
            ):
                raise ValueError("completed journal entry has no result")
        return document

    def _assert_no_orphan_attempt_locked(
        self,
        attempt_id: str,
        checkpoint_id: str | None,
    ) -> None:
        """Block a new attempt while an older checkpoint-scoped run is unsealed."""
        if checkpoint_id is None:
            return
        if not _CHECKPOINT_ID_PATTERN.fullmatch(checkpoint_id):
            raise ValueError(f"Invalid checkpoint_id: {checkpoint_id!r}")
        for path in self.directory.glob("att_*.json"):
            if path.stem == attempt_id:
                continue
            document = self._read(path, allow_poison=True)
            if document is None:
                continue
            if document["poisoned"]:
                if document.get("checkpoint_id") == checkpoint_id:
                    raise ToolJournalCorruptionError(
                        "an earlier checkpoint journal is poisoned"
                    )
                continue
            if (
                document.get("checkpoint_id") == checkpoint_id
                and not document["completed"]
            ):
                raise ToolJournalStateError(
                    "an earlier checkpoint attempt has unresolved journal state"
                )

    @staticmethod
    def _write(path: Path, document: Mapping[str, Any]) -> None:
        payload = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        atomic_write_text(path, payload + "\n")

    def _quarantine_locked(self, path: Path) -> None:
        if not path.exists():
            return
        corrupt = self.directory / "corrupt"
        corrupt.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = corrupt / f"{path.stem}.{stamp}.{uuid4().hex[:8]}.json"
        try:
            os.replace(path, target)
        except OSError:
            return
        files = sorted(
            (item for item in corrupt.glob("*.json") if item.is_file()),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
        )
        for item in files[: -self.retention_limit]:
            item.unlink(missing_ok=True)

    def _prune_locked(self) -> None:
        completed: list[tuple[str, Path]] = []
        total = 0
        for path in self.directory.glob("att_*.json"):
            try:
                document = self._read(path)
            except ToolJournalCorruptionError:
                continue
            if document is None:
                continue
            total += 1
            if document["completed"]:
                completed.append((document["updated_at"], path))
        excess = total - self.retention_limit
        if excess <= 0:
            return
        # Pending attempts are never discarded: losing an uncertain tombstone
        # could turn a later resume into an unsafe replay.
        completed.sort(key=lambda item: (item[0], item[1].name))
        for _updated_at, path in completed[:excess]:
            path.unlink(missing_ok=True)
