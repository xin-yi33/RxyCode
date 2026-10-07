"""layer=unit F4-4 前缀截断（agent 侧）。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity


def _agent_with_prefix(messages):
    agent = object.__new__(AgentV2)
    agent._agent_prefix_messages = list(messages)
    return agent


def _chain():
    return [
        SystemMessage(content="S1-FROZEN"),
        HumanMessage(content="h1"),
        AIMessage(
            content="call read",
            tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "a.txt"}}],
        ),
        ToolMessage(content="content", tool_call_id="c1"),
        AIMessage(content="done t1"),
        HumanMessage(content="h2"),
        AIMessage(content="done t2"),
        HumanMessage(content="h3"),
        AIMessage(content="done t3"),
    ]


def test_u_f4_4_01_truncates_to_human_boundary_keeps_s1():
    """layer=unit U-F4-4-01
    scope=conversation 的核心动作：截到第 2 条 human 的完整 turn 边界；S1 保留；计数精准。
    """
    agent = _agent_with_prefix(_chain())
    truncated = agent._rewind_agent_prefix(keep_human_messages=2)
    kept = agent._agent_prefix_messages
    assert truncated == 2                                 # H3 + AI3 被截掉
    assert kept[0].content == "S1-FROZEN"
    assert kept[-1].content == "done t2"
    assert [m.content for m in kept if getattr(m, "type", "") == "human"] == ["h1", "h2"]
    assert tool_pair_integrity(kept) is True
    assert agent._agent_prefix_is_live("S1-FROZEN") is True


def test_u_f4_4_02_cut_never_orphans_tool_result():
    """layer=unit U-F4-4-02
    目标边界切在 assistant(tool_call)↔tool 配对中间 → 向前收缩到配对完整处，不出孤儿。
    """
    chain = _chain()
    chain[6] = AIMessage(                                  # h2 的回复改为未配对 tool_call
        content="call write",
        tool_calls=[{"id": "c9", "name": "write_file", "args": {"path": "b.txt"}}],
    )
    agent = _agent_with_prefix(chain)
    truncated = agent._rewind_agent_prefix(keep_human_messages=2)
    kept = agent._agent_prefix_messages
    assert tool_pair_integrity(kept) is True
    assert kept[-1].content == "done t1"                   # 收缩到 t1 完整边界
    assert truncated == 4                                  # c9/h3/ai3 + …见断言：
    assert [m.content for m in kept if getattr(m, "type", "") == "human"] == ["h1"]
