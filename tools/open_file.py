"""Open a previewable local file with the operating system's default app."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import current_turn_user_text, resolve_session_path


# ``open_file`` delegates to a host application, so its input contract must be
# narrower than "any existing file".  Keep this list explicit: adding a new
# type is a security decision because some extensions are executable on one of
# the supported operating systems.
PREVIEWABLE_EXTENSIONS = frozenset(
    {
        # Plain text and structured text.
        ".bib",
        ".cfg",
        ".conf",
        ".csv",
        ".json",
        ".jsonl",
        ".log",
        ".markdown",
        ".md",
        ".rst",
        ".tex",
        ".toml",
        ".tsv",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
        # Browser-rendered documents.
        ".css",
        ".htm",
        ".html",
        ".pdf",
        ".svg",
        # Office and OpenDocument files. Macro-enabled OOXML extensions are
        # deliberately absent.
        ".docx",
        ".odp",
        ".ods",
        ".odt",
        ".pptx",
        ".rtf",
        ".xlsx",
        # Raster images.
        ".avif",
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".tif",
        ".tiff",
        ".webp",
    }
)

# Check every extension segment, not only the final suffix.  This prevents an
# executable or script hidden behind an allowed suffix (for example
# ``payload.cmd.html``) from crossing the host-opener boundary.
EXECUTABLE_EXTENSIONS = frozenset(
    {
        ".apk",
        ".app",
        ".bat",
        ".bash",
        ".bin",
        ".cmd",
        ".com",
        ".command",
        ".cpl",
        ".deb",
        ".desktop",
        ".dll",
        ".dmg",
        ".exe",
        ".fish",
        ".hta",
        ".inf",
        ".jar",
        ".js",
        ".jse",
        ".lnk",
        ".lua",
        ".msi",
        ".msp",
        ".msc",
        ".php",
        ".pkg",
        ".pl",
        ".ps1",
        ".psd1",
        ".psm1",
        ".py",
        ".pyw",
        ".rb",
        ".reg",
        ".rpm",
        ".scr",
        ".sh",
        ".so",
        ".sys",
        ".url",
        ".vbe",
        ".vbs",
        ".wsf",
        ".wsh",
        ".zsh",
    }
)


_PREVIEW_EXT_ALT = "|".join(
    sorted(
        (re.escape(ext.lstrip(".")) for ext in PREVIEWABLE_EXTENSIONS),
        key=len,
        reverse=True,
    )
)
_PREVIEW_NAME_RE = re.compile(
    rf"(?<![\w.])((?:[\w.-]+[/\\])*[\w.-]+\.(?:{_PREVIEW_EXT_ALT}))",
    re.IGNORECASE,
)


class OpenFileInput(BaseModel):
    filePath: str = Field(
        description="Absolute or session-relative previewable file path"
    )


def named_preview_files(user_text: str) -> tuple[str, ...]:
    """Previewable filenames the user named this turn (basename-unique)."""
    found: list[str] = []
    seen: set[str] = set()
    for raw in _PREVIEW_NAME_RE.findall(user_text or ""):
        name = str(raw).replace("\\", "/")
        key = Path(name).name.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        found.append(name)
    return tuple(found)


def mismatched_open_error(file_path: str, user_text: str | None = None) -> str | None:
    """Refuse to preview a different file than the ones the user named."""
    text = current_turn_user_text() if user_text is None else user_text
    named = named_preview_files(text)
    requested = Path(str(file_path or "")).name
    if not named or not requested:
        return None
    allowed = {Path(name).name.casefold() for name in named}
    if requested.casefold() in allowed:
        return None
    named_list = ", ".join(named)
    return (
        f"[error: file not found or invalid path: refused to open {requested}; "
        f"user named {named_list}]"
    )


def _validate_previewable_file(file_path: str) -> tuple[Path | None, str | None]:
    """Resolve *file_path* and reject anything outside the preview contract."""
    try:
        path = resolve_session_path(file_path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"[error: file not found or invalid path: {exc}]"

    if not path.is_file():
        return None, f"[error: path is not a regular file: {path}]"

    name = path.name
    if (
        not name
        or name != name.rstrip(" .")
        or ":" in name
        or any(ord(character) < 32 for character in name)
    ):
        return None, f"[blocked: ambiguous file name is not previewable: {path}]"

    parts = name.casefold().split(".")
    if len(parts) < 2 or not parts[-1] or all(not part for part in parts[:-1]):
        return (
            None,
            f"[blocked: files without an approved extension cannot be opened: {path}]",
        )
    if any(not part or part != part.strip() for part in parts[1:-1]):
        return (
            None,
            f"[blocked: ambiguous multi-extension file cannot be opened: {path}]",
        )

    suffixes = tuple(f".{part}" for part in parts[1:] if part)
    dangerous_suffix = next(
        (suffix for suffix in suffixes if suffix in EXECUTABLE_EXTENSIONS),
        None,
    )
    if dangerous_suffix is not None:
        return (
            None,
            f"[blocked: executable or script extension {dangerous_suffix}: {path}]",
        )

    final_suffix = suffixes[-1]
    if final_suffix not in PREVIEWABLE_EXTENSIONS:
        return None, f"[blocked: unsupported preview extension {final_suffix}: {path}]"

    return path, None


def _windows_shell_path(path: Path | str) -> str:
    """Drop the ``\\\\?\\`` prefix so the shell does not treat the path as UNC."""
    raw = os.fspath(path)
    if raw.startswith("\\\\?\\UNC\\"):
        return "\\" + raw[7:]
    if raw.startswith("\\\\?\\"):
        return raw[4:]
    return raw


def _open_on_windows(path: Path) -> None:
    """Open with the default app without attaching it to this console.

    Pass ``start`` as separate argv tokens. A single ``/c`` string like
    ``start "" "C:\\…"`` is rewritten by list2cmdline into ``start \\"\\"``,
    and Windows then looks for a file named ``\\\\``. The dummy title must
    contain a space so ``start`` quotes it; an unquoted ``RxyCode`` matches
    ``rxycode.exe`` on PATH and never opens the file.
    """
    file_name = _windows_shell_path(path)
    argv = ["cmd.exe", "/c", "start", "RxyCode Open", file_name]
    detached = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    new_group = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(Path(file_name).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=detached | new_group,
        )
    except OSError as exc:
        os.startfile(file_name)


def open_file(filePath: str) -> str:
    mismatch = mismatched_open_error(filePath)
    if mismatch is not None:
        return mismatch
    path, error = _validate_previewable_file(filePath)
    if error is not None:
        return error
    if path is None:  # Defensive fail-closed guard for the validator contract.
        return "[error: file validation failed]"

    try:
        if sys.platform == "win32":
            _open_on_windows(path)
        else:
            command = (
                ["open", str(path)]
                if sys.platform == "darwin"
                else ["xdg-open", str(path)]
            )
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or "opener failed").strip()
                return f"[error opening file: {detail}]"
    except Exception as exc:
        return f"[error opening file: {exc}]"

    return f"[opened {path}]"


async def open_file_async(filePath: str) -> str:
    """Open a file without leaving a blocking opener process after cancel.

    Windows uses ``cmd /c start "RxyCode Open" <path>`` as separate argv
    tokens so list2cmdline cannot turn the path into ``\\\\``, and the
    quoted title cannot be mistaken for ``rxycode.exe`` on PATH. On POSIX the opener
    (open/xdg-open) runs through the controlled shell executor so a hung
    opener process tree is terminated on timeout (C2).  Note: a GUI app that
    the opener detaches and hands the document to is out of scope — the
    executor only guarantees the opener process tree itself is cleaned up."""
    mismatch = mismatched_open_error(filePath)
    if mismatch is not None:
        return mismatch
    path, error = _validate_previewable_file(filePath)
    if error is not None:
        return error
    if path is None:  # Defensive fail-closed guard for the validator contract.
        return "[error: file validation failed]"

    if sys.platform == "win32":
        try:
            _open_on_windows(path)
        except Exception as exc:
            return f"[error opening file: {exc}]"
        return f"[opened {path}]"

    from ..utils.shell import shell_executor

    command = (
        ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    )
    result = await shell_executor.execute_argv_async(command, timeout=10)
    if not result["success"]:
        detail = (result["stderr"] or "opener failed").strip()
        return f"[error opening file: {detail}]"
    return f"[opened {path}]"


open_file_tool = StructuredTool.from_function(
    func=open_file,
    coroutine=open_file_async,
    name="open_file",
    description=(
        "Open an existing previewable document, text file, image, HTML page, "
        "or PDF with the operating system's default application. When the "
        "user names a file, pass that exact path; do not ls and open a "
        "different existing file. A missing named file must return "
        "[error: file not found] — quote that error, do not claim success. "
        "Returns as soon as the OS accepts the launch; does not wait for "
        "the user to close the window. Use this instead of bash start/open/"
        "notepad/typora. Spawn failure is an error so you can retry, then "
        "continue with the Final Answer. Executables, scripts, shortcuts, "
        "directories, and unknown extensions are rejected."
    ),
    args_schema=OpenFileInput,
)
