"""Structured, cancellable Git operations."""
from __future__ import annotations

import os
import shlex
import subprocess

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.session_runtime import resolve_session_path
from ..utils.shell import shell_executor


class GitInput(BaseModel):
    operation: str = Field(
        default="status",
        description="Git operation: status, diff, log, branch, add, commit, checkout, push, pull, stash",
    )
    path: str = Field(default=".", description="Repository path")
    args: str = Field(default="", description="Additional Git arguments")


def _format_git_result(stdout: str, stderr: str, success: bool) -> str:
    output = stdout or ""
    if stderr:
        output += f"\n[error] {stderr.strip()}" if not success else f"\n{stderr.strip()}"
    return output.strip()


def _run_git(cmd: list[str], repo_path: str) -> str:
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return _format_git_result(result.stdout, result.stderr, result.returncode == 0)
    except subprocess.TimeoutExpired:
        return "[error: git command timed out (60s)]"
    except FileNotFoundError:
        return "[error: git not found. Install git from https://git-scm.com/]"
    except Exception as exc:
        return f"[error: {exc}]"


def _build_git_command(operation: str, args: str) -> list[str] | str:
    op = operation.lower().strip()
    try:
        extra = shlex.split(args)
    except ValueError as exc:
        return f"[error: invalid Git arguments: {exc}]"

    if op == "status":
        return ["git", "status", "--short"] if not args else ["git", "status"]
    if op == "diff":
        return ["git", "diff", *(extra or ["--stat"])]
    if op == "log":
        limit = args or "10"
        try:
            int(limit)
        except ValueError:
            limit = "10"
        return ["git", "log", f"--max-count={limit}", "--oneline", "--graph"]
    if op == "branch":
        return ["git", "branch", *(extra or ["-a"])]
    if op == "add":
        return ["git", "add", *(extra or ["."])]
    if op == "commit":
        if not args:
            return "[error: commit message required. Use args='-m \"message\"']"
        return ["git", "commit", *(extra if args.startswith("-") else ["-m", args])]
    if op == "checkout":
        if not args:
            return "[error: branch name or commit hash required]"
        return ["git", "checkout", *extra]
    if op in {"push", "pull"}:
        return ["git", op, *extra]
    if op == "stash":
        return ["git", "stash", *(extra or ["list"])]
    if op == "init":
        return ["git", "init"]
    if op == "remote":
        return ["git", "remote", *(extra or ["-v"])]
    return (
        f"[error: unknown git operation '{operation}'. Supported: status, diff, "
        "log, branch, add, commit, checkout, push, pull, stash, init, remote]"
    )


def run_git(operation: str = "status", path: str = ".", args: str = "") -> str:
    repo_path = str(resolve_session_path(path))
    if not os.path.isdir(repo_path):
        return f"[error: path '{path}' is not a directory]"
    command = _build_git_command(operation, args)
    if isinstance(command, str):
        return command
    return _run_git(command, repo_path)


async def run_git_async(
    operation: str = "status", path: str = ".", args: str = ""
) -> str:
    """Run Git natively async and terminate its process tree on cancellation."""
    repo_path = str(resolve_session_path(path))
    if not os.path.isdir(repo_path):
        return f"[error: path '{path}' is not a directory]"
    command = _build_git_command(operation, args)
    if isinstance(command, str):
        return command
    result = await shell_executor.execute_argv_async(
        command, workdir=repo_path, timeout=60
    )
    return _format_git_result(
        result["stdout"], result["stderr"], result["success"]
    )


git_tool = StructuredTool(
    name="git",
    description=(
        "Execute Git operations: status, diff, log, branch, add, commit, "
        "checkout, push, pull, stash, init, remote."
    ),
    func=run_git,
    coroutine=run_git_async,
    args_schema=GitInput,
)
