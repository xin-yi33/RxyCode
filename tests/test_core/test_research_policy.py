import pytest

from RxyCode.RxyCode1_1_0.core.research_policy import (
    extract_research_urls,
    get_research_policy,
    is_successful_research_fetch,
    normalize_research_url,
    research_failure_message,
)


def test_chinese_freshness_query_requires_web_and_bypasses_cache():
    policy = get_research_policy("今天 Python 最新版本是什么？")
    assert policy.requires_web is True
    assert policy.cache_read_allowed is False
    assert policy.cache_write_allowed is False
    assert policy.citations_required is True


def test_english_freshness_query_requires_web():
    policy = get_research_policy("What is the current stable Node.js release?")
    assert policy.requires_web is True
    assert policy.cache_read_allowed is False


@pytest.mark.parametrize(
    "query",
    [
        "Search the web for the Python documentation",
        "Search for the Python documentation",
        "Please look up online how this API works",
        "请联网搜索 Python 官方文档",
        "帮我搜索 Python 官方文档",
        "上海明天的天气怎么样？",
        "Who is the president of France?",
        "What regulations apply to this visa?",
        "What is the USD to CNY exchange rate?",
    ],
)
def test_explicit_web_intent_and_volatile_domains_require_web(query):
    assert get_research_policy(query).requires_web is True


def test_stable_knowledge_query_can_use_answer_cache():
    policy = get_research_policy("Explain what a Python decorator is")
    assert policy.requires_web is False
    assert policy.cache_read_allowed is True
    assert policy.cache_write_allowed is True


def test_bare_algorithm_search_does_not_force_web_research():
    assert get_research_policy("Implement binary search in Python").requires_web is False
    assert get_research_policy("Convert one to two fields").requires_web is False


def test_research_urls_are_deduplicated_normalized_and_private_hosts_rejected():
    urls = extract_research_urls(
        "https://Example.com/source). https://example.com/source "
        "http://127.0.0.1/admin https://localhost/private"
    )
    assert urls == ["https://example.com/source"]
    assert normalize_research_url("https://user:secret@example.com/") is None


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("Fetched source body", True),
        ("", False),
        ("[error fetching https://example.com: timeout]", False),
        ("[blocked: policy]", False),
        ("[rejected: approval denied]", False),
        ("[tool timeout: webfetch exceeded 30s]", False),
        ("[search error: all engines timed out]", False),
        ("None", False),
    ],
)
def test_research_fetch_success_requires_real_content(result, expected):
    assert is_successful_research_fetch(result) is expected


def test_research_failure_message_refuses_to_guess():
    message = research_failure_message("all engines timed out")
    assert "could not verify" in message
    assert "will not guess" in message
    assert "timed out" in message
