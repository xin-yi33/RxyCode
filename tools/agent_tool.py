"""Delegate a sub-task to a child AgentV2 instance.

B13 migration: this is the LEGACY direct-AgentV2 entry. It does not create
an isolated Child Session. When subagents are enabled, calling this raises
a deprecation error directing callers to the new ``task`` tool. When
subagents are disabled (default), the legacy behavior is preserved for
backward compatibility (feature-flag rollback).
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# Migration guidance surfaced to legacy callers when subagents are enabled.
LEGACY_SUBAGENT_DEPRECATED_MSG = (
    "The legacy 'agent' tool creates an unisolated AgentV2 and is deprecated. "
    "Use the 'task' tool (isolated Child Session) or the '@agent' mention. "
    "This error is raised because subagents are enabled."
)


class AgentInput(BaseModel):
    prompt: str = Field(description="Task prompt for the sub-agent to execute")


async def run_agent_async(prompt: str) -> str:
    """Run a child agent without blocking a thread or swallowing cancellation."""
    if _subagents_enabled():
        raise RuntimeError(LEGACY_SUBAGENT_DEPRECATED_MSG)

    from ..core.agent_v2 import AgentV2
    from ..utils.tui import get_tui

    tui = get_tui()
    tui.write_info(f"Sub-agent starting: {prompt[:60]}...")
    try:
        result = await AgentV2().run(prompt, mode="compose")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        tui.write_error(f"Sub-agent error: {exc}")
        return f"[agent error] {exc}"

    tui.write_success("Sub-agent completed")
    return str(result)


def _subagents_enabled() -> bool:
    """Check whether the subagents feature flag is enabled."""
    try:
        from ..core.subagents.registry_provider import get_manager_or_none
        manager = get_manager_or_none()
        if manager is None:
            return False
        return manager.config.flags.subagents_enabled
    except Exception:
        return False


def run_agent(prompt: str) -> str:
    """Synchronous compatibility entry point for callers without an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(run_agent_async(prompt))
    raise RuntimeError("run_agent cannot run inside an event loop; await run_agent_async")


agent_tool = StructuredTool(
    name="agent",
    description=(
        "DEPRECATED legacy sub-agent entry (creates an unisolated AgentV2). "
        "Use the 'task' tool for an isolated Child Session, or '@agent' mention. "
        "Raises when subagents are enabled."
    ),
    func=run_agent,
    coroutine=run_agent_async,
    args_schema=AgentInput,
)
