"""Small atomic file-write primitives used by mutating tools."""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

# Windows: AV / indexer often holds the dest for a moment (WinError 5 / 32).
_WIN_RETRY_ERRORS = {5, 32}


def _normalize_script_line_endings(path: Path, content: str) -> str:
    """Use the native line ending required by Windows batch interpreters.

    ``cmd.exe`` treats LF-only ``.bat``/``.cmd`` files as malformed on the
    supported Windows runtime: command lines can lose their first character
    and the resulting failures trigger an unnecessary model recovery round.
    Normalize only batch scripts; all other file types retain the exact text
    supplied by the agent.
    """
    if path.suffix.lower() not in {".bat", ".cmd"}:
        return content
    return content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")


def _replace_with_retry(source: str, dest: str, attempts: int = 8) -> None:
    """os.replace, with Windows sharing/access retries."""
    delay = 0.02
    last: OSError | None = None
    for attempt in range(attempts):
        try:
            os.replace(source, dest)
            return
        except OSError as exc:
            last = exc
            winerr = getattr(exc, "winerror", None)
            if os.name != "nt" or winerr not in _WIN_RETRY_ERRORS:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
    if last is not None:
        raise last


def atomic_write_text(path: str | Path, content: str) -> None:
    """Durably replace ``path`` with UTF-8 text from the same directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = _normalize_script_line_endings(target, content)
    fd, temporary = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(temporary, str(target))
    finally:
        if os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass
