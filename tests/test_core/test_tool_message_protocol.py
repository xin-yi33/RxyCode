from __future__ import annotations

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def test_failed_tool_result_keeps_recovery_feedback_in_one_message():
    agent = AgentV2.__new__(AgentV2)
    agent._seen_tool_fingerprints = {}
    agent._cfg = {}

    content = agent._tool_result_message_content(
        "bash", "[error executing bash: command not found]"
    )

    assert "[error executing bash: command not found]" in content
    assert "[error feedback]" in content
    assert content.count("[error feedback]") == 1
    assert "禁止静默连打下一个工具" in content


def test_successful_tool_result_still_asks_model_to_speak():
    agent = AgentV2.__new__(AgentV2)
    agent._seen_tool_fingerprints = {}
    agent._cfg = {}

    content = agent._tool_result_message_content("bash", "ok files listed")
    assert "ok files listed" in content
    assert "禁止静默连打下一个工具" in content
