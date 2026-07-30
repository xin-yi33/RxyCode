"""view tool - View file contents with line numbers."""

import os
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class ViewInput(BaseModel):
    filePath: str = Field(description="Path to the file to view")
    offset: int = Field(default=1, description="Line number to start from (1-indexed)")
    limit: int = Field(default=2000, description="Maximum number of lines to show")


def run_view(filePath: str, offset: int = 1, limit: int = 2000) -> str:
    """View file contents with line numbers."""
    file_path = str(resolve_session_path(filePath))

    if not os.path.exists(file_path):
        return f"[error] File not found: {file_path}"

    if os.path.isdir(file_path):
        return f"[error] Is a directory: {file_path}. Use ls tool instead."

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        return f"[error] Cannot read file: {e}"

    total = len(lines)
    start = max(0, offset - 1)
    end = min(total, start + limit)

    result_lines = []
    for i in range(start, end):
        line_num = i + 1
        content = lines[i].rstrip("\n")
        result_lines.append(f"{line_num:>6}: {content}")

    if start > 0:
        result_lines.insert(0, f"(showing lines {start+1}-{end} of {total})")
    if end < total:
        result_lines.append(f"({total - end} more lines)")

    return "\n".join(result_lines) if result_lines else "(empty file)"


view_tool = StructuredTool(
    name="view",
    description="View file contents with line numbers. Supports offset and limit for large files.",
    func=run_view,
    args_schema=ViewInput,
)
