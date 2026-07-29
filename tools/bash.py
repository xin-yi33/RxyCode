from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from ..utils.shell import shell_executor


class BashInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    description: str = Field(default="", description="Short description of what this command does")
    workdir: str = Field(default="", description="Working directory for the command")
    timeout: int = Field(default=60, description="Timeout in seconds")


#: Max chars of combined stdout/stderr returned to the model. Longer output
#: is middle-truncated (head + tail kept) so a noisy command cannot blow up
#: the context window.
MAX_OUTPUT_CHARS = 30000

#: Hint appended when truncation happens (Tier1 style, see
#: memory/compressor.py:170-194 _middle_truncate).
TRUNCATION_HINT = "[输出已截断，可使用 grep/重定向到文件后分段读取继续]"


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


def run_bash(command: str, description: str = "", workdir: str = "", timeout: int = 60) -> str:
    # 委托给 ShellExecutor，自动探测 PowerShell/CMD/Bash
    result = shell_executor.execute(command, workdir, timeout)
    return _format_result(result)


async def run_bash_async(
    command: str,
    description: str = "",
    workdir: str = "",
    timeout: int = 60,
) -> str:
    """Cancellable Bash implementation used by the async agent path."""
    result = await shell_executor.execute_async(command, workdir, timeout)
    return _format_result(result)


def _format_result(result: dict) -> str:
    output = result["stdout"]
    if result["stderr"]:
        output += ("\n" if output else "") + result["stderr"]
    if not result["success"]:
        output += f"\n[exit code: {result['exit_code']}]"
    output = _truncate_output(output)
    return output.strip() or "[no output]"


bash_tool = StructuredTool.from_function(
    func=run_bash,
    coroutine=run_bash_async,
    name="bash",
    description=(
        "Execute a shell command. Auto-detects PowerShell on Windows, "
        "falls back to cmd, uses bash on Unix. Returns stdout and stderr. "
        "Timeout is in seconds. "
        "On Windows: prefer PowerShell/cmd built-ins (dir, Get-ChildItem). "
        "Opening a visible new CMD window (e.g. `start cmd`) is a WRITE/DANGER "
        "action and requires user approval. To run a Python file and capture "
        "stdout on Windows, use `cmd /c python path\\to\\file.py` (not "
        "`start cmd`, which cannot return output to the agent). "
        "For routine work, run commands in the current shell instead of "
        "launching a new GUI window."
    ),
    args_schema=BashInput,
)
