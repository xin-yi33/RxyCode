"""Session-local execution context shared by tools without process-global CWD."""

from __future__ import annotations

import json
import os
import threading
from contextvars import ContextVar, Token
from pathlib import Path

from ..config.settings import get_data_dir, get_dated_data_dir, get_output_dir
from ..memory.long_term import validate_session_id
from ..utils.atomic_file import atomic_write_text


_ACTIVE_SESSION_ID: ContextVar[str] = ContextVar(
    "rxycode_active_session_id",
    default="latest",
)
_TURN_USER_TEXT: ContextVar[str] = ContextVar(
    "rxycode_turn_user_text",
    default="",
)
_SESSION_CWDS: dict[tuple[str, str], Path] = {}
_SESSION_LOCK = threading.RLock()


def initial_working_directory() -> Path:
    # This remains the process launch/test harness directory because the cd
    # tool never mutates process-global state.
    return Path.cwd().resolve()


def current_session_id() -> str:
    return validate_session_id(_ACTIVE_SESSION_ID.get())


def bind_session(session_id: str) -> Token:
    """Bind a validated session to the current async/thread context."""
    return _ACTIVE_SESSION_ID.set(validate_session_id(session_id))


def reset_session_binding(token: Token) -> None:
    _ACTIVE_SESSION_ID.reset(token)


def bind_turn_user_text(text: str) -> Token:
    """Bind this turn's user prompt so tools can pin named files."""
    return _TURN_USER_TEXT.set(text or "")


def reset_turn_user_text(token: Token) -> None:
    _TURN_USER_TEXT.reset(token)


def current_turn_user_text() -> str:
    return _TURN_USER_TEXT.get() or ""


def _state_path(session_id: str) -> Path:
    return get_dated_data_dir("sessions") / "runtime" / f"{session_id}.json"


def _legacy_state_path(session_id: str) -> Path:
    return get_data_dir() / "runtime_sessions" / f"{session_id}.json"


def _project_path(session_id: str) -> Path:
    return get_dated_data_dir("projects") / f"{session_id}.json"


def _find_state_path(session_id: str) -> Path:
    current = _state_path(session_id)
    if current.exists():
        return current
    dated_root = get_data_dir() / "sessions"
    if dated_root.exists():
        matches = sorted(
            dated_root.glob(f"*/runtime/{session_id}.json"),
            key=lambda item: item.parent.parent.name,
            reverse=True,
        )
        if matches:
            return matches[0]
    return _legacy_state_path(session_id)


def _cache_key(session_id: str) -> tuple[str, str]:
    return str(get_data_dir().resolve()), session_id


def _load_working_directory(session_id: str) -> Path | None:
    path = _find_state_path(session_id)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        candidate = Path(str(document.get("working_directory") or "")).resolve()
        if candidate.exists() and candidate.is_dir():
            return candidate
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return None


def current_working_directory(default: str | Path | None = None) -> Path:
    """Return the active session's cwd, restoring it from disk when needed."""
    session_id = current_session_id()
    cache_key = _cache_key(session_id)
    with _SESSION_LOCK:
        cached = _SESSION_CWDS.get(cache_key)
        if cached is not None and cached.exists() and cached.is_dir():
            return cached
        restored = _load_working_directory(session_id)
        if restored is not None:
            _SESSION_CWDS[cache_key] = restored
            return restored
    fallback = (
        Path(default).resolve()
        if default is not None
        else initial_working_directory()
    )
    return fallback


def resolve_session_path(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    workspace_path = (current_working_directory() / path).resolve()
    if workspace_path.exists():
        return workspace_path
    output_path = (get_output_dir() / path).resolve()
    if output_path.exists():
        return output_path
    output_root = get_data_dir() / "output"
    if output_root.exists():
        matches = sorted(
            output_root.glob(f"*/{path.as_posix()}"),
            key=lambda item: item.parent.parts,
            reverse=True,
        )
        if matches:
            return matches[0].resolve()
    return workspace_path


def _strip_redundant_output_prefix(relative: Path, output_dir: Path) -> Path:
    """Drop repeated ``output[/date]`` prefixes when ``output_dir`` already includes them.

    Models often pass ``output/2026-07-28/file.html`` while ``get_output_dir()`` is
    already ``.../output/2026-07-28``. Without stripping, writes land in a nested
    ``.../output/2026-07-28/output/2026-07-28/file.html`` and evidence checks fail.
    """
    parts = list(relative.parts)
    if not parts:
        return relative

    out_parts = list(output_dir.parts)
    # Strip leading "output" (+ optional date matching output_dir.name)
    while parts and parts[0].lower() == "output":
        parts = parts[1:]
        if parts and out_parts and parts[0] == output_dir.name:
            parts = parts[1:]
        elif (
            parts
            and len(out_parts) >= 2
            and out_parts[-1] == parts[0]
            and out_parts[-2].lower() == "output"
        ):
            parts = parts[1:]

    # If relative starts with the dated folder name already used by output_dir
    if parts and parts[0] == output_dir.name and out_parts and out_parts[-1] == output_dir.name:
        parts = parts[1:]

    return Path(*parts) if parts else Path(".")


def resolve_write_path(value: str | os.PathLike[str]) -> Path:
    """Resolve writes to the selected workspace, preserving CLI output fallback."""
    path = Path(value).expanduser()

    # Write resolution deliberately differs from read resolution.  Reads may
    # find a historical artifact in ``output/<date>/`` for backwards
    # compatibility, but a new relative write named ``cache.py`` must never
    # be hijacked by an unrelated historical ``output/.../cache.py``.
    if (
        not path.is_absolute()
        and (not path.parts or path.parts[0].lower() != "output")
    ):
        return (current_working_directory() / path).resolve()

    session_path = resolve_session_path(path)
    if session_path.exists():
        return session_path

    # An absolute path is an explicit caller decision.  Keep it even when its
    # parent does not exist: the write tool creates parent directories, and
    # redirecting it to the dated output directory makes the tool report a
    # successful write that later workspace-scoped reads cannot find.
    if path.is_absolute():
        return path.resolve()

    output_dir = get_output_dir().resolve()
    try:
        session_path.relative_to(output_dir)
        return session_path
    except ValueError:
        pass

    workspace = current_working_directory().resolve()
    try:
        relative = session_path.relative_to(workspace)
    except ValueError:
        # Also try relative to data/output root when model passed output/...
        relative = Path(*path.parts) if not path.is_absolute() else Path(session_path.name)

    relative = _strip_redundant_output_prefix(relative, output_dir)
    if str(relative) in ("", "."):
        relative = Path(session_path.name)
    return (output_dir / relative).resolve()


def set_working_directory(path: str | Path, *, persist: bool = True) -> Path:
    """Bind the active session's cwd without calling os.chdir().

    Disk persist is skipped when the RAM cache already matches, or when
    ``persist=False`` (Session.prompt thinking-TTFT path). Worker bootstrap
    still persists once before the user clock starts.
    """
    session_id = current_session_id()
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise ValueError(f"working directory is not a directory: {candidate}")
    cache_key = _cache_key(session_id)
    with _SESSION_LOCK:
        cached = _SESSION_CWDS.get(cache_key)
        if cached == candidate:
            if persist:
                return candidate
            _SESSION_CWDS[cache_key] = candidate
            return candidate
        _SESSION_CWDS[cache_key] = candidate
        if not persist:
            return candidate
        state_path = _state_path(session_id)
        project_path = _project_path(session_id)
        project_document = {
            "session_id": session_id,
            "working_directory": str(candidate),
        }
        session_document = {
            **project_document,
            "project_file": str(project_path),
        }
        project_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_text(
                project_path,
                json.dumps(project_document, ensure_ascii=False, separators=(",", ":")),
            )
            atomic_write_text(
                state_path,
                json.dumps(session_document, ensure_ascii=False, separators=(",", ":")),
            )
        except OSError:
            # Persist must not fail the first user turn (Windows WinError 5).
            pass
    return candidate


def clear_session_runtime(session_id: str) -> int:
    """Clear one session's persisted execution and project context."""
    resolved = validate_session_id(session_id)
    state_paths = set((get_data_dir() / "sessions").glob(f"*/runtime/{resolved}.json"))
    state_paths.add(_legacy_state_path(resolved))
    project_paths = set((get_data_dir() / "projects").glob(f"*/{resolved}.json"))
    existing = [path for path in (*state_paths, *project_paths) if path.exists()]
    with _SESSION_LOCK:
        for cache_key in [key for key in _SESSION_CWDS if key[1] == resolved]:
            _SESSION_CWDS.pop(cache_key, None)
        for path in existing:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return int(bool(existing) and all(not path.exists() for path in existing))


__all__ = [
    "bind_session",
    "bind_turn_user_text",
    "clear_session_runtime",
    "current_session_id",
    "current_turn_user_text",
    "current_working_directory",
    "initial_working_directory",
    "reset_session_binding",
    "reset_turn_user_text",
    "resolve_session_path",
    "resolve_write_path",
    "set_working_directory",
]
