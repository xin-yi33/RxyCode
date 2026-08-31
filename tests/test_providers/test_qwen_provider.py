"""Qwen provider 行为测试（A17 补全：§7.7 四档）。"""

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelPricing
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


def test_substring_qwen_model_name_not_matched():
    """§7.7 ③：仅 qwen/qwen2/qwen3 前缀命中；my-qwen-model 等子串不误判（DC1）。"""
    p = providers.resolve(
        {"base_url": "https://relay.example/v1", "model_name": "my-qwen-model"}
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


# ---- A17 补全：§7.7 ③ 四档能力 ----


@pytest.mark.parametrize("name", ["qwen3.7-plus", "qwen3.7-max", "qwen3.7-flash"])
def test_37_series_max_output_65536(name):
    """§7.7 问 2：3.7 三主力 max_output_tokens=65_536。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.max_output_tokens == 65_536


def test_38_preview_max_output_not_found():
    """§7.7 问 2：3.8 未找到官方 max output 整数 → None。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.max_output_tokens is None


@pytest.mark.parametrize("name", ["qwen3.7-plus", "qwen3.7-max", "qwen3.7-flash"])
def test_37_series_thinking_default_on(name):
    """§7.7 问 5：3.7 三主力混合思考默认开启（可关）。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.thinking_default_on is True


def test_38_preview_thinking_always_on():
    """§7.7 问 5：3.8 仅思考模式，无法关闭 → thinking_default_on=True。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.thinking_default_on is True


def test_plus_is_vision():
    """§7.7 ③ 主力 A：qwen3.7-plus 图/文/视频输入。"""
    caps = providers.resolve({"model_name": "qwen3.7-plus"}).capabilities(
        {"model_name": "qwen3.7-plus"}
    )
    assert caps.supports_vision is True


def test_max_is_text_only():
    """§7.7 ③ 主力 B：qwen3.7-max 动态 id 纯文本体验。"""
    caps = providers.resolve({"model_name": "qwen3.7-max"}).capabilities(
        {"model_name": "qwen3.7-max"}
    )
    assert caps.supports_vision is False


def test_flash_is_vision():
    """§7.7 ③ 主力 C：qwen3.7-flash 多模态。"""
    caps = providers.resolve({"model_name": "qwen3.7-flash"}).capabilities(
        {"model_name": "qwen3.7-flash"}
    )
    assert caps.supports_vision is True


def test_38_preview_vision_not_written_true():
    """§7.7 ③ 主力 D：3.8 视觉无型号页复核 → 不写入 True 作 API 能力证明。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.supports_vision is False


def test_38_preview_fc_not_found_none():
    """§7.7 ③ 主力 D：3.8 无型号页勾选表 → supports_function_calling=None（未找到）。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.supports_function_calling is None


def test_38_preview_builtin_tools_not_found_none():
    """§7.7 ③ 主力 D：3.8 内置工具未找到 → None（禁止继承写 True）。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.supports_builtin_tools is None


def test_38_preview_billing_token_plan():
    """§7.7 问 7b：3.8 仅 Token Plan Credits。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert caps.billing == "token_plan_credits"


@pytest.mark.parametrize("name", ["qwen3.7-plus", "qwen3.7-max", "qwen3.7-flash"])
def test_37_series_builtin_tools_true(name):
    """§7.7 ③ Q1 第 3 列：3.7 三主力内置工具=True（Harness 不得覆盖）。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.supports_builtin_tools is True
    assert caps.billing == ""


# ---- §7.7 问 7：定价按型号分条（CNY） ----


@pytest.mark.parametrize("name,inp,outp,cached", [
    ("qwen3.7-plus", 2.0, 8.0, 0.4),
    ("qwen3.7-max", 12.0, 36.0, 2.4),
    ("qwen3.7-flash", 0.2, 0.8, 0.04),
])
def test_per_model_pricing(name, inp, outp, cached):
    """§7.7 问 7a：按量定价按型号分条（CNY）。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok == inp
    assert caps.pricing.output_per_mtok == outp
    assert caps.pricing.cached_input_per_mtok == cached
    assert caps.pricing.as_of == "2026-08-02"
    assert caps.pricing.source_url


@pytest.mark.parametrize("name,create,hit", [
    ("qwen3.7-plus", 2.5, 0.2),
    ("qwen3.7-max", 15.0, 1.2),
    ("qwen3.7-flash", 0.25, 0.02),
])
def test_explicit_cache_pricing(name, create, hit):
    """§7.7 问 7a：显式缓存创建 / 显式命中价格结构化承载。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.pricing.cache_creation_per_mtok == create
    assert caps.pricing.explicit_cache_hit_per_mtok == hit


def test_38_preview_token_plan_pricing_none():
    """§7.7 问 7b：3.8 仅 Token Plan（Credits），禁止填 3.7-max 的 12/36 → None。"""
    caps = providers.resolve({"model_name": "qwen3.8-max-preview"}).capabilities(
        {"model_name": "qwen3.8-max-preview"}
    )
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok is None
    assert caps.pricing.output_per_mtok is None
    assert caps.pricing.cached_input_per_mtok is None
    assert caps.pricing.source_url


# ---- §7.7 问 4：显式缓存创建映射 ----


def test_cache_write_nested_mapping():
    """§7.7 问 4：显式创建走 usage.prompt_tokens_details.cache_creation_input_tokens。"""
    caps = providers.resolve({"model_name": "qwen3.7-plus"}).capabilities(
        {"model_name": "qwen3.7-plus"}
    )
    assert caps.usage_fields.cache_write_nested == (
        ("prompt_tokens_details", "cache_creation_input_tokens"),
    )


# ---- §7.7 问 5：llm_kwargs enable_thinking ----


def test_llm_kwargs_enable_thinking():
    """§7.7 问 5：3.7 混合思考经 extra_body enable_thinking=True。"""
    p = providers.resolve({"model_name": "qwen3.7-plus"})
    caps = p.capabilities({"model_name": "qwen3.7-plus"})
    kwargs = p.llm_kwargs({"model_name": "qwen3.7-plus", "resolved_max_tokens": 8192}, caps)
    body = kwargs.get("extra_body") or {}
    assert body.get("enable_thinking") is True


def test_chat_fallback_omits_reasoning_effort_even_with_responses_caps():
    """Chat fallback must not keep Responses-only reasoning.effort."""
    provider = QwenProvider()
    responses_cfg = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen3.7-plus",
        "resolved_max_tokens": 32,
        "api_key": "k",
        "api_transport": "openai_responses",
        "effort": "balanced",
    }
    chat_cfg = {**responses_cfg, "api_transport": "openai_chat"}
    stale_caps = provider.capabilities(responses_cfg)
    kwargs = provider.llm_kwargs(chat_cfg, stale_caps)
    body = kwargs.get("extra_body") or {}
    assert "reasoning_effort" not in kwargs
    assert "enable_thinking" in body
    assert body.get("enable_thinking") is True


# ---- DC1：未知变体保守 ----


def test_unknown_qwen_variant_stays_conservative():
    """未调研型号不套用调研能力：仅 provider/usage/pricing 变化，能力字段保守。"""
    for name in ["qwen-plus", "qwen-unknown-variant", "qwen"]:
        caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
        assert caps.provider == "qwen"
        assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
        assert caps.max_output_tokens is None
        assert caps.supports_reasoning is False
        assert caps.prompt_variant == DEFAULT_CAPABILITIES.prompt_variant == "default"
