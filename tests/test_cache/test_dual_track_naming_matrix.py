"""Dual-track cache naming/stats contract matrices (precise vs semantic)."""

from __future__ import annotations

import itertools

import pytest


def _precise():
    from RxyCode.RxyCode1_1_0.cache.precise_cache import PreciseCache

    cache = object.__new__(PreciseCache)
    cache._index = {}
    cache._cache_dir = None
    cache._index_file = None
    cache._save_index = lambda: None
    return cache


def _semantic():
    from RxyCode.RxyCode1_1_0.cache.semantic_cache import SemanticCache

    cache = object.__new__(SemanticCache)
    cache._index = []
    cache._cache_dir = None
    cache._index_file = None
    cache._save_index = lambda: None
    cache._similarity_threshold = 0.95
    return cache


_SYSTEMS = (
    "You are a helpful assistant.",
    "System prompt v2",
    "coding agent system",
)

_QUERIES = (
    "What is Python?",
    "解释 Python 是什么",
    "How do I read a file?",
    "列出项目结构",
    "Compare asyncio and threading",
)

_NAMESPACES = ("", "fast-reply", "session-abc", "build-mode", "plan-mode")

_TOOL_CALLS = ("", "read", '{"path":"README.md"}')


@pytest.mark.parametrize(
    ("sys_prompt", "query", "namespace"),
    itertools.product(_SYSTEMS, _QUERIES, _NAMESPACES),
)
def test_precise_key_includes_four_sha_segments(sys_prompt: str, query: str, namespace: str):
    cache = _precise()
    key = cache._make_key(sys_prompt, query, namespace=namespace)
    segments = key.split(":")
    assert len(segments) == 4
    assert all(len(seg) == 64 for seg in segments[:2])
    assert segments[2] == "" or len(segments[2]) == 64
    assert segments[3] == "" or len(segments[3]) == 64


@pytest.mark.parametrize(
    ("query_a", "query_b"),
    itertools.product(_QUERIES[:3], _QUERIES[2:]),
)
def test_precise_keys_differ_for_different_queries(query_a: str, query_b: str):
    cache = _precise()
    if query_a == query_b:
        pytest.skip("same query pair")
    k1 = cache._make_key("sys", query_a, "", "")
    k2 = cache._make_key("sys", query_b, "", "")
    assert k1 != k2


@pytest.mark.parametrize("namespace", _NAMESPACES)
def test_semantic_put_get_roundtrip_namespace(namespace: str):
    cache = _semantic()
    query = f"semantic query for {namespace or 'default'}"
    cache.put(query, "stable semantic answer payload", namespace=namespace, ttl=60)
    hit = cache.get(query, namespace=namespace)
    assert hit is not None
    assert hit["response"] == "stable semantic answer payload"
    assert hit["cache_type"] == "semantic"


@pytest.mark.parametrize(
    ("query", "tool_ns"),
    itertools.product(_QUERIES[:4], _TOOL_CALLS),
)
def test_precise_put_labels_cache_type_precise(query: str, tool_ns: str):
    cache = _precise()
    cache.put("sys", query, "resp", ttl=30, namespace=tool_ns)
    hit = cache.get("sys", query, namespace=tool_ns)
    assert hit is not None
    assert hit["cache_type"] == "precise"
    assert hit["from_cache"] is True


@pytest.mark.parametrize("namespace", _NAMESPACES)
def test_semantic_stats_track_namespace(namespace: str):
    cache = _semantic()
    cache.put("q", "stable semantic answer payload", namespace=namespace, ttl=30)
    stats = cache.get_stats()
    assert stats["total_entries"] >= 1
    assert stats["total_hits"] >= 0
