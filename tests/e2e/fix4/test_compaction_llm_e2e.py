"""layer=e2e E-F4-E2E-02 压缩 LLM 摘要全路径。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

pytestmark = pytest.mark.e2e


def _long_chain() -> list:
    """超 occupancy 的真实消息链：4 个工具轮 + 尾 2 轮，文本大到必然 fold。"""
    messages: list = [SystemMessage(content="S1-FROZEN-E2E")]
    for turn in range(4):
        messages.append(HumanMessage(content=f"第{turn}轮任务：处理模块 m{turn} " * 40))
        messages.append(
            AIMessage(
                content=f"读 m{turn}.py",
                tool_calls=[{"id": f"c{turn}", "name": "read_file", "args": {"path": f"m{turn}.py"}}],
            )
        )
        messages.append(ToolMessage(content=f"m{turn} 源文件全文 " * 120, tool_call_id=f"c{turn}"))
        messages.append(AIMessage(content=f"m{turn} 处理完成，结论 blockers=none " * 20))
    messages.append(HumanMessage(content="最后被问到的问题：下一步？"))
    messages.append(AIMessage(content="尾巴保留轮 1"))
    messages.append(HumanMessage(content="尾巴保留轮 2 问题"))
    messages.append(AIMessage(content="尾巴保留轮 2 回答"))
    return messages


def test_e2e_f4_02_compaction_llm_summary_then_continue_prefix(tmp_path):
    """layer=e2e E-F4-E2E-02
    setup：真实消息链 + 假 LLM summarizer（注入点）。
    扰动：run_compaction_ladder 触发（occupancy 超 usable，真实 tiktoken 计数）。
    断言：墓碑先行 → fold 六字段摘要落盘 → 把压缩结果灌回 _agent_prefix_messages
    后续聊一轮 → _agent_prefix_is_live(S1) 为真、S1 逐字节、LLM 摘要仍在链上。
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity
    from RxyCode.RxyCode1_1_0.core.compaction import TOOL_RESULT_TOMBSTONE, run_compaction_ladder

    captured: dict = {}

    async def summarizer(folded):
        captured["folded_types"] = [getattr(m, "type", "") for m in folded]
        return {
            "objective": "finish 4 module passes",
            "constraints": "keep interfaces",
            "progress": "4/4 passes done",
            "files_touched": ["m0.py", "m1.py", "m2.py", "m3.py"],
            "next_step": "write tests",
            "blockers": "none",
        }

    chain = _long_chain()
    out, telemetry = run_compaction_ladder(
        chain,
        force=True,
        context_window=8_000,
        summarizer=summarizer,
    )
    assert telemetry["rung"] == "fold"
    assert telemetry["summary_source"] == "llm"
    assert telemetry["tombstoned"] >= 2
    assert "folded_types" in captured
    tool_texts = [getattr(m, "content", "") for m in out if getattr(m, "type", "") == "tool"]
    assert any(TOOL_RESULT_TOMBSTONE in t for t in tool_texts)
    summary_msgs = [
        m for m in out
        if getattr(m, "type", "") == "system"
        and (getattr(m, "additional_kwargs", None) or {}).get("is_compaction_summary")
    ]
    assert len(summary_msgs) == 1
    summary_text = summary_msgs[0].content
    assert "Objective: finish 4 module passes" in summary_text
    assert "Files Touched: m0.py, m1.py, m2.py, m3.py" in summary_text
    assert "Blockers: none" in summary_text
    assert tool_pair_integrity(out) is True

    agent = object.__new__(AgentV2)
    agent._agent_prefix_messages = list(out)
    assert agent._agent_prefix_is_live("S1-FROZEN-E2E") is True
    followup = agent._continue_agent_prefix("S1-FROZEN-E2E", "续聊：继续写测试")
    assert followup[0].content == "S1-FROZEN-E2E"
    assert followup[-1].content == "续聊：继续写测试"
    assert any(
        "Objective: finish 4 module passes" in getattr(m, "content", "")
        for m in followup
    )
