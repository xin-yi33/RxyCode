"""Process lock, incomplete-task recovery, and instance policy."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

INCOMPLETE_STATUSES = frozenset(
    {"queued", "running", "approval", "submitted", "active"}
)
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out", "recovery_required"}
)
RECOVERY_REQUIRED = "recovery_required"


def default_lock_path() -> Path:
    override = os.environ.get("RXYCODE_APPSERVER_LOCK")
    if override:
        return Path(override)
    try:
        from config.settings import get_data_dir

        return get_data_dir() / "desktop" / "appserver.lock"
    except Exception:
        return Path(os.environ.get("TEMP", ".")) / "rxycode-appserver.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        still_active = 259
        return bool(ok) and int(exit_code.value) == still_active
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_pid_tree(pid: int) -> None:
    """Best-effort kill of *pid* and its descendants (Windows taskkill / POSIX group)."""
    if pid <= 0:
        return
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["taskkill", "/pid", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=creationflags,
        )
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


class InstanceLock:
    """Single-instance lock. Closing one client must not kill a shared server.

    Policy: one appserver process per data dir. A live lock holder is not
    preempted unless ``RXYCODE_APPSERVER_PREEMPT=1`` (Desktop stdio child).
    A stale lock (dead pid) is stolen.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_lock_path()
        self.held = False
        self.payload: dict[str, Any] = {}

    def acquire(self, *, pid: int | None = None) -> tuple[bool, str]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        mine = int(pid if pid is not None else os.getpid())
        if self.path.is_file():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            other = int(existing.get("pid") or 0)
            if other and other != mine and _pid_alive(other):
                self.payload = existing
                return False, f"appserver already running (pid {other})"
        payload = {
            "pid": mine,
            "started_at": time.time(),
            "policy": "single-instance-per-data-dir",
        }
        tmp = self.path.with_suffix(".lock.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)
        self.held = True
        self.payload = payload
        return True, "acquired"

    def preempt_and_acquire(self, *, pid: int | None = None) -> tuple[bool, str]:
        """Kill a live lock holder, then acquire. Used by Desktop stdio startup."""
        other = int(self.payload.get("pid") or 0)
        if other <= 0 and self.path.is_file():
            try:
                existing = json.loads(self.path.read_text(encoding="utf-8"))
                other = int(existing.get("pid") or 0)
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                other = 0
        mine = int(pid if pid is not None else os.getpid())
        if other and other != mine and _pid_alive(other):
            _terminate_pid_tree(other)
            deadline = time.time() + 8.0
            while _pid_alive(other) and time.time() < deadline:
                time.sleep(0.05)
        return self.acquire(pid=pid)

    def release(self) -> None:
        if not self.held:
            return
        try:
            if self.path.is_file():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if int(data.get("pid") or 0) == int(self.payload.get("pid") or 0):
                    self.path.unlink()
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        self.held = False


def mark_incomplete_recovery_required(store: Any) -> list[tuple[str, str]]:
    """Never forge completed. Incomplete persisted tasks become recovery_required."""
    changed: list[tuple[str, str]] = []
    if store is None or not getattr(store, "persistent", False):
        return changed
    for task in list(store.list(include_trashed=True)):
        status = str(task.get("status") or "")
        session_id = str(task.get("session_id") or "")
        if not session_id or status in TERMINAL_STATUSES:
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
        changed.append((session_id, status or "unknown"))
    return changed
