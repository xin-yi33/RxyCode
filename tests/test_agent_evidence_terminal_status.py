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


@pytest.mark.asyncio
async def test_read_only_probe_failure_does_not_override_completed_answer():
    """A failed read-only probe (webfetch/websearch) must not discard a fully
    completed answer. Research fetches are attempts — the model may retry with
    another source. Only critical (WRITE/DANGER or artifact) failures override.
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)

    async def completed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "webfetch",
            {"url": "https://example.com/404", "format": "text"},
            "[error fetching https://example.com/404: Client error '404 Not Found' for url]",
            executed=True,
            approval="approved",
            risk=RiskLevel.READ,
        )
        return "2026 年 AI 编程助手的三大趋势：Agentic 编码、上下文工程、安全治理。"

    agent._run_impl = completed_run
    result = await agent.run("搜索 2026 AI 编程助手趋势")

    assert result.startswith("2026 年 AI 编程助手")
    assert "evidence failed" not in result


@pytest.mark.asyncio
async def test_write_failure_still_overrides_even_with_read_probe_failure():
    """A WRITE-level failure must still override, even when a read-only probe
    also failed in the same run."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    agent = object.__new__(AgentV2)

    async def mixed_run(_user_input: str, _mode: str) -> str:
        ToolOrchestrator()._finish(
            "webfetch",
            {"url": "https://example.com/404", "format": "text"},
            "[error fetching https://example.com/404: 404]",
            executed=True,
            approval="approved",
            risk=RiskLevel.READ,
        )
        ToolOrchestrator()._finish(
            "bash",
            {"command": "python script.py"},
            "[error] script crashed",
            executed=True,
            approval="approved",
            risk=RiskLevel.WRITE,
        )
        return "claiming success despite failure"

    agent._run_impl = mixed_run
    result = await agent.run("do the work")

    assert result.startswith("[evidence failed:")
    assert "claiming success" not in result
