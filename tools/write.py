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

    # 废弃代码（2026-10-23）：JS/TS 的括号计数近似检查已废弃。它把
    # ``const a = ;`` 判为 OK，也会把 TSX/JSX 里的合法括号结构误报。
    # 替代入口：core.post_write_diagnostics（真实 node --check / tsc）。
    # 保留函数签名（同步兼容入口）并返回空串，表示"此路径不判定"。
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


def post_write_report(
    path: Path,
    content: str,
    *,
    operation: str = "write",
) -> str:
    """Synchronous fallback: no longer the diagnostics implementation.

    废弃代码（2026-10-24）：本函数原先是同步 lint 报告（``_lint_python`` /
    ``_lint_javascript``）。统一写后诊断改为 ``async`` 入口
    ``post_write_report_async`` → ``core.post_write_diagnostics.diagnose``
    （真实 compile / node --check / tsc，且带内容指纹与诚实状态），因为
    ``await`` 无法出现在同步函数里。保留同步签名只作为兼容入口，返回空
    字符串表示"此路径不做诊断"；异步路径才是权威结果。
    """
    return ""


async def post_write_report_async(
    path: Path,
    content: str,
    *,
    operation: str = "write",
) -> str:
    """Check a file that was just saved and render the model-facing block.

    This is THE single diagnostics entry point: ``write``, ``edit`` and
    ``patch`` all call it after a successful save, so a file is never checked
    twice and never skipped by one path but not another.

    The write already happened before this runs.  A syntax error here does
    NOT turn the write into a failure, and a missing checker does not either.
    """
    from ..core.post_write_diagnostics import diagnose

    report = await diagnose(path, content, operation=operation, written=True)
    return report.render()


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
        # The synchronous path keeps the cheap Python syntax probe only; the full
        # post-write diagnostics run in ``write_file_async`` (they need await).
        syntax = _verify_syntax(p, content)
        if syntax:
            result_msg += f"\n[syntax check: {syntax}]"
        return result_msg
    except Exception as e:
        return f"[error writing file: {e}]"


async def write_file_async(filePath: str, content: str) -> str:
    # Yield once so a pending cancellation wins before the atomic commit.
    await asyncio.sleep(0)
    result = write_file(filePath, content)
    if result.startswith("[error"):
        return result
    # Write succeeded: attach the real diagnostic block (replacing the legacy
    # synchronous probe so the file is not checked twice).
    path = resolve_write_path(filePath)
    try:
        block = await post_write_report_async(path, content, operation="write")
    except Exception as exc:  # diagnostics must never fail the write
        block = f"\n[syntax check: unavailable — {type(exc).__name__}]"
    legacy = result.find("\n[syntax check:")
    if legacy != -1:
        result = result[:legacy]
    return result + block


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
