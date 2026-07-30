"""format tool - Auto-format code files.

Automatically formats code in Python (black/autopep8) and JavaScript/TypeScript
(prettier) files. Falls back gracefully when formatters are not installed.
"""

import os
import shutil
import subprocess
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path


class FormatInput(BaseModel):
    filePath: str = Field(
        default="",
        description="Path to the file to format (required)"
    )
    tool: str = Field(
        default="auto",
        description="Formatter tool: 'auto' (detect from extension), 'black', 'autopep8', 'prettier', 'ruff'"
    )
    checkOnly: bool = Field(
        default=False,
        description="If True, only check formatting without modifying"
    )


def _run_formatter(cmd: list[str], file_path: str) -> str:
    """Run a formatter command and return output."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\n{result.stderr.strip()}"
        if result.returncode != 0 and not output.strip():
            output = f"[formatter exited with code {result.returncode}]"
        return output.strip() or "File formatted successfully."
    except FileNotFoundError:
        return None  # formatter not installed
    except subprocess.TimeoutExpired:
        return "[error: formatter timed out (30s)]"
    except Exception as e:
        return f"[error: {e}]"


def _detect_formatter(file_path: str) -> tuple[str, list[str]]:
    """Detect the appropriate formatter based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".py",):
        # Prefer ruff, then black, then autopep8
        for formatter, cmd in [
            ("ruff", ["ruff", "format"]),
            ("black", ["black", "--quiet"]),
            ("autopep8", ["autopep8", "--in-place", "--aggressive"]),
        ]:
            if _run_formatter([formatter, "--version"], file_path) is not None:
                return formatter, cmd
        return "black", ["black", "--quiet"]  # assume available

    elif ext in (".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".html", ".md", ".yaml", ".yml"):
        return "prettier", ["npx", "--yes", "prettier", "--write"]

    elif ext in (".rs",):
        return "rustfmt", ["rustfmt"]

    elif ext in (".go",):
        return "gofmt", ["gofmt", "-w"]

    elif ext in (".java",):
        return "google-java-format", ["google-java-format", "--replace"]

    else:
        return None, []


def run_format(filePath: str = "", tool: str = "auto", checkOnly: bool = False) -> str:
    """Format a code file using the best available formatter."""
    if not filePath:
        return "[error: filePath is required]"

    file_path = str(resolve_session_path(filePath))
    if not os.path.isfile(file_path):
        return f"[error: file not found: {filePath}]"

    # Check file size
    size = os.path.getsize(file_path)
    if size > 1024 * 1024:  # 1MB
        return "[error: file too large (>1MB)]"

    if tool == "auto":
        formatter_name, cmd_base = _detect_formatter(file_path)
        if formatter_name is None:
            ext = os.path.splitext(file_path)[1]
            return f"[error: no formatter found for '{ext}' files. Supported: .py, .js, .ts, .jsx, .tsx, .json, .css, .scss, .html, .md, .yaml, .rs, .go, .java]"
    else:
        formatter_name = tool
        if tool == "black":
            cmd_base = ["black", "--quiet"]
        elif tool == "autopep8":
            cmd_base = ["autopep8", "--in-place", "--aggressive"]
        elif tool == "prettier":
            cmd_base = ["npx", "--yes", "prettier", "--write"]
        elif tool == "ruff":
            cmd_base = ["ruff", "format"]
        else:
            return f"[error: unknown formatter '{tool}'. Supported: auto, black, autopep8, prettier, ruff]"

    if checkOnly:
        # For check-only, use diff-based check for most formatters
        if formatter_name == "black":
            result = _run_formatter(["black", "--check", "--quiet", file_path], file_path)
            if result and "would be reformatted" in result:
                return "File needs formatting."
            return "File is properly formatted."
        elif formatter_name == "ruff":
            result = _run_formatter(["ruff", "format", "--check", "--quiet", file_path], file_path)
            if result and result != "File formatted successfully.":
                return "File needs formatting."
            return "File is properly formatted."
        elif formatter_name == "prettier":
            result = _run_formatter(cmd_base + ["--check", file_path], file_path)
            if result and "would be reformatted" in result.lower():
                return "File needs formatting."
            return "File is properly formatted."
        else:
            # For other formatters, just report check result
            return "Check result unavailable for this formatter."

    # Run formatter
    cmd = cmd_base + [file_path]
    result = _run_formatter(cmd, file_path)

    if result is None:
        # Formatter not found
        if formatter_name == "black":
            install_hint = "pip install black"
        elif formatter_name == "ruff":
            install_hint = "pip install ruff"
        elif formatter_name == "autopep8":
            install_hint = "pip install autopep8"
        elif formatter_name == "prettier":
            install_hint = "npm install -g prettier"
        else:
            install_hint = f"install {formatter_name}"
        return f"[error: {formatter_name} not found. Install with: {install_hint}]"

    return result


async def run_format_async(
    filePath: str = "", tool: str = "auto", checkOnly: bool = False
) -> str:
    """Cancellable formatter execution for the async agent path."""
    from ..utils.shell import shell_executor

    if not filePath:
        return "[error: filePath is required]"
    file_path = str(resolve_session_path(filePath))
    if not os.path.isfile(file_path):
        return f"[error: file not found: {filePath}]"
    if os.path.getsize(file_path) > 1024 * 1024:
        return "[error: file too large (>1MB)]"

    formatter_name = tool
    if tool == "auto":
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".py":
            formatter_name = next(
                (name for name in ("ruff", "black", "autopep8") if shutil.which(name)),
                "",
            )
        elif ext in {".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".html", ".md", ".yaml", ".yml"}:
            formatter_name = "prettier" if shutil.which("npx") else ""
        elif ext == ".rs":
            formatter_name = "rustfmt" if shutil.which("rustfmt") else ""
        elif ext == ".go":
            formatter_name = "gofmt" if shutil.which("gofmt") else ""
        elif ext == ".java":
            formatter_name = "google-java-format" if shutil.which("google-java-format") else ""
        else:
            return f"[error: no formatter found for '{ext}' files]"

    commands = {
        "black": ["black", "--quiet"],
        "ruff": ["ruff", "format"],
        "autopep8": ["autopep8", "--in-place", "--aggressive"],
        "prettier": ["npx", "--yes", "prettier", "--write"],
        "rustfmt": ["rustfmt"],
        "gofmt": ["gofmt", "-w"],
        "google-java-format": ["google-java-format", "--replace"],
    }
    if not formatter_name or formatter_name not in commands:
        return f"[error: formatter '{formatter_name or tool}' is not installed or supported]"

    if checkOnly:
        if formatter_name == "black":
            command = ["black", "--check", "--quiet", file_path]
        elif formatter_name == "ruff":
            command = ["ruff", "format", "--check", "--quiet", file_path]
        elif formatter_name == "prettier":
            command = ["npx", "--yes", "prettier", "--check", file_path]
        else:
            return "Check result unavailable for this formatter."
    else:
        command = [*commands[formatter_name], file_path]

    result = await shell_executor.execute_argv_async(command, timeout=30)
    detail = "\n".join(
        part.strip() for part in (result["stdout"], result["stderr"]) if part.strip()
    )
    if checkOnly:
        return "File is properly formatted." if result["success"] else "File needs formatting."
    if not result["success"]:
        return f"[error: formatter failed: {detail or result['exit_code']}]"
    return detail or "File formatted successfully."


format_tool = StructuredTool(
    name="format",
    description="Auto-format code files using black, autopep8 (Python), prettier (JS/TS/JSON/CSS/MD), "
                "ruff (Python), rustfmt (Rust), gofmt (Go), or google-java-format (Java). "
                "Use 'checkOnly' to verify formatting without modifying.",
    func=run_format,
    coroutine=run_format_async,
    args_schema=FormatInput,
)
