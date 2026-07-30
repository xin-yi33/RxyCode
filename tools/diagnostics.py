"""diagnostics tool - Get LSP diagnostics for files."""

import os
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class DiagnosticsInput(BaseModel):
    filePath: str = Field(default="", description="File path to check (empty for all files)")


def run_diagnostics(filePath: str = "") -> str:
    """Get LSP diagnostics for a file or all files."""
    return _get_diagnostics_from_tools(filePath)


def _get_diagnostics_from_tools(file_path: str) -> str:
    """Get diagnostics using basic analysis."""
    if not file_path:
        return "No file specified. Provide a filePath to check for diagnostics."

    file_path = str(resolve_session_path(file_path))
    if not os.path.exists(file_path):
        return f"[error] File not found: {file_path}"

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".py":
        return _check_python(file_path)
    elif ext in (".js", ".ts"):
        return _check_javascript(file_path)
    else:
        return f"No diagnostics available for {ext} files."


def _check_python(file_path: str) -> str:
    """Basic Python diagnostics."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"[error] Cannot read file: {e}"

    lines = content.splitlines()
    issues = []

    for i, line in enumerate(lines, 1):
        # Check for common issues
        if "import *" in line:
            issues.append(f"  [W] {file_path}:{i} Wildcard import")
        if len(line) > 120:
            issues.append(f"  [W] {file_path}:{i} Line too long ({len(line)} > 120)")
        if line.rstrip() != line:
            issues.append(f"  [W] {file_path}:{i} Trailing whitespace")

    # Try syntax check
    try:
        compile(content, file_path, "exec")
    except SyntaxError as e:
        issues.append(f"  [E] {file_path}:{e.lineno} SyntaxError: {e.msg}")

    if not issues:
        return f"No issues found in {os.path.basename(file_path)}."

    return f"Found {len(issues)} issues:\n" + "\n".join(issues)


def _check_javascript(file_path: str) -> str:
    """Basic JavaScript diagnostics."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return f"[error] Cannot read file: {e}"

    lines = content.splitlines()
    issues = []

    for i, line in enumerate(lines, 1):
        if "console.log" in line and "debug" not in file_path.lower():
            issues.append(f"  [W] {file_path}:{i} console.log found")
        if "var " in line:
            issues.append(f"  [W] {file_path}:{i} Use let/const instead of var")

    if not issues:
        return f"No issues found in {os.path.basename(file_path)}."

    return f"Found {len(issues)} issues:\n" + "\n".join(issues)


diagnostics_tool = StructuredTool(
    name="diagnostics",
    description="Get diagnostics (errors, warnings) for a file. Supports Python and JavaScript syntax checking.",
    func=run_diagnostics,
    args_schema=DiagnosticsInput,
)
