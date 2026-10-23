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

    from .write import post_write_report

    return (
        f"Patch applied to {file_path}. +{additions} -{removals} lines."
        + post_write_report(file_path, patched)
    )


async def run_patch_async(filePath: str, diff: str) -> str:
    await asyncio.sleep(0)
    return run_patch(filePath, diff)


def _apply_diff(original: str, diff: str) -> str:
    """Apply a unified diff only when every hunk matches the original file."""
    if not diff.strip():
        return original
    lines = diff.splitlines()
    result: list[str] = []
    orig_lines = original.splitlines()
    orig_idx = 0
    final_newline = original.endswith(("\n", "\r"))
    newline = "\r\n" if "\r\n" in original else "\n"
    hunks = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(("--- ", "+++ ", "diff ", "index ")):
            i += 1
            continue
        match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match is None:
            raise ValueError("expected a unified diff @@ hunk header")
        old_count = int(match.group(2) or 1)
        new_count = int(match.group(4) or 1)
        old_start = int(match.group(1))
        start = old_start if old_count == 0 else old_start - 1
        if start < orig_idx or start > len(orig_lines):
            raise ValueError("overlapping or out-of-range patch hunk")
        result.extend(orig_lines[orig_idx:start])
        orig_idx = start
        new_start = int(match.group(3))
        if new_start != len(result) + (1 if new_count else 0):
            raise ValueError("patch new-line position does not match preceding hunks")
        old_used = new_used = 0
        previous_kind = ""
        hunks += 1
        i += 1
        while i < len(lines) and not lines[i].startswith("@@"):
            body = lines[i]
            if body.startswith("\\ No newline"):
                if previous_kind in {"+", " "}:
                    final_newline = False
                i += 1
                continue
            if body.startswith(("diff ", "index ")) or (
                (old_used, new_used) == (old_count, new_count)
                and body.startswith(("--- ", "+++ "))
            ):
                raise ValueError("one file per edit patch operation")
            if not body or body[0] not in " +-":
                raise ValueError("invalid patch hunk line")
            kind, text = body[0], body[1:]
            if kind in " -":
                if orig_idx >= len(orig_lines) or orig_lines[orig_idx] != text:
                    raise ValueError(f"patch context/removal does not match line {orig_idx + 1}")
                orig_idx += 1
                old_used += 1
            if kind in " +":
                result.append(text)
                new_used += 1
            previous_kind = kind
            i += 1
        if (old_used, new_used) != (old_count, new_count):
            raise ValueError("patch hunk line counts do not match its header")
    if not hunks:
        raise ValueError("patch contains no hunks")
    result.extend(orig_lines[orig_idx:])
    output = newline.join(result)
    if final_newline and result:
        output += newline
    return output


# 兼容入口（2026-10-13）：不再注册独立 patch schema。模型使用 edit 的
# patch operation；run_patch/_apply_diff 是共享补丁实现，并非废弃死代码。
patch_tool = StructuredTool(
    name="patch",
    description="Apply a unified diff patch to a file. Use standard unified diff format with @@ hunk headers.",
    func=run_patch,
    coroutine=run_patch_async,
    args_schema=PatchInput,
)
