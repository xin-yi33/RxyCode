import asyncio
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from ..core.session_runtime import resolve_write_path
from ..utils.atomic_file import atomic_write_text


class WriteInput(BaseModel):
    filePath: str = Field(description="Absolute or session-relative file path")
    content: str = Field(description="Complete file content to write")


def _verify_syntax(path: Path, content: str) -> str:
    """Verify file syntax, return error message or empty string (meaning OK)."""
    suffix = path.suffix.lower()

    if suffix == '.py':
        try:
            compile(content, str(path), 'exec')
            return "OK"
        except SyntaxError as e:
            return f"SYNTAX_ERROR: line {e.lineno}: {e.msg}"

    if suffix in ('.js', '.jsx', '.ts', '.tsx'):
        # Simple bracket matching check
        opens = content.count('{') + content.count('(') + content.count('[')
        closes = content.count('}') + content.count(')') + content.count(']')
        if opens != closes:
            return f"BRACKET_MISMATCH: opens={opens}, closes={closes}"
        return "OK"

    return ""


def write_file(filePath: str, content: str) -> str:
    p = resolve_write_path(filePath)
    try:
        atomic_write_text(p, content)

        result_msg = f"[wrote {len(content)} bytes to {p}]"

        # Syntax verification for common code files
        if p.suffix in ('.py', '.js', '.ts', '.jsx', '.tsx'):
            syntax_result = _verify_syntax(p, content)
            if syntax_result:
                result_msg += f"\n[syntax check: {syntax_result}]"

        return result_msg
    except Exception as e:
        return f"[error writing file: {e}]"


async def write_file_async(filePath: str, content: str) -> str:
    # Yield once so a pending cancellation wins before the atomic commit.
    await asyncio.sleep(0)
    return write_file(filePath, content)


write_tool = StructuredTool.from_function(
    func=write_file,
    coroutine=write_file_async,
    name="write",
    description="Write content to a file. Creates parent directories if needed. Overwrites existing files.",
    args_schema=WriteInput,
)
