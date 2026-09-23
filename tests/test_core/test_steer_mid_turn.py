"""Mid-turn steer is delivered after the current tool, before the next LLM call."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.agent_v2 import apply_mid_turn_steers


def test_apply_mid_turn_steers_appends_user_after_tools() -> None:
    messages = [
        HumanMessage(content="先做环境检查"),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "1"}]),
        ToolMessage(content="python 3.11", tool_call_id="1"),
    ]
    queued = ["严谨一点，只要 agent 开源项目"]

    def drain() -> list[str]:
        items = list(queued)
        queued.clear()
        return items

    applied = apply_mid_turn_steers(messages, drain)
    assert applied == ["严谨一点，只要 agent 开源项目"]
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == "严谨一点，只要 agent 开源项目"
    assert queued == []


def test_apply_mid_turn_steers_noop_without_drain() -> None:
    messages = [HumanMessage(content="hi")]
    assert apply_mid_turn_steers(messages, None) == []
    assert len(messages) == 1
