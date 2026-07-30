"""Bounded, secret-safe, append-only trajectory event persistence.

The runtime integrations decide which lifecycle events to emit.  This module
only defines the durable transport contract: one sanitized JSON object per
line, safe concurrent appends, and corruption-tolerant ordered replay.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from ..config.settings import get_data_dir, load_config
    from .log_retention import prune_run_files
except ImportError:  # Support direct ``python -m core.trajectory`` imports.
    from config.settings import get_data_dir, load_config
    from core.log_retention import prune_run_files


REDACTED = "[REDACTED]"
MAX_STRING_CHARS = 4_096
MAX_COLLECTION_ITEMS = 100
MAX_DEPTH = 8
MAX_EVENT_BYTES = 64 * 1_024

_MIN_EVENT_BYTES = 1_024
_MAX_KEY_CHARS = 256
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_TOKEN_KEYS = frozenset(
    {
        "cachedtokens",
        "completiontokens",
        "contexttokens",
        "inputtokens",
        "outputtokens",
        "prompttokens",
        "tokencount",
        "tokenlimit",
        "tokenusage",
        "totaltokens",
    }
)
_INLINE_CREDENTIAL_RE = re.compile(
    r"(?i)(\b(?:api[\s_-]?key|apikey|access[\s_-]?token|refresh[\s_-]?token|"
    r"id[\s_-]?token|auth[\s_-]?token|client[\s_-]?secret|password|passwd)\b"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s,;\"'}\]]+)"
)
_AUTHORIZATION_RE = re.compile(
    r"(?i)(\bauthorization\b[\"']?\s*[:=]\s*[\"']?)"
    r"(?:(?:basic|bearer)\s+)?([^\s,;\"'}\]]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;\"'}\]]+")
_COMMON_SECRET_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{4,}|"
    r"github_pat_[A-Za-z0-9_]{4,}|gh[pousr]_[A-Za-z0-9_]{4,}|"
    r"xox[baprs]-[A-Za-z0-9-]{4,}|AKIA[A-Z0-9]{12,})"
)
_GLOBAL_FILE_LOCK = threading.RLock()


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized in _SAFE_TOKEN_KEYS:
        return False
    if any(
        marker in normalized
        for marker in (
            "apikey",
            "authorization",
            "credential",
            "password",
            "passwd",
            "secret",
            "setcookie",
        )
    ):
        return True
    return normalized == "token" or normalized.endswith(
        ("accesstoken", "authtoken", "idtoken", "refreshtoken")
    )


def _redact_text(value: str, max_chars: int = MAX_STRING_CHARS) -> str:
    """Redact common credential forms without ever retaining an unbounded value."""
    truncated_chars = max(0, len(value) - max_chars)
    bounded = value[:max_chars]
    bounded = _AUTHORIZATION_RE.sub(r"\1" + REDACTED, bounded)
    bounded = _INLINE_CREDENTIAL_RE.sub(r"\1" + REDACTED, bounded)
    bounded = _BEARER_RE.sub("Bearer " + REDACTED, bounded)
    bounded = _COMMON_SECRET_RE.sub(REDACTED, bounded)
    if truncated_chars:
        bounded += f"...[TRUNCATED {truncated_chars} chars]"
    return bounded


def _type_name(value: Any) -> str:
    raw_name = getattr(type(value), "__name__", "unknown")
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(raw_name))[:80] or "unknown"


def _mapping_items(value: Mapping[Any, Any]):
    try:
        return iter(value.items())
    except Exception:
        return iter(())


def _collection_length(value: Any) -> int | None:
    try:
        return len(value)
    except Exception:
        return None


def _normalize(
    value: Any,
    *,
    depth: int = 0,
    ancestors: set[int] | None = None,
) -> Any:
    """Convert arbitrary input to bounded JSON values without calling repr()."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[NON_FINITE_FLOAT]"
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Path):
        return _redact_text(os.fspath(value))
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _normalize(value.value, depth=depth, ancestors=ancestors)

    if depth >= MAX_DEPTH:
        return "[MAX_DEPTH]"

    ancestors = ancestors if ancestors is not None else set()
    identity = id(value)
    if identity in ancestors:
        return "[CYCLE]"

    if isinstance(value, Mapping):
        ancestors.add(identity)
        try:
            normalized: dict[str, Any] = {}
            consumed = 0
            for key, nested in _mapping_items(value):
                if consumed >= MAX_COLLECTION_ITEMS:
                    break
                if isinstance(key, str):
                    safe_key = _redact_text(key, _MAX_KEY_CHARS)
                else:
                    safe_key = f"<key:{_type_name(key)}>"
                normalized[safe_key] = (
                    REDACTED
                    if _is_sensitive_key(safe_key)
                    else _normalize(
                        nested,
                        depth=depth + 1,
                        ancestors=ancestors,
                    )
                )
                consumed += 1
            total = _collection_length(value)
            if total is not None and total > consumed:
                normalized["_truncated_items"] = total - consumed
            return normalized
        finally:
            ancestors.discard(identity)

    if isinstance(value, (list, tuple, set, frozenset)):
        ancestors.add(identity)
        try:
            items = []
            for index, nested in enumerate(value):
                if index >= MAX_COLLECTION_ITEMS:
                    break
                items.append(
                    _normalize(
                        nested,
                        depth=depth + 1,
                        ancestors=ancestors,
                    )
                )
            if isinstance(value, (set, frozenset)):
                items.sort(
                    key=lambda item: json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            total = _collection_length(value)
            if total is not None and total > len(items):
                items.append({"_truncated_items": total - len(items)})
            return items
        finally:
            ancestors.discard(identity)

    if is_dataclass(value) and not isinstance(value, type):
        ancestors.add(identity)
        try:
            data: dict[str, Any] = {}
            for index, field in enumerate(fields(value)):
                if index >= MAX_COLLECTION_ITEMS:
                    data["_truncated_items"] = len(fields(value)) - index
                    break
                try:
                    nested = getattr(value, field.name)
                except Exception:
                    nested = f"<unavailable:{_type_name(value)}>"
                data[field.name] = (
                    REDACTED
                    if _is_sensitive_key(field.name)
                    else _normalize(
                        nested,
                        depth=depth + 1,
                        ancestors=ancestors,
                    )
                )
            return data
        finally:
            ancestors.discard(identity)

    return f"<unserializable:{_type_name(value)}>"


def _encode_record(record: Mapping[str, Any]) -> bytes:
    return json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _fit_record(record: dict[str, Any], max_event_bytes: int) -> tuple[dict[str, Any], bytes]:
    encoded = _encode_record(record)
    if len(encoded) + 1 <= max_event_bytes:
        return record, encoded

    original_size = len(encoded) + 1
    preview_source = json.dumps(
        record["payload"],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )

    def candidate(preview_chars: int) -> tuple[dict[str, Any], bytes]:
        compact = dict(record)
        compact["payload"] = {
            "_event_truncated": True,
            "original_size_bytes": original_size,
            "preview": preview_source[:preview_chars],
        }
        return compact, _encode_record(compact)

    low = 0
    high = len(preview_source)
    best_record, best_encoded = candidate(0)
    while low <= high:
        middle = (low + high) // 2
        compact, compact_encoded = candidate(middle)
        if len(compact_encoded) + 1 <= max_event_bytes:
            best_record, best_encoded = compact, compact_encoded
            low = middle + 1
        else:
            high = middle - 1
    return best_record, best_encoded


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id must be a non-empty, filesystem-safe identifier")
    if run_id in {".", ".."} or _redact_text(run_id) != run_id:
        raise ValueError("run_id cannot contain a path segment or credential")
    return run_id


def _validate_event_type(event_type: str) -> str:
    if not isinstance(event_type, str) or not _EVENT_TYPE_RE.fullmatch(event_type):
        raise ValueError("event_type must be a non-empty structured identifier")
    if _redact_text(event_type) != event_type:
        raise ValueError("event_type cannot contain a credential")
    return event_type


def _is_replayable_event(event: Any, run_id: str) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("run_id") != run_id:
        return False
    if not isinstance(event.get("timestamp"), str):
        return False
    if not isinstance(event.get("event_type"), str):
        return False
    return "payload" in event


class TrajectoryLogger:
    """Append-only JSONL event logger scoped to one execution run."""

    def __init__(
        self,
        run_id: str,
        *,
        directory: str | Path | None = None,
        max_event_bytes: int = MAX_EVENT_BYTES,
        retention_runs: int | None = None,
        manage_retention: bool = True,
    ) -> None:
        self.run_id = _validate_run_id(run_id)
        if (
            not isinstance(max_event_bytes, int)
            or isinstance(max_event_bytes, bool)
            or not _MIN_EVENT_BYTES <= max_event_bytes <= MAX_EVENT_BYTES
        ):
            raise ValueError(
                f"max_event_bytes must be between {_MIN_EVENT_BYTES} and "
                f"{MAX_EVENT_BYTES}"
            )
        base = (
            Path(directory)
            if directory is not None
            else get_data_dir() / "logs" / "trajectories"
        )
        self.path = base / f"{self.run_id}.jsonl"
        self.max_event_bytes = max_event_bytes
        if manage_retention:
            if retention_runs is None:
                try:
                    retention_runs = int(
                        (load_config().get("observability") or {}).get(
                            "trajectory_retention_runs", 200
                        )
                    )
                except (TypeError, ValueError):
                    retention_runs = 200
            prune_run_files(
                base,
                keep_runs=max(1, retention_runs),
                protected=(self.path,),
            )

    def record(self, event_type: str, payload: Any) -> dict[str, Any] | None:
        """Sanitize and append one event; persistence errors remain non-fatal."""
        validated_type = _validate_event_type(event_type)
        try:
            normalized_payload = _normalize(payload)
        except Exception:
            # A hostile Mapping/Path implementation may raise while being
            # inspected.  Never stringify that exception: it may contain the
            # very credential this boundary is designed to keep off disk.
            normalized_payload = f"<unserializable:{_type_name(payload)}>"
        record = {
            "timestamp": _utc_timestamp(),
            "run_id": self.run_id,
            "event_type": validated_type,
            "payload": normalized_payload,
        }
        fitted, encoded = _fit_record(record, self.max_event_bytes)
        try:
            with _GLOBAL_FILE_LOCK:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("ab") as stream:
                    stream.write(encoded)
                    stream.write(b"\n")
                    stream.flush()
            return fitted
        except Exception:
            return None

    def _read_lines(self) -> list[bytes]:
        if not self.path.exists():
            return []
        lines: list[bytes] = []
        try:
            with _GLOBAL_FILE_LOCK, self.path.open("rb") as stream:
                while True:
                    line = stream.readline(self.max_event_bytes + 1)
                    if not line:
                        break
                    oversized = len(line) > self.max_event_bytes
                    complete = line.endswith(b"\n")
                    if oversized or not complete:
                        while line and not line.endswith(b"\n"):
                            line = stream.readline(self.max_event_bytes + 1)
                        if oversized:
                            continue
                    lines.append(line.rstrip(b"\r\n"))
        except Exception:
            return []
        return lines

    def read_events(self, *, event_type: str | None = None) -> list[dict[str, Any]]:
        """Read valid events in append order, silently skipping corrupt lines."""
        if event_type is not None:
            event_type = _validate_event_type(event_type)
        events: list[dict[str, Any]] = []
        for raw_line in self._read_lines():
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not _is_replayable_event(event, self.run_id):
                continue
            if event_type is not None and event["event_type"] != event_type:
                continue
            events.append(event)
        return events

    def replay(
        self,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        *,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Replay valid events in order and optionally dispatch each to a handler."""
        events = self.read_events(event_type=event_type)
        if handler is not None:
            for event in events:
                handler(event)
        return events


def read_trajectory(
    run_id: str,
    *,
    event_type: str | None = None,
    directory: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Read one run's valid trajectory events."""
    return TrajectoryLogger(
        run_id,
        directory=directory,
        manage_retention=False,
    ).read_events(
        event_type=event_type
    )


def replay_trajectory(
    run_id: str,
    handler: Callable[[dict[str, Any]], Any] | None = None,
    *,
    event_type: str | None = None,
    directory: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Replay one run's valid trajectory events in append order."""
    return TrajectoryLogger(
        run_id,
        directory=directory,
        manage_retention=False,
    ).replay(
        handler,
        event_type=event_type,
    )


__all__ = [
    "MAX_COLLECTION_ITEMS",
    "MAX_DEPTH",
    "MAX_EVENT_BYTES",
    "MAX_STRING_CHARS",
    "REDACTED",
    "TrajectoryLogger",
    "read_trajectory",
    "replay_trajectory",
]
