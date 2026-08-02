"""Qwen provider 行为测试."""

import pytest

from core import providers
from core.providers.openai import OpenAIProvider
from core.providers.qwen import QwenProvider


@pytest.mark.parametrize(
    "cfg",
    [
        {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen3.7-plus",
        },
        {
            "base_url": "https://ws.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen3.7-max",
        },
        {
            "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "model_name": "qwen3.8-max-preview",
        },
        {"base_url": "https://relay.example/v1", "model_name": "qwen3.7-flash"},
    ],
)
def test_matches_by_url_or_model_name(cfg):
    assert isinstance(providers.resolve(cfg), QwenProvider)


def test_unknown_model_does_not_match_qwen():
    p = providers.resolve(
        {"base_url": "https://unknown.example/v1", "model_name": "mystery-1"}
    )
    assert isinstance(p, OpenAIProvider)


def test_supports_function_calling():
    caps = providers.resolve({"model_name": "qwen3.7-plus"}).capabilities(
        {"model_name": "qwen3.7-plus"}
    )
    assert caps.supports_function_calling is True
    assert caps.structured_output == "function_calling"


def test_cache_read_uses_nested_cached_tokens():
    p = providers.resolve({"model_name": "qwen3.7-plus"})
    caps = p.capabilities({"model_name": "qwen3.7-plus"})
    assert (
        p.extract_cache_read(
            {"prompt_tokens_details": {"cached_tokens": 128}}, caps
        )
        == 128
    )
    assert p.extract_cache_read({"prompt_cache_hit_tokens": 99}, caps) == 0


def test_tokenizer_uses_chars_heuristic():
    caps = providers.resolve({"model_name": "qwen3.7-plus"}).capabilities(
        {"model_name": "qwen3.7-plus"}
    )
    assert caps.tokenizer == "chars:0.7"


def test_context_window_1m_for_37_series():
    caps = providers.resolve({"model_name": "qwen3.7-plus"}).capabilities(
        {"model_name": "qwen3.7-plus"}
    )
    assert caps.context_window == 1_000_000
    assert caps.context_window != 256_000


def test_context_window_38_preview_uses_codex_metadata():
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.context_window == 983_616
    assert caps.prompt_variant == "qwen3.8-max-preview"


def test_supports_reasoning_and_prompt_cache():
    caps = providers.resolve({"model_name": "qwen3.7-max"}).capabilities(
        {"model_name": "qwen3.7-max"}
    )
    assert caps.supports_reasoning is True
    assert caps.supports_prompt_cache is True


def test_user_override_beats_provider_default():
    p = providers.resolve({"model_name": "qwen3.7-plus"})
    caps = p.capabilities({"model_name": "qwen3.7-plus", "context_window": 64_000})
    assert caps.context_window == 64_000
