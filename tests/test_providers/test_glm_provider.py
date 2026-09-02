"""GLMProvider 显式能力测试（A14）：匹配、能力声明、定价、usage 提取。

数值全部来自 A0 批 4 调研报告（§7.4，2026-08-02 三方审计通过）。
"""

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelPricing
from core import providers
from core.providers.glm import GLMProvider

_BIGMODEL = "https://open.bigmodel.cn/api/paas/v4/"
_ARK = "https://ark.cn-beijing.volces.com/api/coding/v3"


def _resolve(model_name: str, base_url: str = _BIGMODEL):
    cfg = {"base_url": base_url, "model_name": model_name, "resolved_max_tokens": 8192}
    return providers.resolve(cfg), cfg


def _caps(model_name: str, base_url: str = _BIGMODEL):
    p, cfg = _resolve(model_name, base_url)
    return p.capabilities(cfg)


# ---- 匹配正反例 ---------------------------------------------------------


@pytest.mark.parametrize("cfg", [
    {"base_url": _BIGMODEL, "model_name": "glm-5.2"},
    {"base_url": "https://open.bigmodel.cn/api/paas/v4/", "model_name": "glm-4.7"},
    {"base_url": "https://api.zhipu.ai/v4", "model_name": "x"},
])
def test_matches_bigmodel_or_zhipu_url(cfg):
    assert isinstance(providers.resolve(cfg), GLMProvider)


def test_matches_ark_with_glm_name():
    # Ark 双条件：URL 含 volces.com 且模型名含 glm
    assert isinstance(
        providers.resolve({"base_url": _ARK, "model_name": "glm-5.1"}),
        GLMProvider,
    )


def test_ark_doubao_not_matched():
    # 关键反例：Ark 上豆包不得被抢成 GLM
    p = providers.resolve({"base_url": _ARK, "model_name": "doubao-seed-2.1-turbo"})
    assert not isinstance(p, GLMProvider)


def test_matches_glm_prefix_on_relay():
    assert isinstance(
        providers.resolve({"base_url": "https://relay.example/v1", "model_name": "glm-5.2"}),
        GLMProvider,
    )


@pytest.mark.parametrize("cfg", [
    {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-chat"},
    {"base_url": "https://api.openai.com/v1", "model_name": "gpt-5.6-sol"},
    {"base_url": "https://api.moonshot.cn/v1", "model_name": "kimi-k3"},
])
def test_does_not_steal_other_models(cfg):
    assert not isinstance(providers.resolve(cfg), GLMProvider)


def test_resolve_returns_glm_for_glm_config():
    p = providers.resolve({"base_url": _BIGMODEL, "model_name": "glm-5.2"})
    assert isinstance(p, GLMProvider)


# ---- §7.4 ③：glm-5.2 主骨架 ---------------------------------------------


def test_glm52_section_7_4_values():
    """§7.4 ③：5.2 的 context/compaction/max_output/vision/reasoning/variant/tokenizer。"""
    caps = _caps("glm-5.2")
    assert caps.provider == "glm"
    # 项目侧启发式（官方「1M」字面；精确整数未找到）
    assert caps.context_window == 1_048_576
    assert caps.compaction_threshold == 943_000
    assert caps.max_output_tokens == 131_072
    assert caps.supports_function_calling is True
    assert caps.supports_vision is False
    assert caps.supports_reasoning is True
    assert caps.thinking_default_on is True
    assert caps.supports_prompt_cache is True
    assert caps.prompt_variant == "glm-5.2"
    assert caps.tokenizer == "chars:1.5"


def test_glm52_effort_presets():
    """§7.4 ③：5.2 顶层 reasoning_effort（max 默认推荐）。"""
    caps = _caps("glm-5.2")
    assert caps.effort_presets == {"fast": "low", "balanced": "high", "deep": "max"}


def test_glm_opencode_go_strips_vendor_extras():
    """Console Go rejects GLM-native extras as Extra inputs are not permitted."""
    p, cfg = _resolve("glm-5.2", "https://opencode.ai/zen/go/v1")
    kwargs = p.llm_kwargs({**cfg, "api_key": "sk-test", "effort": "balanced"}, _caps("glm-5.2"))
    assert "reasoning_effort" not in kwargs
    body = kwargs.get("extra_body") or {}
    assert "clear_thinking" not in body
    assert "thinking" not in body


def test_glm_keeps_temperature():
    """§7.4 问 5：未找到 thinking 拒绝 temperature 明文 → accepts_temperature=True。"""
    caps = _caps("glm-5.2")
    assert caps.accepts_temperature is True
    p, cfg = _resolve("glm-5.2")
    kwargs = p.llm_kwargs(cfg, caps)
    assert "temperature" in kwargs


# ---- §7.4 问 2：窗口分档（项目侧启发式） ---------------------------------


@pytest.mark.parametrize("name", ["glm-5.1", "glm-5", "glm-5-turbo", "glm-4.7", "glm-4.6"])
def test_200k_series_window(name):
    caps = _caps(name)
    assert caps.context_window == 200_000
    assert caps.compaction_threshold == 180_000
    assert caps.supports_reasoning is True
    assert caps.thinking_default_on is True


def test_128k_series_window():
    caps = _caps("glm-4.5")
    assert caps.context_window == 128_000
    assert caps.compaction_threshold == 115_200
    assert caps.max_output_tokens == 98_304


def test_5v_turbo_is_vision():
    caps = _caps("glm-5v-turbo")
    assert caps.supports_vision is True


def test_non_52_has_no_effort_presets():
    """§7.4 ③：reasoning_effort 仅 glm-5.2+。"""
    for name in ["glm-5.1", "glm-4.7"]:
        assert _caps(name).effort_presets == {}


# ---- §7.4 问 4：usage 嵌套 cached_tokens ---------------------------------


def test_cache_read_uses_nested_cached_tokens():
    """§7.4 问 4：usage.prompt_tokens_details.cached_tokens（嵌套），非平铺。"""
    p = providers.resolve({"base_url": _BIGMODEL, "model_name": "glm-5.2"})
    caps = p.capabilities({"base_url": _BIGMODEL, "model_name": "glm-5.2"})
    assert caps.usage_fields.cache_read_flat == ()
    assert caps.usage_fields.cache_read_nested == (("prompt_tokens_details", "cached_tokens"),)
    assert caps.usage_fields.reasoning == ()
    assert p.extract_cache_read(
        {"prompt_tokens_details": {"cached_tokens": 64}}, caps
    ) == 64
    # 平铺 prompt_cache_hit_tokens / cached_tokens 不应被误读
    assert p.extract_cache_read({"prompt_cache_hit_tokens": 128}, caps) == 0
    assert p.extract_cache_read({"cached_tokens": 99}, caps) == 0


# ---- §7.4 问 7：定价未找到 → 显式 None -----------------------------------


def test_pricing_all_none_with_source_url():
    """§7.4 问 7：精确单价未找到 → 全部 None + source_url=G13。"""
    caps = _caps("glm-5.2")
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok is None
    assert caps.pricing.output_per_mtok is None
    assert caps.pricing.cached_input_per_mtok is None
    assert caps.pricing.as_of == "2026-08-02"
    assert "bigmodel" in caps.pricing.source_url


# ---- DC1 / 用户覆盖 ------------------------------------------------------


def test_user_override_beats_provider_default():
    p = providers.resolve({"base_url": _BIGMODEL, "model_name": "glm-5.2"})
    caps = p.capabilities({"base_url": _BIGMODEL, "model_name": "glm-5.2",
                           "context_window": 64_000})
    assert caps.context_window == 64_000


def test_unknown_glm_variant_stays_conservative():
    """未调研型号不套用调研能力：仅 provider/usage/pricing 变化，能力字段保守。"""
    for name in ["glm-3.5", "glm-unknown-variant", "glm-x"]:
        caps = _caps(name)
        assert caps.provider == "glm"
        assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
        assert caps.max_output_tokens is None
        assert caps.supports_reasoning is False
        assert caps.effort_presets == {}
        assert caps.prompt_variant == DEFAULT_CAPABILITIES.prompt_variant == "default"


def test_unknown_model_falls_back_to_defaults():
    """DC1：未知模型（非 glm）仍拿到与改造前一致的默认能力。"""
    cfg = {"base_url": "https://relay.example/v1", "model_name": "mystery-1"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    assert caps == DEFAULT_CAPABILITIES
