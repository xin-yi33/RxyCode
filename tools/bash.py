from __future__ import annotations

import asyncio
import hashlib
import platform
import subprocess
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import current_session_id
from ..utils.output_capture import write_text_artifact
from ..utils.shell import shell_executor
from .launch_intent import classify_shell_launch
from .open_file import open_file, open_file_async
from .secret_text import redact_secrets

_SPILL_SEEN: dict[str, set[str]] = {}
_SPILL_ARTIFACTS: dict[str, dict[str, frozenset[str]]] = {}
SPILL_PATH_PREFIX = "Full output saved to:"
SPILL_FAIL_MARKER = "[spill write failed; output truncated]"
DUPLICATE_SPILL = (
    "[duplicate tool output omitted: bash 输出与上次相同，为节省 token 已去重]"
)


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
#: 只按行数截断：超过 200 行时，上下文留首尾各 50 行，全文在 spill 文件里。
INLINE_LINE_LIMIT = 200
EDGE_LINES = 50

#: Hint appended when truncation happens (Tier1 style, see
#: memory/compressor.py:170-194 _middle_truncate).
TRUNCATION_HINT = "[输出已截断，可使用 grep/重定向到文件后分段读取继续]"

LAUNCHED_OK = (
    "[launched] OS accepted the start request. "
    "The GUI app's lifetime is not waited on; continue with the Final Answer."
)


def _redact_preview(text: str) -> str:
    """Redact model-visible previews only; raw local artifacts are untouched."""
    return redact_secrets(text)


def _capture_fingerprint(result: dict) -> str | None:
    base = result.get("capture_fingerprint")
    if not base:
        return None
    identity = f"{base}:{result.get('success')}:{result.get('exit_code')}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _artifact_paths(result: dict) -> list[str]:
    return [
        str(path)
        for path in (result.get("stdout_artifact"), result.get("stderr_artifact"))
        if path
    ]


def _is_duplicate_capture(result: dict, paths: list[str]) -> bool:
    if not paths or result.get("capture_error"):
        return False
    fingerprint = _capture_fingerprint(result)
    if not fingerprint:
        return False
    session = str(current_session_id() or "default")
    seen = _SPILL_SEEN.setdefault(session, set())
    artifacts = _SPILL_ARTIFACTS.setdefault(session, {})
    current_paths = frozenset(paths)
    if fingerprint in seen:
        # A repeated format call may be handed the exact same result object.
        # Do not unlink its canonical files; remove only newly captured copies.
        previous_paths = artifacts.get(fingerprint, frozenset())
        for path in current_paths - previous_paths:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        return True
    seen.add(fingerprint)
    artifacts[fingerprint] = current_paths
    return False


def _output_line_count(text: str, result: dict) -> int:
    line_count = int(result.get("stdout_line_count") or 0) + int(result.get("stderr_line_count") or 0)
    if line_count > 0:
        return line_count
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _output_is_long(text: str, result: dict) -> bool:
    return _output_line_count(text, result) > INLINE_LINE_LIMIT


def _edge_sections(text: str, result: dict) -> tuple[str, str, int]:
    head_lines = list(result.get("stdout_head_lines") or [])
    if not head_lines:
        head_lines = list(result.get("stderr_head_lines") or [])
    if result.get("stderr") and result.get("stderr_tail_lines"):
        tail_lines = list(result.get("stderr_tail_lines") or [])
    else:
        tail_lines = list(result.get("stdout_tail_lines") or [])
    total = int(result.get("stdout_line_count") or 0) + int(result.get("stderr_line_count") or 0)
    if head_lines or tail_lines:
        if result.get("stdout_redaction_hold") or result.get("stderr_redaction_hold"):
            tail_lines = []
        return (
            _redact_preview("\n".join(head_lines[:EDGE_LINES])),
            _redact_preview("\n".join(tail_lines[-EDGE_LINES:])),
            total,
        )
    lines = text.splitlines()
    head = "\n".join(lines[:EDGE_LINES])
    tail = "\n".join(lines[-EDGE_LINES:]) if len(lines) > EDGE_LINES else ""
    return head, tail, len(lines)


def _shape_long_output(text: str, result: dict, paths: list[str]) -> tuple[str, list[str]]:
    """Keep the first and last 50 lines in context and point at the full file."""
    if not text or not _output_is_long(text, result):
        return text, paths
    if result.get("capture_error"):
        return _truncate_output(text), []
    saved = list(paths)
    truncated = bool(result.get("stdout_truncated") or result.get("stderr_truncated"))
    if not saved and not truncated:
        try:
            saved = [str(write_text_artifact(text))]
        except OSError:
            return _truncate_output(text), paths
    if not saved:
        return _truncate_output(text), paths
    head, tail, total = _edge_sections(text, result)
    shown = (EDGE_LINES if head else 0) + (EDGE_LINES if tail and tail != head else 0)
    omitted = max(0, total - shown)
    parts = [head, f"... [省略 {omitted} 行，完整输出已保存至 {saved[0]}] ..."]
    if tail and tail != head:
        parts.append(tail)
    parts.append("如需完整输出，请使用 read 工具读取该文件")
    return "\n".join(part for part in parts if part), saved


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


def _refuse_blacklisted(command: str) -> str | None:
    from RxyCode.RxyCode1_1_0.core.safety.policy import hard_denied_shell_reason

    reason = hard_denied_shell_reason(command)
    if not reason:
        return None
    return f"[blocked: dangerous command rejected] {reason}。这条命令未执行。"


def run_bash(command: str, description: str = "", workdir: str = "", timeout: int = 1800) -> str:
    # 废弃代码（2026-09-20）：timeout: int = 60 / 120 不再作为 run_bash 默认值。
    refused = _refuse_blacklisted(command)
    if refused is not None:
        return refused
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
    refused = _refuse_blacklisted(command)
    if refused is not None:
        return refused
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
    # Deprecated 2026-10-11: _spill_large_output/_write_spill_file materialized
    # full streams before spilling. BoundedOutputCapture now streams previews/
    # artifacts; never route new calls through that old path. Keep this metadata-only.
    output = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    if stderr:
        output += ("\n" if output else "") + stderr
    if not result["success"]:
        output += f"\n[exit code: {result['exit_code']}]"
    paths = _artifact_paths(result)
    if _is_duplicate_capture(result, paths):
        return DUPLICATE_SPILL

    body, paths = _shape_long_output(_redact_preview(output), result, paths)
    if len(body) > MAX_OUTPUT_CHARS and "完整输出已保存至" not in body:
        body = _truncate_output(body)
    if result.get("capture_error"):
        capture_error = str(result["capture_error"])
        marker = (
            SPILL_FAIL_MARKER
            if "spill" in capture_error.lower()
            else "[output capture failed; preview may be incomplete]"
        )
        body += "\n" + marker
    path_lines = [f"{SPILL_PATH_PREFIX} {path}" for path in paths]
    if not result["success"]:
        # Tool recovery classifies the stable [error...] prefix.  Preserve the
        # command output and exit code, but do not let a failed shell probe be
        # mistaken for a successful empty/diagnostic result.
        msg = f"[error executing bash: {body or 'command failed'}]"
        if _looks_like_env_probe(command):
            msg += (
                " Do not retry pip/python/node probes. Call write for the "
                "user-named source files using the stdlib. Do not install "
                "Flask/FastAPI/Django unless the user named that framework."
            )
        if path_lines:
            msg += "\n" + "\n".join(path_lines)
        return msg
    if path_lines:
        return f"{body}\n" + "\n".join(path_lines) if body else "\n".join(path_lines)
    return body or "[no output]"


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
