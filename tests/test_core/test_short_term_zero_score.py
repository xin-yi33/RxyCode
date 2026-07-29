"""Zero-score short-term context must not inject unrelated history."""
from langchain_core.messages import AIMessage, HumanMessage

from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory


def test_zero_score_returns_empty():
    stm = ShortTermMemory(window_size=10)
    stm._messages.append(HumanMessage(content="写一个跑酷小游戏并保存"))
    stm._messages.append(AIMessage(content="<html>parkour game code...</html>"))
    assert stm.get_relevant_context("你好") == ""


def test_positive_overlap_still_returns():
    stm = ShortTermMemory(window_size=10)
    stm._messages.append(HumanMessage(content="写一个跑酷小游戏"))
    stm._messages.append(AIMessage(content="parkour html ready"))
    ctx = stm.get_relevant_context("继续改跑酷")
    assert "跑酷" in ctx or "parkour" in ctx.lower()
