import glob as glob_mod
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class GlobInput(BaseModel):
    pattern: str = Field(description="Glob pattern to match files (e.g. **/*.py)")
    path: str = Field(default="", description="Directory to search in (default: current dir)")


def glob_files(pattern: str, path: str = "") -> str:
    root = resolve_session_path(path or ".")
    pattern_path = Path(pattern).expanduser()
    full_pattern = str(
        pattern_path if pattern_path.is_absolute() else root / pattern_path
    )
    matches = sorted(glob_mod.glob(full_pattern, recursive=True))
    if not matches:
        return "[no matches found]"
    return "\n".join(matches)


glob_tool = StructuredTool.from_function(
    func=glob_files,
    name="glob",
    description="Find files by glob pattern. Returns matching file paths sorted by name.",
    args_schema=GlobInput,
)
