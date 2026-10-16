"""Edit, test, and LSP reference adapter.

Edits and pytest go through ToolOrchestrator. The exit code is the process
status from the bash tool, not a model summary. A missing language server
returns no references.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Any

from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.lsp.client import create_lsp_client
from RxyCode.RxyCode1_1_0.tools.bash import bash_tool
from RxyCode.RxyCode1_1_0.tools.edit import edit_tool

_EXIT = re.compile(r"RXY_PYTEST_EXIT (-?\d+)")


def repair_and_test(
    *,
    root: Path,
    file_path: Path,
    old: str,
    new: str,
    test_path: Path,
) -> dict[str, Any]:
    """Apply one replace edit, then run pytest in that directory."""
    return asyncio.run(
        _repair_and_test(
            root=root,
            file_path=file_path,
            old=old,
            new=new,
            test_path=test_path,
        )
    )


def run_tests(*, root: Path, test_path: Path) -> dict[str, Any]:
    """Run pytest and parse the process exit status."""
    return asyncio.run(_run_tests(root=root, test_path=test_path))


def apply_patch(
    *,
    file_path: Path,
    diff: str,
    later_file: Path | None = None,
    later_diff: str | None = None,
) -> dict[str, Any]:
    """Apply the first patch. A conflict does not write that file or a later one."""
    return asyncio.run(
        _apply_patch(
            file_path=file_path,
            diff=diff,
            later_file=later_file,
            later_diff=later_diff,
        )
    )


def references(*, language: str, workspace: str, file_path: str) -> dict[str, Any]:
    """Ask the language server for references. No server means no locations."""
    del file_path
    client = create_lsp_client(language, workspace)
    if client is None:
        return {
            "status": "unavailable",
            "language": language,
            "locations": [],
            "reason": f"language server for {language} is unavailable",
        }
    try:
        return {
            "status": "unavailable",
            "language": language,
            "locations": [],
            "reason": f"language server for {language} does not provide references",
        }
    finally:
        client.stop()


def _orchestrator() -> ToolOrchestrator:
    orchestrator = ToolOrchestrator()
    orchestrator.register("edit", edit_tool)
    orchestrator.register("bash", bash_tool)
    return orchestrator


def _config(root: Path) -> dict[str, Any]:
    return {
        "safety": {
            "enabled": False,
            "permission_mode": "full",
            "allowed_write_paths": [str(root)],
        }
    }


async def _repair_and_test(
    *,
    root: Path,
    file_path: Path,
    old: str,
    new: str,
    test_path: Path,
) -> dict[str, Any]:
    orchestrator = _orchestrator()
    edited = await orchestrator.execute_tool(
        "edit",
        {"filePath": str(file_path), "oldString": old, "newString": new},
        config=_config(root),
    )
    if not _edit_succeeded(str(edited)):
        raise RuntimeError(str(edited))
    tested = await _run_tests(root=root, test_path=test_path, orchestrator=orchestrator)
    tested["edit"] = str(edited)
    return tested


async def _run_tests(
    *,
    root: Path,
    test_path: Path,
    orchestrator: ToolOrchestrator | None = None,
) -> dict[str, Any]:
    _ensure_runner_path()
    runner = orchestrator or _orchestrator()
    script = root / "_rxy_pytest_runner.py"
    script.write_text(
        "import subprocess\n"
        "import sys\n"
        "completed = subprocess.run([sys.executable, '-m', 'pytest', sys.argv[1], '-q'])\n"
        "print('RXY_PYTEST_EXIT', completed.returncode)\n"
        "raise SystemExit(completed.returncode)\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script}" "{test_path}"'
    output = await runner.execute_tool(
        "bash",
        {"command": command, "workdir": str(root)},
        config=_config(root),
    )
    text = str(output)
    exit_code = _process_exit(text)
    return {
        "exit_code": exit_code,
        "output": text,
        "report": _report("pytest", exit_code, text),
    }


async def _apply_patch(
    *,
    file_path: Path,
    diff: str,
    later_file: Path | None,
    later_diff: str | None,
) -> dict[str, Any]:
    orchestrator = _orchestrator()
    detail = await orchestrator.execute_tool(
        "edit",
        {"filePath": str(file_path), "diff": diff},
        config=_config(file_path.parent),
    )
    text = str(detail)
    if not _edit_succeeded(text):
        return {"applied": False, "detail": text}
    if later_file is not None and later_diff is not None:
        return await _apply_patch(file_path=later_file, diff=later_diff, later_file=None, later_diff=None)
    return {"applied": True, "detail": text}


def _ensure_runner_path() -> None:
    repo = Path(__file__).resolve().parents[5]
    runner = repo / "packages" / "rxycode-runner" / "src"
    if runner.is_dir() and str(runner) not in sys.path:
        sys.path.insert(0, str(runner))


def _edit_succeeded(text: str) -> bool:
    lowered = text.lower()
    return lowered.startswith("[edited") or "patch applied to" in lowered


def _process_exit(output: str) -> int:
    match = _EXIT.search(output)
    if match is None:
        raise RuntimeError(f"pytest result has no process exit code: {output[-500:]}")
    return int(match.group(1))


def _report(framework: str, exit_code: int, output: str) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.strip()]
    summary = lines[-1] if lines else ""
    return {
        "framework": framework,
        "exit_code": exit_code,
        "status": "failed" if exit_code != 0 else "passed",
        "summary": summary,
    }
