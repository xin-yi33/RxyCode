"""Delegate a sub-task to a child AgentV2 instance."""

from __future__ import annotations

import asyncio

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class AgentInput(BaseModel):
    prompt: str = Field(description="Task prompt for the sub-agent to execute")


async def run_agent_async(prompt: str) -> str:
    """Run a child agent without blocking a thread or swallowing cancellation."""
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
        "Run a sub-task with a child AI agent. Use for complex searches, analysis, "
        "or tasks that benefit from a fresh context."
    ),
    func=run_agent,
    coroutine=run_agent_async,
    args_schema=AgentInput,
)
