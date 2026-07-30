import asyncio
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from ..core.session_runtime import resolve_session_path
from ..utils.atomic_file import atomic_write_text


class EditInput(BaseModel):
    filePath: str = Field(description="Absolute or session-relative file path")
    oldString: str = Field(description="Exact text to find and replace")
    newString: str = Field(description="Replacement text")
    replaceAll: bool = Field(default=False, description="Replace all occurrences")


def edit_file(filePath: str, oldString: str, newString: str, replaceAll: bool = False) -> str:
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
        atomic_write_text(p, content)
        return f"[edited {filePath}]"
    except Exception as e:
        return f"[error editing file: {e}]"


async def edit_file_async(
    filePath: str,
    oldString: str,
    newString: str,
    replaceAll: bool = False,
) -> str:
    await asyncio.sleep(0)
    return edit_file(filePath, oldString, newString, replaceAll)


edit_tool = StructuredTool.from_function(
    func=edit_file,
    coroutine=edit_file_async,
    name="edit",
    description="Replace exact text in a file. Use replaceAll for renaming variables etc.",
    args_schema=EditInput,
)
