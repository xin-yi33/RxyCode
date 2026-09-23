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
                inside_root = True
            except (ValueError, OSError):
                inside_root = False
            if not inside_root:
                # 自救通道（2026-09-23）：启动目录不是项目时工作区会被降级
                # 到 ~/.rxycode/workspace，agent 需要能 cd 到真实项目目录
                # 继续工作，而不是报「被环境阻塞」。允许 cd 到项目目录
                # （.git/package.json 等标记）或用户 home 之下的目录；其余
                # 目标（如系统目录）仍然拒绝。cd 之后的写操作仍按新 cwd
                # 逐个过写路径闸。
                if not (_looks_like_project(target) or _is_under_home(target)):
                    return (
                        "[error: directory escapes execution.workspace_root: "
                        f"{target}]"
                    )
        resolved = set_working_directory(target)
        return f"Changed directory to: {resolved}"
    except Exception as e:
        return f"[error changing directory: {e}]"


_CD_PROJECT_MARKERS = (
    ".git",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "composer.json",
    ".rxycode-project",
)


def _looks_like_project(path: Path) -> bool:
    return any((path / marker).exists() for marker in _CD_PROJECT_MARKERS)


def _is_under_home(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path.home().resolve())
        return True
    except (ValueError, OSError):
        return False


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
