"""Thread-safe, atomic JSON persistence for application caches."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar


_logger = logging.getLogger(__name__)
_T = TypeVar("_T", dict, list)
_locks_guard = threading.Lock()
_path_locks: dict[str, threading.RLock] = {}


def path_lock(path: Path) -> threading.RLock:
    """Return the process-wide lock shared by all users of *path*."""
    key = os.path.normcase(str(Path(path).resolve()))
    with _locks_guard:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _path_locks[key] = lock
        return lock


def atomic_write_json(path: Path, payload: dict | list) -> None:
    """Atomically replace *path* with a fully flushed JSON document."""
    path = Path(path)
    with path_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                fd = -1
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_json_index(
    path: Path,
    expected_type: type[_T],
    empty_factory: Callable[[], _T],
    validator: Callable[[_T], bool] | None = None,
    sanitizer: Callable[[_T], _T] | None = None,
) -> _T:
    """Load an index, preserving and repairing malformed JSON documents.

    A sanitizer may retain valid entries from an otherwise structurally valid
    document. The original document is archived before the cleaned payload is
    installed, so field-level corruption remains diagnosable.
    """
    path = Path(path)
    with path_lock(path):
        if not path.exists():
            return empty_factory()

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, expected_type):
                raise ValueError(
                    f"expected {expected_type.__name__} root, got "
                    f"{type(payload).__name__}"
                )
            if validator is not None and not validator(payload):
                raise ValueError("index entries have an invalid structure")
            if sanitizer is not None:
                cleaned = sanitizer(payload)
                if cleaned != payload:
                    backup = path.with_name(
                        f"{path.name}.corrupt-{time.time_ns()}"
                    )
                    os.replace(path, backup)
                    _logger.warning(
                        "Preserved partially corrupt cache index %s as %s",
                        path,
                        backup,
                    )
                    atomic_write_json(path, cleaned)
                    return cleaned
            return payload
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            backup = path.with_name(f"{path.name}.corrupt-{time.time_ns()}")
            try:
                os.replace(path, backup)
                _logger.warning(
                    "Preserved corrupt cache index %s as %s: %s",
                    path,
                    backup,
                    exc,
                )
            except OSError as archive_error:
                _logger.warning(
                    "Could not preserve corrupt cache index %s: %s",
                    path,
                    archive_error,
                )
                return empty_factory()

            empty = empty_factory()
            try:
                atomic_write_json(path, empty)
            except OSError as repair_error:
                _logger.warning(
                    "Could not recreate cache index %s: %s", path, repair_error
                )
            return empty
        except OSError as exc:
            _logger.warning("Could not read cache index %s: %s", path, exc)
            return empty_factory()
