from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class ReadInput(BaseModel):
    filePath: str = Field(description="Absolute or session-relative file path")
    offset: int = Field(default=1, description="Starting line number (1-indexed)")
    limit: int = Field(default=800, description="Max lines to read (default 800; use offset to page through larger files)")


def read_file(filePath: str, offset: int = 1, limit: int = 800) -> str:
    if any(ch in filePath for ch in ("*", "?", "[")):
        return (
            "[error: read 不支持通配符路径；请改用 glob 或 ls 工具定位文件后再 read 具体路径]"
        )
    p = resolve_session_path(filePath)
    if not p.exists():
        return f"[error: path not found: {filePath}]"
    if p.is_dir():
        return (
            f"[error: '{filePath}' 是目录，read 仅用于文件；请改用 ls 或 glob]"
        )
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        start = max(0, offset - 1)
        end = min(len(all_lines), start + limit)
        selected = all_lines[start:end]
        result = []
        for i, line in enumerate(selected, start=start + 1):
            result.append(f"{i}: {line.rstrip()}")
        return "\n".join(result)
    except Exception as e:
        return f"[error reading file: {e}]"


read_tool = StructuredTool.from_function(
    func=read_file,
    name="read",
    description=(
        "Read a file (not a directory). Relative paths use the session working directory. "
        "Returns content with line numbers. Reads at most `limit` lines (default 800); "
        "for larger files, page through with `offset`. "
        "Do not pass glob wildcards or directories — use glob/ls instead."
    ),
    args_schema=ReadInput,
)
