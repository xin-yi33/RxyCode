"""Anthropic provider 行为测试."""

import pytest

from core import providers
from core.providers.anthropic import AnthropicProvider
from core.providers.openai import OpenAIProvider


@pytest.mark.parametrize(
    "cfg",
    [
        {
            "base_url": "https://api.anthropic.com/v1",
            "model_name": "claude-opus-5",
        },
        {
            "base_url": "https://relay.example/v1",
            "model_name": "claude-sonnet-5",
        },
        {"base_url": "https://example.com", "model_name": "claude-haiku-4-5"},
    ],
)
def test_matches_by_url_or_model_name(cfg):
    assert isinstance(providers.resolve(cfg), AnthropicProvider)


def test_unknown_model_does_not_match_anthropic():
    p = providers.resolve(
        {"base_url": "https://unknown.example/v1", "model_name": "mystery-1"}
    )
    assert isinstance(p, OpenAIProvider)


def test_uses_claude_prompt_variant():
    caps = providers.resolve({"model_name": "claude-opus-5"}).capabilities(
        {"model_name": "claude-opus-5"}
    )
    assert caps.prompt_variant == "claude"


def test_cache_read_uses_flat_cache_read_input_tokens():
    p = providers.resolve({"model_name": "claude-opus-5"})
    caps = p.capabilities({"model_name": "claude-opus-5"})
    assert p.extract_cache_read({"cache_read_input_tokens": 512}, caps) == 512
    assert (
        p.extract_cache_read(
            {"prompt_tokens_details": {"cached_tokens": 99}}, caps
        )
        == 0
    )


def test_supports_prompt_cache_reflects_explicit_cache_control():
    """§7.8：Anthropic 需显式 cache_control，与 OpenAI 自动缓存语义不同。"""
    caps = providers.resolve({"model_name": "claude-opus-5"}).capabilities(
        {"model_name": "claude-opus-5"}
    )
    assert caps.supports_prompt_cache is True


def test_opus_context_window_is_1m_not_legacy_256k():
    caps = providers.resolve({"model_name": "claude-opus-5"}).capabilities(
        {"model_name": "claude-opus-5"}
    )
    assert caps.context_window == 1_000_000
    assert caps.context_window != 256_000


def test_haiku_context_window_is_200k():
    caps = providers.resolve({"model_name": "claude-haiku-4-5"}).capabilities(
        {"model_name": "claude-haiku-4-5"}
    )
    assert caps.context_window == 200_000


def test_supports_reasoning_and_tools():
    caps = providers.resolve({"model_name": "claude-opus-5"}).capabilities(
        {"model_name": "claude-opus-5"}
    )
    assert caps.supports_reasoning is True
    assert caps.supports_function_calling is True


def test_user_override_beats_provider_default():
    p = providers.resolve({"model_name": "claude-opus-5"})
    caps = p.capabilities({"model_name": "claude-opus-5", "context_window": 32_000})
    assert caps.context_window == 32_000
