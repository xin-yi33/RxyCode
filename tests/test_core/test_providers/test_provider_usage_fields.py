"""DEFAULT usage-field map must preserve every legacy cache-read source."""
from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES
from RxyCode.RxyCode1_1_0.core import providers


def test_default_map_includes_langchain_normalized_cache_read():
    caps = DEFAULT_CAPABILITIES
    assert ("input_token_details", "cache_read") in caps.usage_fields.cache_read_nested


def test_base_provider_extracts_langchain_normalized_cache_read():
    caps = DEFAULT_CAPABILITIES
    provider = providers.resolve(
        {"base_url": "https://api.openai.com/v1", "model_name": "gpt-4o"}
    )
    assert (
        provider.extract_cache_read(
            {"input_token_details": {"cache_read": 123}, "prompt_tokens": 1000},
            caps,
        )
        == 123
    )


def test_default_flat_deepseek_field_still_wins():
    caps = DEFAULT_CAPABILITIES
    provider = providers.resolve(
        {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-v4-flash"}
    )
    usage = {"prompt_cache_hit_tokens": 42, "input_token_details": {"cache_read": 7}}
    assert provider.extract_cache_read(usage, caps) == 42
