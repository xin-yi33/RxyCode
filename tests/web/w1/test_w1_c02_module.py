"""WEB-W1-C02. Concurrent tool calls keep their own RunContext."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_SRC = REPO / "packages" / "rxycode-protocol" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _auth(tenant: str, target: str) -> dict[str, str]:
    return {
        "tenant_id": tenant,
        "actor_id": "actor-1",
        "project_id": "project-1",
        "session_id": "client-session",
        "target_id": target,
        "permission_profile": "default",
        "deadline_at": "2026-10-16T00:00:00Z",
        "trace_id": f"trace-{tenant}",
    }


async def test_w1_c02_integration():
    """Two concurrent ToolOrchestrator calls do not swap tenant or target."""
    from langchain_core.tools import StructuredTool

    from appserver.runtime import bind_prompt_context, current_run_context, reset_prompt_context
    from execution.tool_orchestrator import ToolOrchestrator
    from rxycode_protocol.run_context import RunContext

    async def echo() -> str:
        context = current_run_context()
        assert context is not None
        return f"{context.tenant_id}|{context.target_id}"

    orchestrator = ToolOrchestrator()
    orchestrator.register(
        "echo",
        StructuredTool.from_function(coroutine=echo, name="echo", description="read run scope"),
    )

    async def once(tenant: str, target: str) -> str:
        context = RunContext.from_authenticated(_auth(tenant, target))
        tokens = bind_prompt_context("ses-c02", None, run_context=context)
        try:
            return await orchestrator.execute_tool(
                "echo",
                {},
                config={"safety": {"enabled": False}},
            )
        finally:
            reset_prompt_context(tokens)

    left, right = await asyncio.gather(
        once("tenant-a", "target-a"),
        once("tenant-b", "target-b"),
    )
    assert left == "tenant-a|target-a"
    assert right == "tenant-b|target-b"
