"""A22: DeepSeek v4 补全 —— v4-flash/pro 识别、能力、effort、thinking、回传契约。

数值来自 A0 §7.1（2026-08-02 三方审计通过）。
"""

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelPricing
from core import providers
from core.providers.deepseek import DeepSeekProvider


def _resolve(model_name: str):
    cfg = {"base_url": "https://api.deepseek.com", "model_name": model_name,
           "resolved_max_tokens": 8192}
    return providers.resolve(cfg), cfg


def _caps(model_name: str):
    p, cfg = _resolve(model_name)
    return p.capabilities(cfg)


# ---- 完成判据 2：v4 识别 / 能力 / effort / thinking 与 §7.1 一致 ------------


def test_gateway_prefixed_v41_flash_is_thinking_model():
    """OpenCode Go ids must not fall through as unknown variants (no thinking)."""
    caps = _caps("opencode-go/deepseek-v4.1-flash")
    assert caps.supports_reasoning is True
    assert caps.thinking_default_on is True
    assert caps.effort_presets["fast"] == "low"
    p = DeepSeekProvider()
    kwargs = p.llm_kwargs(
        {
            "model_name": "opencode-go/deepseek-v4.1-flash",
            "resolved_max_tokens": 8192,
            "effort": "fast",
        },
        caps,
    )
    assert (kwargs.get("extra_body") or {}).get("thinking", {}).get("type") == "enabled"
    assert kwargs.get("reasoning_effort") == "low"


def test_extract_reasoning_keeps_wire_chain_when_caps_say_no():
    """A mis-classified variant must still surface reasoning_content from the wire."""
    from dataclasses import replace

    from config.model_capabilities import UsageFieldMap

    caps = replace(
        DEFAULT_CAPABILITIES,
        supports_reasoning=False,
        usage_fields=UsageFieldMap(reasoning=("reasoning_content",)),
    )
    assert (
        DeepSeekProvider().extract_reasoning({"reasoning_content": "why search"}, caps)
        == "why search"
    )


@pytest.mark.parametrize("name", ["deepseek-v4-flash", "deepseek-v4-pro"])
def test_v4_matches(name):
    p = providers.resolve({"base_url": "https://api.deepseek.com", "model_name": name})
    assert isinstance(p, DeepSeekProvider)


def test_v4_context_and_output_s71():
    """§7.1 问 2：v4 1M context；max output 384K。"""
    for name in ("deepseek-v4-flash", "deepseek-v4-pro"):
        caps = _caps(name)
        assert caps.context_window == 1_048_576
        assert caps.max_output_tokens == 384_000


def test_v4_thinking_default_on_s71():
    """§7.1 问 5：v4 适配 thinking，默认开启，effort 默认 high（balanced→high）。"""
    for name in ("deepseek-v4-flash", "deepseek-v4-pro"):
        caps = _caps(name)
        assert caps.supports_reasoning is True
        assert caps.thinking_default_on is True
        assert caps.accepts_temperature is False
        assert caps.effort_presets == {"fast": "low", "balanced": "high", "deep": "max"}
        assert caps.effort_presets["balanced"] == "high"  # A21 默认档 balanced→high


def test_v4_tools_s71():
    """§7.1 问 3：v4 全系支持 Tool Calls。"""
    for name in ("deepseek-v4-flash", "deepseek-v4-pro"):
        assert _caps(name).supports_function_calling is True


def test_v4_prompt_variant():
    """§7.1：v4-flash/pro 专属 prompt_variant。"""
    assert _caps("deepseek-v4-flash").prompt_variant == "deepseek-v4-flash"
    assert _caps("deepseek-v4-pro").prompt_variant == "deepseek-v4-pro"


def test_v4_usage_fields_s71():
    """§7.1 问 4：缓存命中顶层 prompt_cache_hit_tokens；reasoning_content 平铺。"""
    for name in ("deepseek-v4-flash", "deepseek-v4-pro"):
        caps = _caps(name)
        assert caps.usage_fields.cache_read_flat == (
            "prompt_cache_hit_tokens",
            "cached_tokens",
        )
        assert caps.usage_fields.reasoning == ("reasoning_content",)


# ---- 完成判据 3：tools + reasoning_content 回传契约 ------------------------


def test_to_openai_messages_echoes_reasoning_content():
    """带 tools 的轮次必须回传 reasoning_content（§7.1 问 5；否则 400）。"""
    from langchain_core.messages import AIMessage, ToolMessage
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    ai = AIMessage(
        content="thinking then answer",
        tool_calls=[{"id": "call_1", "name": "fetch", "args": {"url": "x"}}],
        additional_kwargs={"reasoning_content": "chain of thought"},
    )
    out = AgentV2._to_openai_messages(
        [ai, ToolMessage(content="ok", tool_call_id="call_1")]
    )
    assert out[0]["role"] == "assistant"
    assert out[0]["reasoning_content"] == "chain of thought"
    assert out[0]["tool_calls"][0]["id"] == "call_1"


def test_to_openai_messages_reasoning_from_attr():
    """reasoning_content 也可从消息属性取（非 additional_kwargs 时）。"""
    from langchain_core.messages import AIMessage
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    ai = AIMessage(content="answer", reasoning_content="cot via attr")
    out = AgentV2._to_openai_messages([ai])
    assert out[0]["reasoning_content"] == "cot via attr"


def test_to_openai_messages_tool_round_without_reasoning():
    """带 tools 但 assistant 无 captured reasoning 时，仍回传空 reasoning_content
    （§7.1 问 5：thinking 模式工具轮次必须保持该键，否则 400；agent_v2.py:1490）。
    这是 _raw_stream 实际构建请求 payload 的路径（agent_v2.py:1672）。"""
    from langchain_core.messages import AIMessage
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    ai = AIMessage(
        content="call tool",
        tool_calls=[{"id": "call_2", "name": "fetch", "args": {}}],
    )
    out = AgentV2._to_openai_messages([ai])
    assert out[0]["role"] == "assistant"
    assert "reasoning_content" in out[0]
    assert out[0]["reasoning_content"] == ""


# ---- 完成判据 4：旧型号（deepseek-chat/reasoner）保持 A3 逻辑不回归 ---------


def test_legacy_chat_non_thinking_s71():
    """旧 deepseek-chat → non-thinking（A3 行为）；§7.1 过渡期指向 flash non-thinking。
    A3 通用字段保留（1M/ToolCalls/tokenizer），v4 专属字段（effort/cache/max_output）不套用。"""
    caps = _caps("deepseek-chat")
    assert caps.supports_reasoning is False
    assert caps.thinking_default_on is False
    assert caps.accepts_temperature is True
    assert caps.context_window == 1_048_576  # A3 原值，过渡期仍 1M
    assert caps.supports_function_calling is True
    assert caps.tokenizer == "chars:2.0"
    assert caps.prompt_variant == "deepseek"
    assert caps.effort_presets == {}
    assert caps.cache_min_block_tokens is None
    assert caps.max_output_tokens is None


def test_legacy_reasoner_thinking_s71():
    """旧 deepseek-reasoner → thinking（A3 行为）；§7.1 过渡期指向 flash thinking。
    A3 通用字段保留，v4 专属字段（effort/cache/max_output）不套用。"""
    caps = _caps("deepseek-reasoner")
    assert caps.supports_reasoning is True
    assert caps.thinking_default_on is True
    assert caps.accepts_temperature is False
    assert caps.context_window == 1_048_576  # A3 原值
    assert caps.supports_function_calling is True
    assert caps.tokenizer == "chars:2.0"
    assert caps.prompt_variant == "deepseek"
    assert caps.effort_presets == {}
    assert caps.cache_min_block_tokens is None
    assert caps.max_output_tokens is None


# ---- 完成判据 1：TODO 已填充；DC1/兜底 ------------------------------------


def test_deepseek_pricing_s71():
    """§7.1 问 7：v4-flash/pro 定价分条（USD，as_of=2026-08-02）。"""
    p, cfg = _resolve("deepseek-v4-flash")
    caps = p.capabilities(cfg)
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok == 0.14
    assert caps.pricing.output_per_mtok == 0.28
    assert caps.pricing.cached_input_per_mtok == 0.0028
    assert caps.pricing.as_of == "2026-08-02"
    assert caps.pricing.source_url

    p, cfg = _resolve("deepseek-v4-pro")
    caps = p.capabilities(cfg)
    assert caps.pricing.input_per_mtok == 0.435
    assert caps.pricing.output_per_mtok == 0.87
    assert caps.pricing.cached_input_per_mtok == 0.003625


def test_unknown_deepseek_variant_conservative():
    """未调研变体不套用 v4 能力，也不套用 A3 特有字段（DC1：context 默认、
    max_output/pricing None、无 thinking、无 ToolCalls/cache，全默认）。
    usage_fields 除外——它是 endpoint 协议布局（api.deepseek.com 响应结构），
    任何型号均按此解析缓存命中/reasoning（Luna rev5 选项 2）。"""
    caps = _caps("deepseek-unknown-x")
    assert caps.provider == "deepseek"
    assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
    assert caps.max_output_tokens is None
    assert caps.supports_reasoning is False
    assert caps.thinking_default_on is False
    assert caps.effort_presets == {}
    assert caps.cache_min_block_tokens is None
    assert caps.cache_ttl_s == DEFAULT_CAPABILITIES.cache_ttl_s
    assert caps.cache_breakpoints == DEFAULT_CAPABILITIES.cache_breakpoints
    assert caps.compaction_threshold == DEFAULT_CAPABILITIES.compaction_threshold
    assert caps.accepts_temperature == DEFAULT_CAPABILITIES.accepts_temperature
    assert caps.supports_function_calling == DEFAULT_CAPABILITIES.supports_function_calling
    assert caps.structured_output == DEFAULT_CAPABILITIES.structured_output
    assert caps.prompt_variant == "deepseek"
    assert caps.pricing.input_per_mtok is None
    assert caps.pricing.cache_write_per_mtok is None
    # 价格全 None 但来源元数据仍在：这是「未知价格 + 来源锚点」，非已调研定价
    # （不得被误读为已调研，也不得静默当 0 计费）
    assert caps.pricing.as_of == "2026-08-02"
    assert caps.pricing.source_url
    assert caps.pricing.output_per_mtok is None
    assert caps.pricing.cached_input_per_mtok is None
    assert caps.tokenizer == DEFAULT_CAPABILITIES.tokenizer
    assert caps.usage_fields.cache_read_flat == (
        "prompt_cache_hit_tokens",
        "cached_tokens",
    )

    # 系统性对比：除 provider/pricing/prompt_variant/usage_fields 四个有意覆盖字段外，
    # 未知变体必须逐字段等于 DEFAULT_CAPABILITIES（DC1 严格兜底）。
    import dataclasses

    for f in dataclasses.fields(caps):
        if f.name in ("provider", "pricing", "prompt_variant", "usage_fields"):
            continue
        assert getattr(caps, f.name) == getattr(DEFAULT_CAPABILITIES, f.name), (
            f"unknown variant leaked field: {f.name}"
        )


@pytest.mark.parametrize("name", ["deepseek-v4", "deepseek-v4-foo"])
def test_v4_substring_not_generalized(name):
    """`"v4" in name` 不泛化：未知 v4 变体不得继承 v4 能力（DC1）。"""
    caps = _caps(name)
    assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
    assert caps.max_output_tokens is None
    assert caps.supports_reasoning is False
    assert caps.cache_min_block_tokens is None
    assert caps.prompt_variant == "deepseek"


@pytest.mark.parametrize("name", ["deepseek-v4-flash-foo", "deepseek-v4-pro-preview"])
def test_pricing_substring_not_generalized(name):
    """`"v4-flash"/"v4-pro"` 不子串匹配：未知变体 pricing 显式 None（DC1）。"""
    caps = _caps(name)
    assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
    assert caps.max_output_tokens is None
    assert caps.cache_min_block_tokens is None
    assert caps.prompt_variant == "deepseek"
    assert caps.pricing.input_per_mtok is None
    assert caps.pricing.output_per_mtok is None
