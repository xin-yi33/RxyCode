"""Task list management tool — public name ``task_manage``.

B13 · Migration: the task list tool's public model tool name moves from
``task`` to ``task_manage`` so the ``task`` name is reserved for the
isolated-subagent dispatch tool.

The implementation reuses the persistent task store from ``tools/task_tool.py``
(tasks.json with file locking). This module only changes the registered name;
it does NOT reimplement task persistence or lock semantics.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from .task_tool import manage_tasks


class TaskManageInput(BaseModel):
    """Argument schema for the ``task_manage`` tool."""

    operation: str = Field(description="Operation: create, list, get, start, block, unblock, done, abandon, rename")
    id: str = Field(default="", description="Task ID (e.g. T1, T1.1)")
    summary: str = Field(default="", description="Task summary (for create/rename)")
    status: str = Field(default="", description="Status filter for list")
    event_summary: str = Field(default="", description="Short note for state transitions")


async def task_manage_async(**kwargs: object) -> str:
    """Async wrapper delegating to the shared task store."""
    await asyncio.sleep(0)
    return manage_tasks(**kwargs)


def task_manage_sync(**kwargs: object) -> str:
    """Sync wrapper delegating to the shared task store."""
    return manage_tasks(**kwargs)


task_manage_tool = StructuredTool(
    name="task_manage",
    description=(
        "Persistent task management. Operations: create, list, get, start, "
        "block, unblock, done, abandon, rename. This manages a task checklist; "
        "to dispatch an isolated subagent, use the 'task' tool instead."
    ),
    func=task_manage_sync,
    coroutine=task_manage_async,
    args_schema=TaskManageInput,
)
