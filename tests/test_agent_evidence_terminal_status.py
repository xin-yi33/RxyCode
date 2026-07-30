"""Tool-boundary evidence is authoritative over optimistic model prose."""

import pytest


@pytest.mark.asyncio
async def test_failed_tool_evidence_overrides_optimistic_final_answer():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor

    agent = object.__new__(AgentV2)

    async def optimistic_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "bash",
            {"command": "failing-command"},
            "[error] command failed",
            executed=True,
            approval="approved",
        )
        return "Task completed successfully"

    agent._run_impl = optimistic_run
    result = await agent.run("do the work")

    assert result.startswith("[evidence failed:")
    assert "Task completed successfully" not in result
    assert agent._last_evidence[0]["status"] == "failed"
    snapshot = run_monitor.snapshot()
    assert snapshot["status_counts"] == {"failed": 1}
    assert snapshot["tool_evidence"] == {"total": 1, "failed": 1}
