"""DeepSeek provider 行为测试."""

import pytest

from core import providers
from core.providers.deepseek import DeepSeekProvider


@pytest.mark.parametrize(
    "cfg",
    [
        {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-chat"},
        {"base_url": "https://relay.example/v1", "model_name": "deepseek-reasoner"},
        {"base_url": "https://api.DeepSeek.com", "model_name": "x"},
    ],
)
def test_matches_by_url_or_model_name(cfg):
    assert isinstance(providers.resolve(cfg), DeepSeekProvider)


def test_chat_model_keeps_sampling_and_tools():
    caps = providers.resolve(
        {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-chat"}
    ).capabilities({"model_name": "deepseek-chat"})
    assert caps.accepts_temperature is True
    assert caps.supports_function_calling is True
    assert caps.supports_reasoning is False
    assert caps.structured_output == "function_calling"


def test_reasoner_drops_sampling_keeps_tools():
    """§7.1: reasoner/thinking 模式忽略 temperature，仍支持 tools."""
    caps = providers.resolve(
        {
            "base_url": "https://api.deepseek.com/v1",
            "model_name": "deepseek-reasoner",
        }
    ).capabilities({"model_name": "deepseek-reasoner"})
    assert caps.supports_reasoning is True
    assert caps.accepts_temperature is False
    assert caps.supports_function_calling is True
    assert caps.structured_output == "function_calling"


def test_reasoner_llm_kwargs_omit_temperature():
    p = providers.resolve({"model_name": "deepseek-reasoner"})
    caps = p.capabilities({"model_name": "deepseek-reasoner"})
    kwargs = p.llm_kwargs({"model_name": "deepseek-reasoner"}, caps)
    assert "temperature" not in kwargs


def test_cache_read_uses_flat_field_only():
    p = providers.resolve({"model_name": "deepseek-chat"})
    caps = p.capabilities({"model_name": "deepseek-chat"})
    assert p.extract_cache_read({"prompt_cache_hit_tokens": 42}, caps) == 42
    # DeepSeek Chat Completions 不用嵌套形式，即使出现也不该被误读
    assert (
        p.extract_cache_read(
            {"prompt_tokens_details": {"cached_tokens": 99}}, caps
        )
        == 0
    )


def test_user_override_beats_provider_default():
    p = providers.resolve({"model_name": "deepseek-chat"})
    caps = p.capabilities({"model_name": "deepseek-chat", "context_window": 32_000})
    assert caps.context_window == 32_000


def test_context_window_is_not_the_global_256k():
    caps = providers.resolve({"model_name": "deepseek-chat"}).capabilities(
        {"model_name": "deepseek-chat"}
    )
    assert caps.context_window != 256_000, (
        "DeepSeek must not inherit the legacy global 256k window"
    )
    assert caps.context_window == 1_048_576
