"""ModelCapabilities 的默认值锁定测试。

这些默认值必须与 Phase A 之前的硬编码行为一致，否则所有未识别模型的行为
会静默改变。改默认值时必须同步改这里，并在 PR 里说明理由。
"""
from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
    UsageFieldMap,
)


def test_defaults_match_legacy_hardcoded_behaviour():
    c = DEFAULT_CAPABILITIES
    assert c.context_window == 256_000        # utils/streaming.py:47
    assert c.compaction_threshold == 232_000  # config/settings.py:299
    assert c.tokenizer == "tiktoken:o200k_base"  # agent_v2.py:207 gpt-4o
    assert c.supports_function_calling is True
    assert c.supports_prompt_cache is True
    assert c.structured_output == "function_calling"
    assert c.prompt_variant == "default"


def test_usage_fields_cover_both_legacy_probes():
    fields = DEFAULT_CAPABILITIES.usage_fields
    # agent_v2.py:163-200 原先盲试的两个字段都要在默认映射里
    assert "prompt_cache_hit_tokens" in fields.cache_read_flat
    assert ("prompt_tokens_details", "cached_tokens") in fields.cache_read_nested
    assert "reasoning_content" in fields.reasoning


def test_overrides_apply_known_fields_only():
    base = ModelCapabilities()
    merged = base.merged_with_overrides({
        "context_window": 64_000,
        "base_url": "http://example.com",   # 非能力字段，应被忽略
        "supports_reasoning": True,
    })
    assert merged.context_window == 64_000
    assert merged.supports_reasoning is True
    assert not hasattr(merged, "base_url")


def test_capabilities_are_frozen():
    import dataclasses
    import pytest
    c = ModelCapabilities()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.context_window = 1  # type: ignore[misc]


def test_usage_field_map_is_hashable():
    # frozen dataclass 用作 provider 单例的一部分，必须可哈希
    assert hash(UsageFieldMap()) == hash(UsageFieldMap())
