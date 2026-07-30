from pathlib import Path
import asyncio
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class ChangeDirectoryInput(BaseModel):
    path: str = Field(description="Path to change to (absolute or relative)")


def change_directory(path: str) -> str:
    from ..config.settings import load_config
    from ..core.session_runtime import (
        initial_working_directory,
        resolve_session_path,
        set_working_directory,
    )

    target = resolve_session_path(path)
    if not target.exists():
        return f"[error: path not found: {path}]"
    if not target.is_dir():
        return f"[error: not a directory: {path}]"
    try:
        execution = (load_config() or {}).get("execution") or {}
        mode = str(execution.get("sandbox_mode", "workspace") or "workspace")
        root_value = execution.get("workspace_root", ".") or "."
        workspace_root = Path(root_value).expanduser()
        if not workspace_root.is_absolute():
            workspace_root = initial_working_directory() / workspace_root
        workspace_root = workspace_root.resolve()
        if mode in {"workspace", "docker"}:
            try:
                target.relative_to(workspace_root)
            except (ValueError, OSError):
                return (
                    "[error: directory escapes execution.workspace_root: "
                    f"{target}]"
                )
        resolved = set_working_directory(target)
        return f"Changed directory to: {resolved}"
    except Exception as e:
        return f"[error changing directory: {e}]"


async def change_directory_async(path: str) -> str:
    await asyncio.sleep(0)
    return change_directory(path)


change_directory_tool = StructuredTool(
    name="cd",
    description="Change the current working directory. Parameter: path (required). Also available as 'change_directory'.",
    func=change_directory,
    coroutine=change_directory_async,
    args_schema=ChangeDirectoryInput,
)
