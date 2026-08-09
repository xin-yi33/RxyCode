"""Subagent Task Tool — the SOLE dispatch entry for model-driven tasks.

B7 · This is a thin adapter layer:
  - defines the tool argument schema
  - registers the tool for model use
  - delegates ALL dispatch logic to ChildSessionManager

It MUST NOT:
  - create an AgentV2 instance
  - construct a Primary conversation history
  - implement its own lifecycle/permission/budget logic
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from protocol.subagents import (
    ContextEnvelope,
    ContextReference,
    TaskRequest,
    TriggerKind,
)


class SubagentTaskInput(BaseModel):
    """Argument schema for the `task` tool."""

    agent_id: str = Field(description="Target subagent id to dispatch (e.g. 'explore').")
    description: str = Field(default="", description="Short description of the task (for display).")
    prompt: str = Field(description="The task prompt sent to the child agent.")
    context_refs: list[str] = Field(default_factory=list, description="Context references: 'file:path', 'dir:path', 'item:id', 'artifact:id'.")
    output_schema: str = Field(default="", description="Optional output schema name for structured results.")


def _parse_context_refs(refs: list[str]) -> tuple[ContextReference, ...]:
    """Parse 'kind:value' context reference strings into ContextReference objects."""
    parsed: list[ContextReference] = []
    for ref in refs or []:
        kind, _, value = ref.partition(":")
        kind = kind.strip().lower()
        value = value.strip()
        if not value:
            continue
        if kind == "file":
            parsed.append(ContextReference(kind="file", path=value, visibility="summary"))
        elif kind == "dir":
            parsed.append(ContextReference(kind="directory", path=value, visibility="summary"))
        elif kind == "item":
            parsed.append(ContextReference(kind="item", item_id=value, visibility="summary"))
        elif kind == "artifact":
            parsed.append(ContextReference(kind="artifact", item_id=value, visibility="summary"))
    return tuple(parsed)


async def dispatch_subagent_task(
    agent_id: str,
    prompt: str,
    description: str = "",
    context_refs: list[str] | None = None,
    output_schema: str = "",
) -> str:
    """Dispatch a subagent task via the ChildSessionManager.

    This is the model-facing async entry point for the `task` tool.
    All permission/budget/workspace decisions are delegated to the manager.
    """
    from ..core.subagents.manager import ChildSessionManager
    from ..core.subagents.registry_provider import get_manager

    manager: ChildSessionManager = get_manager()

    references = _parse_context_refs(context_refs or [])

    parent_session_id = manager.primary_session_id()

    context = None
    if references or description:
        context = ContextEnvelope(
            parent_session_id=parent_session_id,
            task=description or prompt,
            references=references,
        )

    request = TaskRequest(
        parent_session_id=parent_session_id,
        agent_id=agent_id,
        prompt=prompt,
        context=context,
        trigger=TriggerKind.AUTOMATIC,
        output_schema=output_schema or None,
    )

    try:
        result = await manager.dispatch(request)
    except Exception as exc:
        return f"[task error: {exc}]"

    # Return a human-readable summary to the Primary model
    status = result.status.value
    if result.error is not None:
        return f"[task {status}] {result.summary} — error: {result.error.message}"
    return f"[task {status}] {result.summary}"


async def dispatch_subagent_task_async(
    agent_id: str,
    prompt: str,
    description: str = "",
    context_refs: list[str] | None = None,
    output_schema: str = "",
) -> str:
    """Async entry point (awaitable by the model loop)."""
    await asyncio.sleep(0)
    return await dispatch_subagent_task(
        agent_id=agent_id,
        prompt=prompt,
        description=description,
        context_refs=context_refs,
        output_schema=output_schema,
    )


def dispatch_subagent_task_sync(
    agent_id: str,
    prompt: str,
    description: str = "",
    context_refs: list[str] | None = None,
    output_schema: str = "",
) -> str:
    """Synchronous compatibility entry for callers without an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            dispatch_subagent_task(
                agent_id=agent_id,
                prompt=prompt,
                description=description,
                context_refs=context_refs,
                output_schema=output_schema,
            )
        )
    raise RuntimeError(
        "dispatch_subagent_task_sync cannot run inside an event loop; "
        "await dispatch_subagent_task_async"
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

subagent_task_tool = StructuredTool(
    name="task",
    description=(
        "Dispatch a task to a child subagent (isolated session, own permissions "
        "and budget). Use for complex searches, analysis, or tasks that benefit "
        "from a fresh context. Returns a structured result summary."
    ),
    func=dispatch_subagent_task_sync,
    coroutine=dispatch_subagent_task_async,
    args_schema=SubagentTaskInput,
)
