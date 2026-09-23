from __future__ import annotations

import asyncio
import platform
import subprocess
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..utils.shell import shell_executor
from .launch_intent import classify_shell_launch
from .open_file import open_file, open_file_async


class BashInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    description: str = Field(default="", description="Short description of what this command does")
    workdir: str = Field(default="", description="Working directory for the command")
    timeout: int = Field(
        default=1800,
        description=(
            "Hard cap in seconds (default 1800). At 180/300/600s the runtime "
            "watches 3 seconds and reports both CPU samples. Sustained CPU "
            "or growing IO stays until this cap. One CPU spike with flat IO "
            "comes back to you: stop, retry, or wait. Not a broken interpreter."
        ),
        # 废弃代码（2026-09-22）：timeout 说明没有 3 秒观察，模型只看到一次读数。
        # description=(
        #     "Hard cap in seconds (default 1800). Runtime probes CPU/IO at "
        #     "180/300/600s and reports to you and the user. A busy search/"
        #     "traversal is not killed. An idle-CPU/IO job yields at the first "
        #     "idle checkpoint so you decide whether to stop or retry."
        # ),
    )
    # 废弃代码（2026-09-20）：schema 默认 60 / 120 会在编排器 1800s 预算内先被杀掉。
    # timeout: int = Field(default=60, ...)
    # timeout: int = Field(default=120, ...)


#: Max chars of combined stdout/stderr returned to the model. Longer output
#: is middle-truncated (head + tail kept) so a noisy command cannot blow up
#: the context window.
MAX_OUTPUT_CHARS = 30000

#: Hint appended when truncation happens (Tier1 style, see
#: memory/compressor.py:170-194 _middle_truncate).
TRUNCATION_HINT = "[输出已截断，可使用 grep/重定向到文件后分段读取继续]"

LAUNCHED_OK = (
    "[launched] OS accepted the start request. "
    "The GUI app's lifetime is not waited on; continue with the Final Answer."
)


def _truncate_output(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Middle-truncate ``text`` keeping ~half at the head and half at the tail.

    Adapted from memory/compressor.py:170-194 (Tier1 _middle_truncate).
    """
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    head = text[:keep]
    tail = text[-keep:]
    omitted = len(text) - len(head) - len(tail)
    return f"{head}\n{TRUNCATION_HINT} (omitted {omitted} chars)\n{tail}"


def _resolve_preview_path(path: str, workdir: str) -> str:
    if not workdir:
        return path
    candidate = Path(path)
    if candidate.is_absolute():
        return path
    return str(Path(workdir) / path)


def _windows_start_argv(command: str) -> list[str]:
    stripped = (command or "").strip()
    head = stripped.split(None, 1)[0].replace("\\", "/").rsplit("/", 1)[-1].casefold() if stripped else ""
    if head in {"start"}:
        return ["cmd.exe", "/s", "/c", stripped]
    return ["cmd.exe", "/s", "/c", f'start "" {stripped}']


def _detach_gui(command: str, workdir: str = "") -> str:
    """Spawn a GUI/launcher and return when the OS accepts it.

    废弃代码（2026-09-21）：以前打开类命令走 shell_executor.execute /
    process.communicate()，会等到 Word/Notepad/Typora 窗口关闭才返回。
    """
    cwd = workdir or None
    try:
        if platform.system() == "Windows":
            no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            detached = int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
            new_group = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
            proc = subprocess.Popen(
                _windows_start_argv(command),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                close_fds=True,
                creationflags=no_window | detached | new_group,
            )
        else:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        try:
            code = proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            return LAUNCHED_OK
        err = proc.stderr.read() if proc.stderr is not None else b""
        text = (err or b"").decode("utf-8", errors="replace").strip()
        if code not in (0, None):
            return f"[error launching command: {text or f'exit {code}'}]"
        return LAUNCHED_OK
    except OSError as exc:
        return f"[error launching command: {exc}]"


def _maybe_launch(command: str, workdir: str = "") -> str | None:
    plan = classify_shell_launch(command)
    if plan is None:
        return None
    if plan.kind == "open_preview" and plan.path:
        return open_file(_resolve_preview_path(plan.path, workdir))
    return _detach_gui(command, workdir)


async def _maybe_launch_async(command: str, workdir: str = "") -> str | None:
    plan = classify_shell_launch(command)
    if plan is None:
        return None
    if plan.kind == "open_preview" and plan.path:
        return await open_file_async(_resolve_preview_path(plan.path, workdir))
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _detach_gui, command, workdir)


def run_bash(command: str, description: str = "", workdir: str = "", timeout: int = 1800) -> str:
    # 废弃代码（2026-09-20）：timeout: int = 60 / 120 不再作为 run_bash 默认值。
    launched = _maybe_launch(command, workdir)
    if launched is not None:
        return launched
    # 委托给 ShellExecutor，自动探测 PowerShell/CMD/Bash
    result = shell_executor.execute(command, workdir, timeout)
    return _format_result(result, command)


async def run_bash_async(
    command: str,
    description: str = "",
    workdir: str = "",
    timeout: int = 1800,  # 废弃代码（2026-09-20）：旧默认 timeout: int = 60 / 120
) -> str:
    """Cancellable Bash implementation used by the async agent path."""
    launched = await _maybe_launch_async(command, workdir)
    if launched is not None:
        return launched
    result = await shell_executor.execute_async(command, workdir, timeout)
    return _format_result(result, command)


def _looks_like_env_probe(command: str) -> bool:
    lowered = (command or "").lower()
    if "pip install" in lowered or "npm install" in lowered:
        return False
    # 废弃代码（2026-09-22）：任意 python -c 都追加 Do not retry。
    # 用户的断言测试被说成「解释器卡死，不要再跑 python」。
    # return "python -c" in lowered or "python3 -c" in lowered
    return any(
        token in lowered
        for token in ("pip show", "--version", "where python", "where.exe python", "node -v", "npm -v")
    )


def _format_result(result: dict, command: str = "") -> str:
    output = result["stdout"]
    if result["stderr"]:
        output += ("\n" if output else "") + result["stderr"]
    if not result["success"]:
        output += f"\n[exit code: {result['exit_code']}]"
    output = _truncate_output(output)
    output = output.strip()
    if not result["success"]:
        # Tool recovery classifies the stable [error...] prefix.  Preserve the
        # command output and exit code, but do not let a failed shell probe be
        # mistaken for a successful empty/diagnostic result.
        msg = f"[error executing bash: {output or 'command failed'}]"
        if _looks_like_env_probe(command):
            msg += (
                " Do not retry pip/python/node probes. Call write for the "
                "user-named source files using the stdlib. Do not install "
                "Flask/FastAPI/Django unless the user named that framework."
            )
        return msg
    return output or "[no output]"


bash_tool = StructuredTool.from_function(
    func=run_bash,
    coroutine=run_bash_async,
    name="bash",
    description=(
        "Execute a shell command. Auto-detects PowerShell on Windows, "
        "falls back to cmd, uses bash on Unix. Returns stdout and stderr. "
        "Timeout is a hard cap in seconds (default 1800). "
        "Runtime probes CPU/IO at 180/300/600s, watches 3 seconds, and "
        "reports both samples to you. A busy search or a long compile/"
        "download/test is not killed. One CPU spike with flat IO is "
        "oscillation: you decide whether to stop, retry, or wait. "
        "Do not describe that as a broken Python install. "
        "On Windows: prefer PowerShell/cmd built-ins (dir, Get-ChildItem). "
        "Opening a visible new CMD window (e.g. `start cmd`) is a WRITE/DANGER "
        "action and requires user approval. To run a Python file and capture "
        "stdout on Windows, use `cmd /c python path\\to\\file.py` (not "
        "`start cmd`, which cannot return output to the agent). "
        "Do not use bash to open documents (Word/Notepad/Typora/start/"
        "xdg-open). Call open_file instead. Launch success is the OS "
        "accepting the start request, not the user closing the GUI. "
        "For routine work, run commands in the current shell instead of "
        "launching a new GUI window."
    ),
    args_schema=BashInput,
)
