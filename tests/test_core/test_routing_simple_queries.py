"""Regression tests for routing false-positives in _is_simple_query.

Bug (2026-07-21): a naive substring `in` check on English
code-intent keywords made "app" match inside "happened"/"happier"
and "script" match inside "descriptive". This routed plain chat
queries like "what happened?" into the full LangGraph plan-execute
pipeline, producing 43 sub-tasks and a ~240s hang instead of an
instant fast-path reply.

Fix: English keywords are now matched with word boundaries (\b),
so "app" no longer matches "happened".

These tests assert the CORRECT (post-fix) behaviour: plain conversational
queries stay on the fast path (True), while genuine build/code/file
requests still take the tool-capable pipeline (False).
"""
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2


def _classify(text: str) -> bool:
    # _is_simple_query is self-contained (no self state), so we can construct
    # the instance without running __init__ (which would build the LLM).
    agent = object.__new__(AgentV2)
    return agent._is_simple_query(text)


def test_what_happened_stays_simple():
    """The exact failing query: 'app' inside 'happened' must NOT trigger."""
    assert _classify("what happened？") is True
    assert _classify("what happened?") is True


def test_happier_stays_simple():
    """'app' inside 'happier' must not trigger the complex path."""
    assert _classify("i am happier now") is True


def test_generic_english_chat_stays_simple():
    """Other plain conversational English must stay on the fast path."""
    assert _classify("what is a decorator in python?") is True
    assert _classify("how are you today?") is True


def test_chinese_chat_stays_simple():
    assert _classify("Python 的 list 和 tuple 有什么区别？") is True


def test_code_generation_still_complex():
    """Genuine code/game generation must still use the tool pipeline."""
    assert _classify("帮我写一个跑酷小游戏") is False
    assert _classify("写一个算法") is False
    assert _classify("build a complete app") is False


def test_explicit_build_still_complex():
    assert _classify("帮我创建一个完整的Python项目") is False
    assert _classify("Build a complete REST API from scratch") is False


def test_file_operations_still_complex():
    """File ops require tools and must stay on the complex path."""
    assert _classify("read file.txt") is False
    assert _classify("write file output.py") is False


def test_partial_file_word_is_simple():
    """'read a file' without the standalone 'file' word must NOT over-match."""
    assert _classify("how to read a file") is True
