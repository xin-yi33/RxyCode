"""Behavioral contract tests for public AgentV2 modes."""

import pytest


@pytest.mark.asyncio
async def test_agent_run_rejects_unknown_mode_before_initialization():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent._cancelled = False

    with pytest.raises(ValueError, match="Unsupported agent mode"):
        await agent.run("hello", mode="unsafe")
