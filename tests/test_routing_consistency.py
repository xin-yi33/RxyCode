"""Routing consistency test for the parkour-game vs spider-card-game issue.

User report: "昨天让他给我写一个跑酷小游戏的时候一直报错，之前写蜘蛛卡牌游戏
的时候都可以的。"  (parkour game kept erroring; spider card game worked.)

Root cause (see core/agent_v2.py::_is_simple_query): the classifier routed
"写一个跑酷小游戏" to the SIMPLE (no-tool) fast-reply path, which only streams
text and can never write/run a file. A phrasing that hit the complex-path
keywords (创建/实现 + 整个) went through the tool-capable pipeline and
actually built the game. The fix adds code/game/app intent detection so any
"写一个游戏/代码" request gets the tool pipeline it needs.

These tests assert the CORRECT (post-fix) behaviour. They pass once the
code-intent guard is in place.
"""
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def _classify(text: str) -> bool:
    # _is_simple_query is self-contained (no self state), so we can construct
    # the instance without running __init__ (which would build the LLM).
    agent = object.__new__(AgentV2)
    return agent._is_simple_query(text)


def test_parkour_game_is_routed_to_complex_pipeline():
    """A request to BUILD A GAME must NOT take the no-tool fast-reply path."""
    parkour = "帮我用Python写一个跑酷小游戏"
    assert _classify(parkour) is False  # False == "complex" (uses tools)


def test_spider_card_game_is_routed_to_complex_pipeline():
    card = "帮我用Python写一个蜘蛛纸牌游戏"
    assert _classify(card) is False


def test_equivalent_game_requests_are_classified_consistently():
    """'跑酷小游戏' and '蜘蛛纸牌游戏' are equally complex; routing must match."""
    parkour = "帮我写一个跑酷小游戏"
    card = "帮我写一个蜘蛛纸牌游戏"
    assert _classify(parkour) == _classify(card)


def test_explicit_full_build_still_complex():
    assert _classify("帮我创建一个完整的Python项目") is False
    assert _classify("Build a complete REST API from scratch") is False


def test_plain_chat_still_simple():
    """Genuinely simple questions should stay on the fast path."""
    assert _classify("Python 的 list 和 tuple 有什么区别？") is True
    assert _classify("what is a decorator in python?") is True
