import json
from pathlib import Path
import re
import threading
from datetime import datetime
from typing import Optional

from RxyCode.RxyCode1_1_0.config.settings import get_data_dir, get_dated_data_dir
from RxyCode.RxyCode1_1_0.utils.atomic_file import atomic_write_text

_MEMORY_LOCK = threading.RLock()


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_session_id(session_id: str | None) -> str:
    value = "latest" if session_id is None else str(session_id).strip()
    if not _SESSION_ID_RE.fullmatch(value) or value in {".", ".."}:
        raise ValueError(
            "session_id must be 1-64 characters using letters, numbers, '.', '_' or '-'"
        )
    return value


def _sessions_dir() -> Path:
    d = get_dated_data_dir("sessions") / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_session_dir(session_id: str) -> Path | None:
    current = _sessions_dir() / session_id
    if current.exists():
        return current
    matches = sorted(
        (get_data_dir() / "sessions").glob(f"*/memory/{session_id}"),
        key=lambda item: item.parent.parent.name,
        reverse=True,
    )
    if matches:
        return matches[0]
    legacy = get_data_dir() / "memory" / "sessions" / session_id
    return legacy if legacy.exists() else None


def _projects_dir() -> Path:
    d = get_data_dir() / "memory" / "projects" / "global"
    d.mkdir(parents=True, exist_ok=True)
    return d


class LongTermMemory:
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = validate_session_id(session_id)
        existing_dir = _find_session_dir(self.session_id)
        self._session_dir = _sessions_dir() / self.session_id
        self._session_dir.mkdir(parents=True, exist_ok=True)
        existing_dir = existing_dir or self._session_dir
        self._context_file = self._session_dir / "context.md"
        self._history_file = self._session_dir / "history.json"
        self._existing_context_file = existing_dir / "context.md"
        self._existing_history_file = existing_dir / "history.json"
        self._global_file = _projects_dir() / "MEMORY.md"

    def _refresh_session_dir(self) -> None:
        current = _sessions_dir() / self.session_id
        current.mkdir(parents=True, exist_ok=True)
        if current != self._session_dir:
            self._session_dir = current
            self._context_file = current / "context.md"
            self._history_file = current / "history.json"

    def save_session_context(self, content: str):
        self._refresh_session_dir()
        atomic_write_text(self._context_file, content)

    def load_session_context(self) -> str:
        self._refresh_session_dir()
        source = self._context_file if self._context_file.exists() else self._existing_context_file
        if not source.exists():
            return ""
        with open(source, "r", encoding="utf-8") as f:
            return f.read()

    def append_session_context(self, content: str):
        with _MEMORY_LOCK:
            existing = self.load_session_context()
            atomic_write_text(self._context_file, existing + "\n\n" + content)

    def save_history(self, messages: list[dict]):
        self._refresh_session_dir()
        with _MEMORY_LOCK:
            atomic_write_text(
                self._history_file,
                json.dumps(messages, ensure_ascii=False, indent=2),
            )

    def load_history(self) -> list[dict]:
        self._refresh_session_dir()
        source = self._history_file if self._history_file.exists() else self._existing_history_file
        if not source.exists():
            return []
        try:
            with open(source, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def save_global_memory(self, content: str):
        with open(self._global_file, "w", encoding="utf-8") as f:
            f.write(content)

    def load_global_memory(self) -> str:
        if not self._global_file.exists():
            return ""
        with open(self._global_file, "r", encoding="utf-8") as f:
            return f.read()

    def append_error_log(self, task_id: str, error: str):
        """Append an error entry to the session error log (not conversation memory)."""
        error_file = self._session_dir / "errors.log"
        with open(error_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] Task {task_id}: {error}\n")

    def clear_session(self) -> int:
        """Remove this session's durable files from every dated and legacy root."""
        roots = list((get_data_dir() / "sessions").glob(f"*/memory/{self.session_id}"))
        roots.append(get_data_dir() / "memory" / "sessions" / self.session_id)
        removed = 0
        for root in roots:
            for name in ("context.md", "history.json", "errors.log", "auto_facts.md", "compressed.md"):
                path = root / name
                if path.is_file():
                    path.unlink()
                    removed += 1
            try:
                root.rmdir()
            except OSError:
                pass
        return removed

    def list_sessions(self) -> list[str]:
        sessions = {
            path.name
            for path in (get_data_dir() / "sessions").glob("*/memory/*")
            if path.is_dir()
        }
        legacy = get_data_dir() / "memory" / "sessions"
        if legacy.exists():
            sessions.update(path.name for path in legacy.iterdir() if path.is_dir())
        return sorted(sessions)

