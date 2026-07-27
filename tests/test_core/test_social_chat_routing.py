"""Social-chat routing: emotion + play-game must not enter LangGraph.

E1: 「玩游戏」 must not be treated like 「写游戏」 code intent.
E6: social chat uses a narrow tool whitelist (datetime only; no write/edit/bash).
E7: social chat stays on fast path even when UI mode is build.
"""
from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    AgentV2,
    CODE_MUTATING_TOOL_NAMES,
    PLAN_READONLY_TOOL_NAMES,
    SOCIAL_CHAT_TOOL_NAMES,
)


def _agent() -> AgentV2:
    return object.__new__(AgentV2)


def _simple(text: str) -> bool:
    return _agent()._is_simple_query(text)


def _social(text: str) -> bool:
    return _agent()._is_social_chat(text)


def _allowlist(text: str, explicit: frozenset[str] | None = None):
    return _agent()._resolve_fast_reply_tool_allowlist(text, explicit)


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


def test_error_complaint_is_social():
    assert _social("你却说 Error") is True
    assert _simple("你却说 Error") is True


def test_social_chat_tool_whitelist_is_datetime_only():
    assert SOCIAL_CHAT_TOOL_NAMES == frozenset({"datetime"})
    assert _allowlist("我好伤心") == SOCIAL_CHAT_TOOL_NAMES
    assert _allowlist("你却说 Error") == SOCIAL_CHAT_TOOL_NAMES


def test_social_chat_bans_mutating_tools():
    assert CODE_MUTATING_TOOL_NAMES.isdisjoint(SOCIAL_CHAT_TOOL_NAMES)
    for banned in ("write", "edit", "bash", "patch", "shell"):
        assert banned not in SOCIAL_CHAT_TOOL_NAMES


def test_parkour_game_keeps_full_tool_allowlist():
    text = "用 Python 写一个跑酷小游戏并保存到文件"
    assert _allowlist(text) is None


def test_explicit_allowlist_not_overridden_for_social():
    assert _allowlist("你好", PLAN_READONLY_TOOL_NAMES) == PLAN_READONLY_TOOL_NAMES


def test_social_core_tools_filter_excludes_write_edit_bash():
    """Simulate _fast_reply_with_tools filtering against a full tool registry."""
    class _Tool:
        def __init__(self, name: str):
            self.name = name

    core_tools = [
        _Tool("datetime"),
        _Tool("read"),
        _Tool("write"),
        _Tool("edit"),
        _Tool("bash"),
    ]
    allowed = SOCIAL_CHAT_TOOL_NAMES
    filtered = [
        tool for tool in core_tools
        if str(getattr(tool, "name", "")).lower() in allowed
    ]
    names = {tool.name for tool in filtered}
    assert names == {"datetime"}
    assert "write" not in names
    assert "edit" not in names
    assert "bash" not in names
