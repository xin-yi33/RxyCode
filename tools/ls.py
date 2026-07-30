"""ls tool - List directory contents as a tree."""

import os
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class LsInput(BaseModel):
    path: str = Field(default=".", description="Directory path to list")
    ignore: list[str] = Field(default_factory=list, description="Patterns to ignore")


def run_ls(path: str = ".", ignore: list[str] = None) -> str:
    """List directory contents as a tree."""
    if ignore is None:
        ignore = []

    resolved_path = resolve_session_path(path)
    if not resolved_path.exists():
        return f"[error] Path not found: {resolved_path}"

    if resolved_path.is_file():
        return str(resolved_path)

    lines = []
    max_depth = 3
    max_entries = 200

    def should_ignore(name):
        for pattern in ignore:
            if pattern in name:
                return True
        return False

    def walk(dir_path, prefix="", depth=0):
        if depth > max_depth or len(lines) > max_entries:
            return
        try:
            entries = sorted(os.listdir(dir_path))
        except PermissionError:
            lines.append(f"{prefix}[permission denied]")
            return

        entries = [e for e in entries if not should_ignore(e)]

        for i, entry in enumerate(entries):
            full_path = os.path.join(dir_path, entry)
            is_last = i == len(entries) - 1
            connector = "+-- " if is_last else "|-- "

            if os.path.isdir(full_path):
                lines.append(f"{prefix}{connector}{entry}/")
                extension = "    " if is_last else "|   "
                walk(full_path, prefix + extension, depth + 1)
            else:
                size = os.path.getsize(full_path)
                size_str = _format_size(size)
                lines.append(f"{prefix}{connector}{entry} ({size_str})")

    walk(str(resolved_path))
    if len(lines) > max_entries:
        lines.append(f"... ({len(lines)} entries truncated)")
    return "\n".join(lines) if lines else "(empty directory)"


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size/1024:.1f}KB"
    else:
        return f"{size/(1024*1024):.1f}MB"


ls_tool = StructuredTool(
    name="ls",
    description="List directory contents as a tree structure. Shows files with sizes and directories with / suffix.",
    func=run_ls,
    args_schema=LsInput,
)
