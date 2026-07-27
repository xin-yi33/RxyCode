"""Social-chat routing: emotion + play-game must not enter LangGraph.

E1: 「玩游戏」 must not be treated like 「写游戏」 code intent.
E7: social chat stays on fast path even when UI mode is build.
"""
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def _agent() -> AgentV2:
    return object.__new__(AgentV2)


def _simple(text: str) -> bool:
    return _agent()._is_simple_query(text)


def _social(text: str) -> bool:
    return _agent()._is_social_chat(text)


def test_sad_play_game_with_friend_is_social_and_simple():
    text = "我一直想找我的朋友玩游戏，但是他不理我，我好伤心"
    assert _social(text) is True
    assert _simple(text) is True


def test_accompany_play_game_is_social():
    assert _social("陪我玩游戏好吗") is True
    assert _simple("陪我玩游戏好吗") is True


def test_write_parkour_game_still_complex():
    text = "用 Python 写一个跑酷小游戏并保存到文件"
    assert _social(text) is False
    assert _simple(text) is False


def test_create_game_still_complex():
    assert _social("写一个游戏") is False
    assert _simple("写一个游戏") is False
    assert _social("开发一个小游戏") is False
    assert _simple("帮我写一个跑酷小游戏") is False


def test_plain_hello_is_social_or_simple():
    assert _simple("你好") is True


def test_what_happened_still_simple():
    assert _simple("what happened?") is True
