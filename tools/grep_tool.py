import re
import os
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class GrepInput(BaseModel):
    pattern: str = Field(description="Regex pattern to search for")
    path: str = Field(default="", description="Directory to search in")
    include: str = Field(default="", description="File pattern filter (e.g. *.py)")


def grep_files(pattern: str, path: str = "", include: str = "") -> str:
    root = resolve_session_path(path or ".")
    if not root.exists():
        return f"[error: path not found: {path}]"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"[error: invalid regex: {e}]"
    results = []
    max_results = 100

    # If path is a file, search in that file directly
    if root.is_file():
        try:
            with open(root, "r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        results.append(f"{root}:{i}: {line.rstrip()}")
                        if len(results) >= max_results:
                            return "\n".join(results) + f"\n[truncated at {max_results} matches]"
        except (PermissionError, OSError):
            return f"[error: cannot read file: {root}]"
        return "\n".join(results) if results else "[no matches found]"

    for dirpath, dirnames, filenames in os.walk(root):
        for fname in filenames:
            if include:
                from fnmatch import fnmatch
                if not fnmatch(fname, include):
                    continue
            fpath = Path(dirpath) / fname
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append(f"{fpath}:{i}: {line.rstrip()}")
                            if len(results) >= max_results:
                                return "\n".join(results) + f"\n[truncated at {max_results} matches]"
            except (PermissionError, OSError):
                continue

    return "\n".join(results) if results else "[no matches found]"


grep_tool = StructuredTool.from_function(
    func=grep_files,
    name="grep",
    description="Search file contents using regex. Returns matching lines with file:line format.",
    args_schema=GrepInput,
)
