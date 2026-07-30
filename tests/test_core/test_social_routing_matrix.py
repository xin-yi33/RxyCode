"""Table-driven social-chat vs code-intent routing matrices (E1/E6/E7)."""

from __future__ import annotations

import itertools

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    AgentV2,
    CODE_MUTATING_TOOL_NAMES,
    PLAN_READONLY_TOOL_NAMES,
    SOCIAL_CHAT_TOOL_NAMES,
)


def _agent() -> AgentV2:
    return object.__new__(AgentV2)


_EMOTIONS = (
    "伤心", "难过", "不理我", "孤独", "郁闷", "好伤心", "很难过", "倾诉",
    "安慰", "在吗", "你好", "您好", "谢谢", "how are you", "i'm sad",
    "im sad", "feel sad", "lonely", "upset", "你却说", "你却报",
    "怎么又报错", "你说 error", "你说error", "you said error",
)

_PLAY_PHRASES = (
    "玩游戏", "陪我玩", "找我玩", "找朋友玩", "一起玩", "陪我玩游戏",
    "能陪我玩吗", "想玩游戏", "来玩游戏", "play with me",
)

_PREFIXES = ("", "今天", "刚才", "一直", "真的")

_SUFFIXES = ("", "好吗", "可以吗", "……")

_SOCIAL_POSITIVE = [
    f"{prefix}{emotion}{'，' if prefix and emotion else ''}{play}{suffix}".strip()
    for prefix, emotion, play, suffix in itertools.product(
        _PREFIXES, _EMOTIONS, _PLAY_PHRASES, _SUFFIXES
    )
    if emotion or play
]

_CODE_VERBS = ("写", "开发", "创建", "实现", "构建", "编写", "制作", "设计", "build", "create")
_CODE_NOUNS = (
    "游戏", "脚本", "程序", "网站", "爬虫", "机器人", "算法", "app", "project", "module",
)
_CODE_SCOPES = ("一个", "完整", "整个", "全新", "小型", "full", "complete")

_CODE_NEGATIVE = [
    f"请{verb}{scope}{noun}并保存到文件"
    for verb, scope, noun in itertools.product(_CODE_VERBS, _CODE_SCOPES, _CODE_NOUNS)
]

_SIMPLE_POSITIVE = [
    "你好",
    "what happened?",
    "happened",
    "descriptive text only",
    "解释一下 Python 是什么",
    "Python 是什么？",
    "1+1等于几",
    "谢谢你的帮助",
    "在吗",
    "how are you today",
] + [
    f"{emotion}但只是聊天"
    for emotion in _EMOTIONS[:12]
]

_COMPLEX_NEGATIVE = [
    "分步重构整个项目的认证模块",
    "step-by-step migrate the entire codebase",
    "搭建完整的新项目框架",
    "create a full complete application from scratch",
] + [
    f"{verb}{scope}{noun}分阶段逐步完成"
    for verb, scope, noun in itertools.product(
        ("重构", "迁移", "重写"), ("整个", "全部"), ("项目", "系统")
    )
]


@pytest.mark.parametrize("text", _SOCIAL_POSITIVE)
def test_social_play_matrix_is_social_and_simple(text: str):
    agent = _agent()
    assert agent._is_social_chat(text) is True, text
    assert agent._is_simple_query(text) is True, text
    assert agent._resolve_fast_reply_tool_allowlist(text, None) == SOCIAL_CHAT_TOOL_NAMES


@pytest.mark.parametrize("text", _CODE_NEGATIVE)
def test_code_intent_matrix_is_not_social(text: str):
    agent = _agent()
    assert agent._is_social_chat(text) is False, text


@pytest.mark.parametrize("text", _SIMPLE_POSITIVE)
def test_simple_query_matrix_stays_simple(text: str):
    agent = _agent()
    assert agent._is_simple_query(text) is True, text


@pytest.mark.parametrize("text", _COMPLEX_NEGATIVE)
def test_complex_query_matrix_not_simple(text: str):
    agent = _agent()
    assert agent._is_simple_query(text) is False, text


@pytest.mark.parametrize("text", _SOCIAL_POSITIVE[:60])
def test_social_allowlist_excludes_mutating_tools(text: str):
    allowlist = _agent()._resolve_fast_reply_tool_allowlist(text, None)
    assert allowlist is not None
    assert CODE_MUTATING_TOOL_NAMES.isdisjoint(allowlist)


@pytest.mark.parametrize("text", _CODE_NEGATIVE[:40])
def test_code_intent_keeps_full_or_explicit_allowlist(text: str):
    explicit = frozenset({"read", "write", "bash"})
    assert _agent()._resolve_fast_reply_tool_allowlist(text, explicit) == explicit


@pytest.mark.parametrize(
    ("mode_hint", "text"),
    itertools.product(
        ("build", "plan", "compose"),
        _SOCIAL_POSITIVE[:30],
    ),
)
def test_social_under_any_mode_hint_stays_social(mode_hint: str, text: str):
    del mode_hint  # routing helper is mode-agnostic; mode applied later in run()
    assert _agent()._is_social_chat(text) is True


@pytest.mark.parametrize("tool", sorted(PLAN_READONLY_TOOL_NAMES))
def test_plan_readonly_tools_never_mutating(tool: str):
    assert tool not in CODE_MUTATING_TOOL_NAMES
