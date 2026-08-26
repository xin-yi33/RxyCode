import ast
import asyncio
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from ..core.session_runtime import resolve_write_path
from ..utils.atomic_file import atomic_write_text

#: Testers stack combo cases until named pytest goes red. Cap keeps the
#: named file to the prompt behaviors (H4 asks for at least 6; LRU max 3).
_TEST_FUNCTION_CAP = 16
_TEST_FUNCTION_CAP_BY_NAME: dict[str, int] = {
    "test_lru_cache.py": 3,
    "test_lru_warmup.py": 3,
    "test_calc.py": 24,
}


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


def _count_test_functions(content: str) -> int | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def write_file(filePath: str, content: str) -> str:
    p = resolve_write_path(filePath)
    parts = {part.lower() for part in p.parts}
    if p.suffix == ".py" and "tests" not in parts:
        lowered = p.name.lower()
        if (
            lowered.startswith("test_")
            or lowered in {"test.py", "verify.py"}
            or lowered.startswith(
                (
                    "verify_",
                    "create_",
                    "_gen",
                    "_run",
                    "quick_test",
                    "run_test",
                    "_min_test",
                    "_quick_test",
                )
            )
            or (lowered.startswith("_") and "test" in lowered)
            or lowered.endswith("_test.py")
            or lowered == "smoke_test.py"
        ):
            return (
                f"[error writing file: {p.name} belongs under tests/, "
                "not the workspace root. File not written.]"
            )
    if p.suffix == ".py" and (
        p.name.startswith("test_") or "tests" in parts
    ):
        n = _count_test_functions(content)
        cap = _TEST_FUNCTION_CAP_BY_NAME.get(p.name, _TEST_FUNCTION_CAP)
        if n is not None and n > cap:
            return (
                f"[error writing file: {p.name} has {n} test_ functions; "
                f"keep at most {cap} covering the named "
                "behaviors. File not written.]"
            )
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
