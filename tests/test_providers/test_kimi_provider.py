"""KimiProvider 显式能力测试（A13）：匹配、能力声明、定价、usage 提取。

数值全部来自 A0 批 3 调研报告（§7.3，2026-08-02 三方审计通过）。
"""

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelPricing
from core import providers
from core.providers.kimi import KimiProvider

_MOONSHOT_CN = "https://api.moonshot.cn/v1"
_MOONSHOT_AI = "https://api.moonshot.ai/v1"


def _resolve(model_name: str):
    cfg = {"base_url": _MOONSHOT_CN, "model_name": model_name, "resolved_max_tokens": 8192}
    return providers.resolve(cfg), cfg


def _caps(model_name: str):
    p, cfg = _resolve(model_name)
    return p.capabilities(cfg)


# ---- 匹配正反例 ---------------------------------------------------------


@pytest.mark.parametrize("cfg", [
    {"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"},
    {"base_url": _MOONSHOT_AI, "model_name": "kimi-k2.7-code"},
    {"base_url": "https://relay.example/v1", "model_name": "kimi-k2.6"},
])
def test_matches_by_url_or_model_name(cfg):
    assert isinstance(providers.resolve(cfg), KimiProvider)


@pytest.mark.parametrize("cfg", [
    {"base_url": "https://api.deepseek.com/v1", "model_name": "deepseek-chat"},
    {"base_url": "https://api.openai.com/v1", "model_name": "gpt-5.6-sol"},
    {"base_url": "https://ark.cn-beijing.volces.com/api/coding/v3", "model_name": "doubao-seed-2.1-turbo"},
    {"base_url": "https://ark.cn-beijing.volces.com/api/coding/v3", "model_name": "glm-5.2"},
])
def test_does_not_steal_other_models(cfg):
    assert not isinstance(providers.resolve(cfg), KimiProvider)


def test_resolve_returns_kimi_for_kimi_config():
    p = providers.resolve({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"})
    assert isinstance(p, KimiProvider)


# ---- §7.3 问 2/5/6：kimi-k3 旗舰 ----------------------------------------


def test_k3_section_7_3_values():
    """§7.3 ③：k3 的 context/compaction/max_output/vision/reasoning/variant/tokenizer。"""
    caps = _caps("kimi-k3")
    assert caps.provider == "kimi"
    assert caps.context_window == 1_048_576
    assert caps.compaction_threshold == 943_000
    assert caps.max_output_tokens == 131_072
    assert caps.supports_vision is True
    assert caps.supports_reasoning is True
    assert caps.thinking_default_on is True
    assert caps.supports_prompt_cache is True
    assert caps.supports_function_calling is True
    assert caps.prompt_variant == "kimi-k3"
    assert caps.tokenizer == "chars:1.75"


def test_k3_effort_presets():
    """§7.3 问 5：k3 顶层 reasoning_effort low/high/max，无 medium。"""
    caps = _caps("kimi-k3")
    assert caps.effort_presets == {"fast": "low", "balanced": "high", "deep": "max"}


def test_kimi_fixed_temperature_not_injected():
    """§7.3 问 5：kimi 采样参数固定，勿显式传 temperature。"""
    caps = _caps("kimi-k3")
    assert caps.accepts_temperature is False
    p, cfg = _resolve("kimi-k3")
    kwargs = p.llm_kwargs(cfg, caps)
    assert "temperature" not in kwargs


def test_fixed_sampling_params_never_injected():
    """§7.3 问 5：top_p/presence/frequency 等固定采样参数不得显式发送。"""
    p, cfg = _resolve("kimi-k3")
    caps = p.capabilities(cfg)
    kwargs = p.llm_kwargs(cfg, caps)
    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
        assert key not in kwargs, f"{key} must not be injected for Kimi"
    # A21 起：kimi-k3 有 effort_presets（§7.3 问 5）→ 默认档 balanced 注入 reasoning_effort
    assert kwargs.get("reasoning_effort") == "high"


# ---- §7.3 问 2/5：k2.7-code / highspeed / k2.6 -------------------------


@pytest.mark.parametrize("name", ["kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"])
def test_k2x_context_and_thinking(name):
    """§7.3 问 2/5：k2.7 系与 k2.6 均为 262,144，始终推理。"""
    caps = _caps(name)
    assert caps.context_window == 262_144
    assert caps.compaction_threshold == 236_000
    assert caps.supports_reasoning is True
    assert caps.thinking_default_on is True


def test_k2x_has_no_effort_presets():
    """§7.3 问 5：k2.7/k2.6 不支持 reasoning_effort。"""
    for name in ["kimi-k2.7-code", "kimi-k2.6"]:
        assert _caps(name).effort_presets == {}


# ---- §7.3 问 7：定价按型号分条（CNY） -----------------------------------


@pytest.mark.parametrize("name,inp,cached,outp", [
    ("kimi-k3", 20.00, 2.00, 100.00),
    ("kimi-k2.7-code", 6.50, 1.30, 27.00),
    ("kimi-k2.7-code-highspeed", 13.00, 2.60, 54.00),
    ("kimi-k2.6", 6.50, 1.10, 27.00),
])
def test_per_model_pricing(name, inp, cached, outp):
    """§7.3 问 7：定价按型号分条；highspeed 不得与普通 k2.7-code 共用。"""
    caps = _caps(name)
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok == inp
    assert caps.pricing.cached_input_per_mtok == cached
    assert caps.pricing.output_per_mtok == outp
    assert caps.pricing.as_of == "2026-08-02"
    assert caps.pricing.source_url


def test_unknown_kimi_model_gets_explicit_none_pricing():
    """未调研型号（如 kimi-k2.5 / moonshot-v1）→ 价格显式 None，不得静默当 0。"""
    caps = _caps("kimi-k2.5")
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok is None
    assert caps.pricing.source_url


def test_unknown_kimi_variant_stays_conservative():
    """未调研型号不套用调研能力：仅 provider/usage/pricing 变化，能力字段保守。"""
    for name in ["kimi-k2.5", "moonshot-v1-32k", "kimi-unknown-variant"]:
        caps = _caps(name)
        assert caps.provider == "kimi"
        assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
        assert caps.max_output_tokens is None
        assert caps.supports_reasoning is False
        assert caps.supports_vision is False
        assert caps.effort_presets == {}
        # 未调研变体不套用专属 prompt_variant（与 A12 一致：保持 "default"）
        assert caps.prompt_variant == DEFAULT_CAPABILITIES.prompt_variant == "default"


# ---- §7.3 问 4：usage 字段 cached_tokens（非 prompt_cache_hit_tokens） ----


def test_cache_read_uses_flat_cached_tokens():
    """§7.3 问 4：usage.cached_tokens（平铺），非 prompt_cache_hit_tokens。"""
    p = providers.resolve({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"})
    caps = p.capabilities({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"})
    assert caps.usage_fields.cache_read_flat == ("cached_tokens",)
    assert caps.usage_fields.cache_read_nested == ()
    # §7.3 问 4/5：缓存写入价与 reasoning 计数官方未找到 → 嵌套路径显式清空
    assert caps.usage_fields.cache_write_nested == ()
    assert caps.usage_fields.reasoning_nested == ()
    assert p.extract_cache_read({"cached_tokens": 42}, caps) == 42
    # 嵌套 / prompt_cache_hit_tokens 不应被误读
    assert p.extract_cache_read({"prompt_cache_hit_tokens": 99}, caps) == 0
    assert p.extract_cache_read({"prompt_tokens_details": {"cached_tokens": 99}}, caps) == 0


# ---- DC1 / 用户覆盖 ------------------------------------------------------


def test_user_override_beats_provider_default():
    p = providers.resolve({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"})
    caps = p.capabilities({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3",
                           "context_window": 128_000})
    assert caps.context_window == 128_000


def test_context_window_is_not_the_global_256k():
    caps = _caps("kimi-k3")
    assert caps.context_window != 256_000
    assert caps.context_window == 1_048_576


def test_unknown_model_falls_back_to_defaults():
    """DC1：未知模型（非 kimi）仍拿到与改造前一致的默认能力。"""
    cfg = {"base_url": "https://relay.example/v1", "model_name": "mystery-1"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    assert caps == DEFAULT_CAPABILITIES


# ---- 2026-09-23 流式思维链缺失回归 --------------------------------------


def test_k3_stream_reasoning_content_extracted():
    """2026-09-23 回归：kimi-k3 流式轮次思维链缺失。

    根因：_KIMI_USAGE.reasoning=() 导致 BaseProvider.extract_reasoning 的
    字段循环为空，流式 delta 里的 reasoning_content 永远取不到
    （探针证据：tui.reasoning.emit 缺失 + session.final.thinking thinking_len=0）。
    Kimi 官方 API 的 reasoning 就在 delta/message 的 reasoning_content 字段
    （见 core/providers/kimi.py 模块 docstring §7.3），usage_fields.reasoning
    是**内容**字段映射（config/model_capabilities.py UsageFieldMap.reasoning：
    「推理/思考内容所在字段（在 delta 或 message 上）」），不是 usage 计数路径。
    """
    from types import SimpleNamespace

    p = providers.resolve({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"})
    caps = p.capabilities({"base_url": _MOONSHOT_CN, "model_name": "kimi-k3"})
    # 字段映射必须包含 reasoning_content（否则流式提取恒为空）
    assert "reasoning_content" in caps.usage_fields.reasoning
    # delta 携带 reasoning_content 时必须取出
    delta = SimpleNamespace(reasoning_content="让我想想…", content=None, tool_calls=None)
    assert p.extract_reasoning(delta, caps) == "让我想想…"
    # 无 reasoning 的 delta 返回空串（不误判）
    empty = SimpleNamespace(reasoning_content="", content="你好", tool_calls=None)
    assert p.extract_reasoning(empty, caps) == ""


def test_k3_via_third_party_relay_also_extracts():
    """kimi 模型经第三方中转（如 api.arc-bench.com）时同样命中提取。

    用户实际链路：custom-api-arc-bench-com/kimi-k3 → matches() 按模型名命中
    KimiProvider → 同一份 capabilities → 同一个 bug/同一个修复。
    """
    from types import SimpleNamespace

    cfg = {"base_url": "https://api.arc-bench.com/v1", "model_name": "kimi-k3"}
    p = providers.resolve(cfg)
    assert isinstance(p, KimiProvider)
    caps = p.capabilities(cfg)
    delta = SimpleNamespace(reasoning_content="中转站的思维链", content=None, tool_calls=None)
    assert p.extract_reasoning(delta, caps) == "中转站的思维链"
