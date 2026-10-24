"""patch tool - Apply unified diff patches to files."""

import asyncio
import os
import re
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from ..core.session_runtime import resolve_session_path
from ..utils.atomic_file import atomic_write_text


class PatchInput(BaseModel):
    filePath: str = Field(description="Path to the file to patch")
    diff: str = Field(description="Unified diff to apply")


def run_patch(filePath: str, diff: str) -> str:
    """Apply a unified diff patch to a file."""
    file_path = resolve_session_path(filePath)

    if not os.path.exists(file_path):
        return f"[error] File not found: {file_path}"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            original = f.read()
    except Exception as e:
        return f"[error] Cannot read file: {e}"

    try:
        patched = _apply_diff(original, diff)
    except Exception as e:
        return f"[error] Failed to apply patch: {e}"

    try:
        atomic_write_text(file_path, patched)
    except Exception as e:
        return f"[error] Cannot write file: {e}"

    # Count changes
    orig_lines = original.splitlines()
    new_lines = patched.splitlines()
    additions = max(0, len(new_lines) - len(orig_lines))
    removals = max(0, len(orig_lines) - len(new_lines))

    return f"Patch applied to {file_path}. +{additions} -{removals} lines."


async def run_patch_async(filePath: str, diff: str) -> str:
    await asyncio.sleep(0)
    result = run_patch(filePath, diff)
    if not result.startswith("Patch applied"):
        return result
    # The patch is on disk; check the content that was actually saved through
    # the same entry point write/edit use.
    from .write import post_write_report_async

    p = resolve_session_path(filePath)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return result + f"\n[syntax check: unavailable — {type(exc).__name__}]"
    try:
        return result + await post_write_report_async(p, content, operation="patch")
    except Exception as exc:  # diagnostics must never fail the patch
        return result + f"\n[syntax check: unavailable — {type(exc).__name__}]"


def _apply_diff(original: str, diff: str) -> str:
    """Apply a simple unified diff.

    Context (`` ``) and removal (``-``) lines must equal the file's actual
    lines at the hunk position.  A mismatched diff used to silently skip the
    file's real lines and still report success — a corrupted patch must
    surface as an error, never as a green apply.
    """
    lines = diff.splitlines()
    result = []
    orig_lines = original.splitlines()
    orig_idx = 0
    strip_final_newline = False

    def take_expected(expected: str) -> None:
        nonlocal orig_idx
        got = orig_lines[orig_idx] if orig_idx < len(orig_lines) else "<EOF>"
        if orig_idx >= len(orig_lines) or orig_lines[orig_idx] != expected:
            raise ValueError(
                f"context mismatch at file line {orig_idx + 1}: "
                f"expected {expected!r}, found {got!r}"
            )
        orig_idx += 1

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip diff metadata lines (--- / +++ / diff)
        if line.startswith("---") or line.startswith("+++") or line.startswith("diff "):
            i += 1
            continue

        # Handle "No newline at end of file" marker
        if line.startswith("\\ No newline"):
            strip_final_newline = True
            i += 1
            continue

        # Parse hunk header
        if line.startswith("@@"):
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if match:
                start = int(match.group(1)) - 1
                # Copy lines before hunk
                while orig_idx < start and orig_idx < len(orig_lines):
                    result.append(orig_lines[orig_idx])
                    orig_idx += 1
            i += 1
            continue

        # Context line — must equal the file line it claims to keep
        if line.startswith(" "):
            take_expected(line[1:])
            result.append(orig_lines[orig_idx - 1])
            i += 1
            continue

        # Remove line — must equal the file line it claims to delete
        if line.startswith("-"):
            take_expected(line[1:])
            i += 1
            continue

        # Add line
        if line.startswith("+"):
            result.append(line[1:])
            i += 1
            continue

        # Skip unknown lines
        i += 1

    # Copy remaining lines
    while orig_idx < len(orig_lines):
        result.append(orig_lines[orig_idx])
        orig_idx += 1

    output = "\n".join(result)
    if strip_final_newline and output.endswith("\n"):
        output = output[:-1]
    return output


patch_tool = StructuredTool(
    name="patch",
    description="Apply a unified diff patch to a file. Use standard unified diff format with @@ hunk headers.",
    func=run_patch,
    coroutine=run_patch_async,
    args_schema=PatchInput,
)
