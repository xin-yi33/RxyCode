import asyncio
from typing import Literal
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from ..core.session_runtime import resolve_session_path
from ..utils.atomic_file import atomic_write_text


class EditInput(BaseModel):
    filePath: str = Field(description="Absolute or session-relative file path")
    operation: Literal["replace", "write", "patch"] | None = Field(
        default=None,
        description="replace: exact-text change; write: create/overwrite with content; patch: apply diff. Omit only when one payload identifies the operation.",
    )
    oldString: str | None = Field(default=None, description="replace only: exact text to find")
    newString: str | None = Field(default=None, description="replace only: replacement text; empty deletes the match")
    replaceAll: bool = Field(default=False, description="Replace all occurrences")
    content: str | None = Field(default=None, description="write only: complete file content; empty creates/clears a file")
    diff: str | None = Field(default=None, description="patch only: standard unified diff with @@ hunk headers")


def edit_file(
    filePath: str,
    oldString: str | None = None,
    newString: str | None = None,
    replaceAll: bool = False,
    *,
    operation: str | None = None,
    content: str | None = None,
    diff: str | None = None,
) -> str:
    """One model-facing file mutation entry; reuse the atomic write/diff helpers."""
    supplied = []
    if oldString is not None or newString is not None:
        supplied.append("replace")
    if content is not None:
        supplied.append("write")
    if diff is not None:
        supplied.append("patch")
    if len(supplied) != 1 or (operation is not None and operation != supplied[0]):
        return "[error editing file: provide exactly one matching payload: replace=oldString+newString, write=content, patch=diff]"
    selected = operation or supplied[0]
    if replaceAll and selected != "replace":
        return "[error editing file: replaceAll is only valid for replace]"
    if selected == "write":
        from .write import write_file

        return write_file(filePath, content)
    if selected == "patch":
        if not diff.strip():
            return "[error editing file: patch requires a non-empty unified diff]"
        from .patch import run_patch

        return run_patch(filePath, diff)
    if oldString is None or newString is None or not oldString:
        return "[error editing file: replace requires non-empty oldString and a newString (which may be empty)]"
    p = resolve_session_path(filePath)
    if not p.exists():
        return f"[error: file not found: {filePath}]"
    try:
        with open(p, "r", encoding="utf-8", newline="") as f:
            content = f.read()

        if oldString not in content:
            # Exact match failed, provide helpful context
            lines = content.split('\n')
            # Try line-level fuzzy matching
            old_lines = oldString.strip().split('\n')
            first_line = old_lines[0].strip()

            # Search for lines containing first_line
            similar_lines = []
            for i, line in enumerate(lines, 1):
                if first_line and first_line in line:
                    similar_lines.append(f"  line {i}: {line.rstrip()}")

            error_msg = f"[error: oldString not found in {filePath}]"
            error_msg += f"\n[searched for ({len(oldString)} chars): {repr(oldString[:200])}]"

            if similar_lines:
                error_msg += "\n[similar content found at:]"
                for sl in similar_lines[:5]:
                    error_msg += f"\n{sl}"
            else:
                # If no similar lines, show file beginning
                preview = '\n'.join(
                    f"  {i+1}: {line}" for i, line in enumerate(lines[:10])
                )
                error_msg += f"\n[file starts with:]\n{preview}"
                if len(lines) > 10:
                    error_msg += f"\n  ... ({len(lines)} lines total)"

            return error_msg

        # Prevent no-op edits (oldString == newString)
        if oldString == newString:
            return f"[error: oldString and newString are identical ({repr(oldString[:50])}). No change needed.]"

        if not replaceAll:
            count = content.count(oldString)
            if count > 1:
                return f"[error: found {count} matches for oldString. Use replaceAll or provide more context]"
            content = content.replace(oldString, newString, 1)
        else:
            content = content.replace(oldString, newString)
        from .write import (
            _TEST_FUNCTION_CAP,
            _TEST_FUNCTION_CAP_BY_NAME,
            _count_test_functions,
        )
        parts = {part.lower() for part in p.parts}
        if p.suffix == ".py" and (
            p.name.startswith("test_") or p.name == "test.py" or "tests" in parts
        ):
            n = _count_test_functions(content)
            cap = _TEST_FUNCTION_CAP_BY_NAME.get(p.name, _TEST_FUNCTION_CAP)
            if n is not None and n > cap:
                return (
                    f"[error editing file: {p.name} would have {n} test_ functions; "
                    f"keep at most {cap} covering the named behaviors. File not edited.]"
                )
        atomic_write_text(p, content)
        # Diagnostics run on the ASYNC path only (``edit_file_async``), which is
        # the path the agent uses.  Calling the coroutine here produced an
        # un-awaited coroutine and no report at all -- the "declared diagnostics
        # never wired" regression.  The synchronous function stays a pure
        # writer for callers that cannot await.
        return f"[edited {filePath}]"
    except Exception as e:
        return f"[error editing file: {e}]"


async def edit_file_async(
    filePath: str,
    oldString: str | None = None,
    newString: str | None = None,
    replaceAll: bool = False,
    *,
    operation: str | None = None,
    content: str | None = None,
    diff: str | None = None,
) -> str:
    await asyncio.sleep(0)
    result = edit_file(
        filePath, oldString, newString, replaceAll,
        operation=operation, content=content, diff=diff,
    )
    return await _attach_diagnostics(result, filePath)


#: Success prefixes of the three write operations.  replace returns
#: ``[edited ...]``, write returns ``[wrote ...]`` and patch returns
#: ``Patch applied ...``.  Matching only the first one silently skipped
#: diagnostics for the other two (audit P2, round 4: 0/0/1 calls).
_SUCCESS_PREFIXES = ("[edited", "[wrote", "Patch applied")


def _operation_for_result(result: str) -> str:
    """Map a success message to the operation name used in the report."""
    if result.startswith("[wrote"):
        return "write"
    if result.startswith("Patch applied"):
        return "patch"
    return "edit"


async def _attach_diagnostics(result: str, filePath: str) -> str:
    """Append the post-write report after a successful write.

    All three operations (replace/write/patch) end in one committed file, so
    they share ONE diagnostics entry point (``post_write_report``) with the
    standalone write/patch functions.  That is what keeps the "check the saved
    version exactly once" contract true across every write path.

    A failed edit/missing checker never turns into a write failure: only a
    successful result is extended.
    """
    if not isinstance(result, str) or not result.startswith(_SUCCESS_PREFIXES):
        return result
    try:
        from .write import post_write_report_async

        p = resolve_session_path(filePath)
        saved = p.read_text(encoding="utf-8", errors="replace")
        block = await post_write_report_async(
            p, saved, operation=_operation_for_result(result)
        )
        return result + block
    except Exception as exc:  # diagnostics must never fail the edit
        return result + f"\n[syntax check: unavailable — {type(exc).__name__}]"


edit_tool = StructuredTool.from_function(
    func=edit_file,
    coroutine=edit_file_async,
    name="edit",
    description=(
        "Create or modify a file. Use operation='write' with content for new files/full replacement; "
        "operation='replace' with oldString/newString for small exact changes; "
        "operation='patch' with diff for multiple hunks. Read before changing existing files. "
        "Use exactly one payload; replaceAll applies only to replace. "
        "Python and JavaScript results include syntax and linter findings."
    ),
    args_schema=EditInput,
)
