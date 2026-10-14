import ast
import asyncio
import json
import shutil
import subprocess
import sys
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


def _lint_python(path: Path) -> str:
    """Pyflakes 与语法级规则。未定义名字这类问题 compile 看不出来。"""
    try:
        proc = subprocess.run(
            [
                sys.executable, "-m", "ruff", "check",
                "--select", "F,E9",
                "--output-format", "json",
                "--no-cache",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "[lint] ruff 超时，仅完成语法检查"
    except OSError as exc:
        return f"[lint] 未能运行 ruff（{exc}），仅完成语法检查"
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if "No module named ruff" in stderr:
        return "[lint] 未能运行 ruff，仅完成语法检查"
    if not stdout:
        if proc.returncode == 0:
            return "[lint] 没有问题"
        return "[lint] ruff 未能完成，仅完成语法检查"
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return "[lint] ruff 输出无法解析，仅完成语法检查"
    items = [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    if not items:
        return "[lint] 没有问题"
    rendered: list[str] = []
    for item in items[:20]:
        loc = item.get("location") if isinstance(item.get("location"), dict) else {}
        row = loc.get("row")
        col = loc.get("column")
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        where = f"第{row}行" if row else "未知行"
        if col:
            where += f"第{col}列"
        rendered.append(f"- {where}：{code} {message}".rstrip())
    extra = f"\n- …还有 {len(items) - 20} 条" if len(items) > 20 else ""
    return "[lint]\n" + "\n".join(rendered) + extra


def _lint_javascript(path: Path) -> str:
    node = shutil.which("node")
    if not node:
        return "[lint] 没有 node，仅完成括号检查"
    try:
        proc = subprocess.run(
            [node, "--check", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return "[lint] node --check 超时，仅完成括号检查"
    except OSError as exc:
        return f"[lint] 未能运行 node（{exc}），仅完成括号检查"
    if proc.returncode == 0:
        return "[lint] 没有语法问题"
    text = proc.stderr or proc.stdout or ""
    line_no = ""
    for raw in text.splitlines():
        if raw.startswith(str(path)) and ":" in raw:
            tail = raw.rsplit(":", 1)[-1].strip()
            if tail.isdigit():
                line_no = tail
                break
    message = ""
    for raw in text.splitlines():
        if raw.startswith("SyntaxError:"):
            message = raw.split(":", 1)[1].strip()
            break
    if not message:
        message = "语法错误"
    where = f"第{line_no}行：" if line_no else ""
    return f"[lint]\n- {where}SyntaxError {message}"


def post_write_report(path: Path, content: str | None = None) -> str:
    """写入之后的检查。语法和静态问题附在同一次工具结果里。"""
    suffix = path.suffix.lower()
    if suffix not in {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        return ""
    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"\n[lint] 无法读取已写入文件: {exc}"
    lines: list[str] = []
    syntax = _verify_syntax(path, content)
    if syntax:
        lines.append(f"[syntax check: {syntax}]")
    if suffix == ".py":
        lines.append(_lint_python(path))
    elif suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        lines.append(_lint_javascript(path))
    else:
        lines.append("[lint] 没有适用于 TypeScript 的检查器，仅完成括号检查")
    return "\n" + "\n".join(lines)


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
        result_msg += post_write_report(p, content)
        return result_msg
    except Exception as e:
        return f"[error writing file: {e}]"


async def write_file_async(filePath: str, content: str) -> str:
    # Yield once so a pending cancellation wins before the atomic commit.
    await asyncio.sleep(0)
    return write_file(filePath, content)


# 兼容入口（2026-10-13）：不再注册独立 write schema。模型使用 edit 的
# write operation；write_file 仍是它调用的完整写入实现，旧导入保留。
write_tool = StructuredTool.from_function(
    func=write_file,
    coroutine=write_file_async,
    name="write",
    description=(
        "Write content to a file. Creates parent directories if needed. "
        "Overwrites existing files. Python and JavaScript results include "
        "syntax and linter findings for the next turn."
    ),
    args_schema=WriteInput,
)
