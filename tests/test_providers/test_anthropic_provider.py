"""Anthropic provider 行为测试（A18 补全：§7.8 五主力）。"""

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelPricing
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
        {"base_url": "https://api.anthropic.com/v1", "model_name": "claude-fable-5"},
        {"base_url": "https://relay.example/v1", "model_name": "claude-opus-4-8"},
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
    """§7.8/A6：原生 Messages（api.anthropic.com）支持显式 cache_control；
    OpenAI 兼容/中转端点不支持 prompt caching（Luna rev5 端点感知）。"""
    native = providers.resolve(
        {"base_url": "https://api.anthropic.com/v1", "model_name": "claude-opus-5"}
    ).capabilities({"base_url": "https://api.anthropic.com/v1", "model_name": "claude-opus-5"})
    assert native.supports_prompt_cache is True
    relay = providers.resolve(
        {"base_url": "https://relay.example/v1", "model_name": "claude-sonnet-5"}
    ).capabilities({"base_url": "https://relay.example/v1", "model_name": "claude-sonnet-5"})
    assert relay.supports_prompt_cache is False


@pytest.mark.parametrize(
    "url",
    [
        "https://api.anthropic.com.evil.example/v1",
        "https://relay.example/proxy/api.anthropic.com/v1",
        "https://not-anthropic.com/v1",
        "ftp://api.anthropic.com/v1",
        "http://api.anthropic.com/v1",
    ],
)
def test_fake_native_endpoint_not_cached(url):
    """§7.8/A6：伪原生子串/非 HTTPS 不得获得 supports_prompt_cache（Luna rev6/rev7）。"""
    caps = providers.resolve({"base_url": url, "model_name": "claude-opus-5"}).capabilities(
        {"base_url": url, "model_name": "claude-opus-5"}
    )
    assert caps.supports_prompt_cache is False


def test_sampling_in_extra_body_rejected():
    """§7.8：extra_body 内传非默认采样参数不得绕过 400 契约（Luna rev6）。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    cfg = dict(_CFG, extra_body={"temperature": 0.9})
    with pytest.raises(ValueError):
        p.llm_kwargs(cfg, caps)


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


def test_dotted_catalog_ids_use_canonical_family():
    dotted = providers.resolve({"model_name": "claude-haiku-4.5"}).capabilities(
        {
            "base_url": "https://api.anthropic.com/v1",
            "model_name": "claude-haiku-4.5",
        }
    )
    hyphen = providers.resolve({"model_name": "claude-haiku-4-5"}).capabilities(
        {
            "base_url": "https://api.anthropic.com/v1",
            "model_name": "claude-haiku-4-5",
        }
    )
    assert dotted.context_window == hyphen.context_window == 200_000
    assert dotted.cache_min_block_tokens == hyphen.cache_min_block_tokens == 4096


def test_sonnet_45_is_not_aliased_to_sonnet_5():
    """claude-sonnet-4.5 is the Sonnet 4.5 API id, not Sonnet 5."""
    from core.catalog import canonical_model_id

    assert canonical_model_id("anthropic", "claude-sonnet-4.5") == "claude-sonnet-4-5"
    sonnet_45 = AnthropicProvider().capabilities(
        {
            "base_url": "https://api.anthropic.com/v1",
            "model_name": "claude-sonnet-4.5",
        }
    )
    sonnet_5 = AnthropicProvider().capabilities(
        {
            "base_url": "https://api.anthropic.com/v1",
            "model_name": "claude-sonnet-5",
        }
    )
    assert sonnet_45.context_window == 200_000
    assert sonnet_5.context_window == 1_000_000
    assert sonnet_45.max_output_tokens == 64_000
    assert sonnet_5.max_output_tokens == 128_000
    assert sonnet_45.thinking_default_on is False
    assert sonnet_5.thinking_default_on is True
    assert sonnet_45.pricing.input_per_mtok is None
    assert sonnet_5.pricing.input_per_mtok == 2.0


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


# ---- A18 补全：§7.8 ③ 五主力 ----


@pytest.mark.parametrize("name,context,maxout", [
    ("claude-opus-5", 1_000_000, 128_000),
    ("claude-sonnet-5", 1_000_000, 128_000),
    ("claude-fable-5", 1_000_000, 128_000),
    ("claude-opus-4-8", 1_000_000, 128_000),
    ("claude-haiku-4-5", 200_000, 64_000),
])
def test_five_mainstays_window_and_output(name, context, maxout):
    """§7.8 ③：五主力 context/max_output（A1 表 1M/200k/128k/64k）。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.context_window == context
    assert caps.max_output_tokens == maxout
    assert caps.supports_vision is True


@pytest.mark.parametrize("name,default_on", [
    ("claude-opus-5", True),
    ("claude-sonnet-5", True),
    ("claude-fable-5", True),   # thinking always on, cannot disable
    ("claude-opus-4-8", False),  # default off; must explicit adaptive (A4)
    ("claude-haiku-4-5", False),  # extended only, explicit enabled (A1/A5)
])
def test_thinking_default_on_per_mainstay(name, default_on):
    """§7.8 问 5：Claude 5 默认开；Opus 4.8 / Haiku 4.5 默认关。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.thinking_default_on is default_on


@pytest.mark.parametrize("name,inp,outp,hit,write", [
    ("claude-opus-5", 5.0, 25.0, 0.50, 6.25),
    ("claude-sonnet-5", 2.0, 10.0, 0.20, 2.50),
    ("claude-fable-5", 10.0, 50.0, 1.00, 12.50),
    ("claude-opus-4-8", 5.0, 25.0, 0.50, 6.25),
    ("claude-haiku-4-5", 1.0, 5.0, 0.10, 1.25),
])
def test_per_mainstay_pricing(name, inp, outp, hit, write):
    """§7.8 问 7：五主力 input/output/cache_hit/5m cache_write 分条（USD，as_of=2026-08-02）。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert isinstance(caps.pricing, ModelPricing)
    assert caps.pricing.input_per_mtok == inp
    assert caps.pricing.output_per_mtok == outp
    assert caps.pricing.cached_input_per_mtok == hit
    assert caps.pricing.cache_write_per_mtok == write
    assert caps.pricing.as_of == "2026-08-02"
    assert caps.pricing.source_url


def test_cache_write_flat_mapping():
    """§7.8 ③：Anthropic 缓存写入在顶层 usage.cache_creation_input_tokens。"""
    caps = providers.resolve({"model_name": "claude-opus-5"}).capabilities(
        {"model_name": "claude-opus-5"}
    )
    assert caps.usage_fields.cache_write_flat == ("cache_creation_input_tokens",)
    assert caps.usage_fields.cache_read_flat == ("cache_read_input_tokens",)


def test_opus_48_tokenizer_notes():
    """§7.8 问 6：无 tiktoken，用 count_tokens；tokenizer 非官方启发式。"""
    caps = providers.resolve({"model_name": "claude-opus-4-8"}).capabilities(
        {"model_name": "claude-opus-4-8"}
    )
    assert caps.tokenizer == "chars:3.0"


def test_unknown_anthropic_variant_stays_conservative():
    """未调研型号不套用调研能力：仅 provider/usage/pricing 变化，能力字段保守。"""
    for name in ["claude-unknown-variant", "claude-opus-3", "claude-mythos-5"]:
        caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
        assert caps.provider == "anthropic"
        assert caps.context_window == DEFAULT_CAPABILITIES.context_window == 256_000
        assert caps.max_output_tokens is None
        assert caps.supports_reasoning is False
        assert caps.prompt_variant == DEFAULT_CAPABILITIES.prompt_variant == "default"
        # 未知变体 pricing 全字段 None（DC1，不得继承调研定价）
        assert caps.pricing.input_per_mtok is None
        assert caps.pricing.output_per_mtok is None
        assert caps.pricing.cached_input_per_mtok is None
        assert caps.pricing.cache_write_per_mtok is None
        # 未知变体不继承缓存参数（cache_min_block/ttl/breakpoints 保持 DEFAULT）
        assert caps.cache_min_block_tokens == DEFAULT_CAPABILITIES.cache_min_block_tokens
        assert caps.cache_ttl_s == DEFAULT_CAPABILITIES.cache_ttl_s
        assert caps.cache_breakpoints == DEFAULT_CAPABILITIES.cache_breakpoints


# ---- A18 Luna rev1 补充：采样 400 契约 / 缓存参数 / thinking 契约 ----

_CFG = {"model_name": "claude-opus-5", "resolved_max_tokens": 8192, "api_key": "x"}


def test_llm_kwargs_no_temperature_for_anthropic():
    """§7.8 问 5：非默认采样一律 400 → llm_kwargs 不注入 temperature（accepts_temperature=False）。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    kw = p.llm_kwargs(_CFG, caps)
    assert "temperature" not in kw


def test_llm_kwargs_thinking_injected_via_extra_body():
    """§7.8/A21：Anthropic 不注入 base 的 extra_body.thinking type:enabled——thinking
    走 content blocks（Opus 4.8 用 type:enabled 会 400；Claude 5 adaptive 默认开）。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    kw = p.llm_kwargs(_CFG, caps)
    body = kw.get("extra_body") or {}
    assert "thinking" not in body  # 默认路径零注入（严格断言，Luna rev8 Minor）
    assert "reasoning_effort" not in kw


def test_llm_kwargs_strips_reasoning_effort_from_extra_body():
    """§7.8 ③：Anthropic 无 reasoning_effort——extra_body 内传入也移除（Luna rev8/rev9）。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    # 组合场景：合法 thinking + 不支持的 reasoning_effort 同在一个 extra_body
    cfg = dict(_CFG, extra_body={"thinking": {"type": "adaptive"}, "reasoning_effort": "high"})
    kw = p.llm_kwargs(cfg, caps)
    assert "reasoning_effort" not in kw
    body = kw.get("extra_body") or {}
    assert "reasoning_effort" not in body
    assert body.get("thinking") == {"type": "adaptive"}  # 合法配置保留


def test_relay_override_cannot_enable_cache():
    """§7.8 A6：relay 端点的 supports_prompt_cache 端点硬边界不可被 override 绕过（Luna rev9）。"""
    relay = {"base_url": "https://relay.example/v1", "model_name": "claude-sonnet-5"}
    caps = providers.resolve(relay).capabilities(dict(relay, supports_prompt_cache=True))
    assert caps.supports_prompt_cache is False


def test_native_override_cannot_disable_cache():
    """§7.8 A6：原生端点恒 supports_prompt_cache=True，不可被 override 改 False（Luna rev13）。"""
    native = {"base_url": "https://api.anthropic.com/v1", "model_name": "claude-opus-5"}
    caps = providers.resolve(native).capabilities(dict(native, supports_prompt_cache=False))
    assert caps.supports_prompt_cache is True


@pytest.mark.parametrize("url", ["https://api.anthropic.com:8443/v1", "https://api.anthropic.com:443/v1"])
def test_native_port_boundary(url):
    """§7.8：原生端点端口 443/空 放行；非标准端口不判为原生（Luna rev13）。"""
    caps = providers.resolve({"base_url": url, "model_name": "claude-opus-5"}).capabilities(
        {"base_url": url, "model_name": "claude-opus-5"}
    )
    assert caps.supports_prompt_cache is (url.endswith(":443/v1"))


def test_unknown_variant_native_endpoint_cache_true():
    """§7.8 A6：supports_prompt_cache 是端点级事实——未知变体走原生端点也应 True
    （模型专属的 min_block/ttl/breakpoints 不设置，Luna rev12）。"""
    native = {"base_url": "https://api.anthropic.com/v1", "model_name": "claude-unknown-variant"}
    caps = providers.resolve(native).capabilities(native)
    assert caps.supports_prompt_cache is True
    assert caps.cache_min_block_tokens == DEFAULT_CAPABILITIES.cache_min_block_tokens
    relay = {"base_url": "https://relay.example/v1", "model_name": "claude-unknown-variant"}
    caps_relay = providers.resolve(relay).capabilities(relay)
    assert caps_relay.supports_prompt_cache is False


def test_fable_disabled_thinking_rejected():
    """§7.8 A4：claude-fable-5 thinking 不可关——显式 type:disabled 拒绝。"""
    cfg = {"model_name": "claude-fable-5", "resolved_max_tokens": 8192, "api_key": "x"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    with pytest.raises(ValueError):
        p.llm_kwargs(dict(cfg, extra_body={"thinking": {"type": "disabled"}}), caps)


def test_llm_kwargs_does_not_mutate_caller_extra_body():
    """Luna rev17：llm_kwargs 不修改调用方传入的 extra_body dict（拷贝后操作）。"""
    cfg = {"model_name": "claude-opus-3", "resolved_max_tokens": 8192, "api_key": "x"}
    caller_body = {"thinking": {"type": "adaptive"}}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    p.llm_kwargs(dict(cfg, extra_body=caller_body), caps)
    assert caller_body == {"thinking": {"type": "adaptive"}}  # 未被污染


def test_user_extra_body_value_overrides_base():
    """Luna rev17：用户显式 extra_body 值优先于 base 生成的同键默认值。"""
    cfg = {"model_name": "claude-opus-3", "resolved_max_tokens": 8192, "api_key": "x",
           "extra_body": {"top_p": 0.95}}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    kw = p.llm_kwargs(cfg, caps)
    assert kw["extra_body"]["top_p"] == 0.95


def test_llm_kwargs_preserves_explicit_adaptive():
    """§7.8：各型号合法的显式 thinking 配置不被误删（按实际型号验证）。"""
    cases = [
        ("claude-opus-4-8", {"type": "adaptive"}),  # Opus 4.8 开启路径
        ("claude-haiku-4-5", {"type": "enabled", "budget_tokens": 4096}),  # Haiku extended
    ]
    for name, thinking in cases:
        cfg = {"model_name": name, "resolved_max_tokens": 8192, "api_key": "x",
               "extra_body": {"thinking": thinking}}
        p = providers.resolve(cfg)
        caps = p.capabilities(cfg)
        kw = p.llm_kwargs(cfg, caps)
        assert kw["extra_body"]["thinking"] == thinking


def test_llm_kwargs_opus48_enabled_passthrough():
    """§7.8：Opus 4.8 显式传 type:enabled → 保留原样，由 API 返回 400（不静默改写）。"""
    p = providers.resolve({"model_name": "claude-opus-4-8", "resolved_max_tokens": 8192, "api_key": "x"})
    caps = p.capabilities({"model_name": "claude-opus-4-8", "resolved_max_tokens": 8192, "api_key": "x"})
    cfg = {"model_name": "claude-opus-4-8", "resolved_max_tokens": 8192, "api_key": "x",
           "extra_body": {"thinking": {"type": "enabled"}}}
    kw = p.llm_kwargs(cfg, caps)
    assert kw["extra_body"]["thinking"]["type"] == "enabled"


@pytest.mark.parametrize("key,value", [("temperature", 0.9), ("top_p", 0.9), ("top_k", 30)])
def test_llm_kwargs_rejects_custom_sampling(key, value):
    """§7.8：受限型号（五主力 + Mythos/Opus4.7）显式传非默认采样 → ValueError（HTTP 400）。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    cfg = dict(_CFG)
    cfg[key] = value
    with pytest.raises(ValueError):
        p.llm_kwargs(cfg, caps)


@pytest.mark.parametrize("name", ["claude-mythos-5", "claude-opus-4-7", "claude-mythos-5-preview"])
def test_sampling_restricted_includes_mythos_and_opus47(name):
    """§7.8 问 5（A4）：Mythos/Preview/Opus 4.7 等报告明确型号受采样 400 契约。"""
    cfg = {"model_name": name, "resolved_max_tokens": 8192, "api_key": "x"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    with pytest.raises(ValueError):
        p.llm_kwargs(dict(cfg, temperature=0.9), caps)


@pytest.mark.parametrize("name", ["claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-x", "claude-opus-3"])
def test_unlisted_variants_sampling_not_restricted(name):
    """DC1：§7.8 未列出的 4.6/4.5 及未知变体不继承采样 400 契约（Luna rev14）。"""
    cfg = {"model_name": name, "resolved_max_tokens": 8192, "api_key": "x"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    kw = p.llm_kwargs(dict(cfg, temperature=0.9), caps)
    assert kw.get("temperature") == 0.9


def test_haiku_sampling_not_restricted():
    """§7.8：Haiku 4.5 不在采样 400 清单——可传自定义采样，accepts_temperature=True
    （与 llm_kwargs 分支一致，Luna rev15）。"""
    cfg = {"model_name": "claude-haiku-4-5", "resolved_max_tokens": 8192, "api_key": "x"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    assert caps.accepts_temperature is True
    kw = p.llm_kwargs(dict(cfg, temperature=0.9), caps)
    assert kw.get("temperature") == 0.9


def test_restricted_accepts_temperature_false():
    """§7.8：受限型号 accepts_temperature=False（与采样 400 契约一致）。"""
    for name in ("claude-opus-5", "claude-fable-5", "claude-sonnet-5"):
        caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
        assert caps.accepts_temperature is False


@pytest.mark.parametrize("name", ["claude-mythos-5", "claude-mythos-5-preview", "claude-opus-4-7"])
def test_restricted_non_mainstay_accepts_temperature_false(name):
    """Luna rev16：非五主力受限型号的 capability 元数据须与 llm_kwargs 拒绝行为一致。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.accepts_temperature is False


def test_unknown_variant_sampling_not_rejected():
    """§7.8/DC1：未知变体（claude-opus-3）不继承采样 400 契约（Luna rev10）。"""
    cfg = {"model_name": "claude-opus-3", "resolved_max_tokens": 8192, "api_key": "x"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    kw = p.llm_kwargs(dict(cfg, temperature=0.9), caps)
    assert kw.get("temperature") == 0.9


def test_unknown_variant_extra_body_sampling_preserved():
    """DC1：未知变体 extra_body 内采样字段按 DEFAULT 行为保留（Luna rev11 Minor）。"""
    cfg = {"model_name": "claude-opus-3", "resolved_max_tokens": 8192, "api_key": "x"}
    p = providers.resolve(cfg)
    caps = p.capabilities(cfg)
    kw = p.llm_kwargs(dict(cfg, extra_body={"temperature": 0.9}), caps)
    assert kw["extra_body"]["temperature"] == 0.9


def test_llm_kwargs_accepts_default_temperature():
    """§7.8：显式传 Anthropic 默认采样值（temperature=1.0 / top_p=1.0）→ 放行。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    for key, value in (("temperature", 1.0), ("top_p", 1.0)):
        cfg = dict(_CFG)
        cfg[key] = value
        kw = p.llm_kwargs(cfg, caps)
        assert "temperature" not in kw and "top_p" not in kw  # 默认值 → 不注入自定义采样


def test_llm_kwargs_no_sampling_params():
    """§7.8：非默认 temperature/top_p/top_k 一律 400 → llm_kwargs 不注入任一采样参数。"""
    p = providers.resolve(_CFG)
    caps = p.capabilities(_CFG)
    kw = p.llm_kwargs(_CFG, caps)
    assert "temperature" not in kw
    assert "top_p" not in kw
    assert "top_k" not in kw


@pytest.mark.parametrize(
    "name,min_block",
    [
        ("claude-opus-5", 512),
        ("claude-fable-5", 512),
        ("claude-sonnet-5", 1024),
        ("claude-opus-4-8", 1024),
        ("claude-haiku-4-5", 4096),
    ],
)
def test_cache_min_block_per_mainstay(name, min_block):
    """§7.8 问 4：各主力最小可缓存块（A3 表）。"""
    caps = providers.resolve({"model_name": name}).capabilities({"model_name": name})
    assert caps.cache_min_block_tokens == min_block
    assert caps.cache_ttl_s == 300
    assert caps.cache_breakpoints == ("tools", "system", "session_static", "tail")


def test_cache_write_flat_mapping_and_pricing_write():
    """§7.8 ③：cache write 顶层字段 + 5m 写入价（cache_write_per_mtok）。"""
    caps = providers.resolve({"model_name": "claude-opus-5"}).capabilities({"model_name": "claude-opus-5"})
    assert caps.usage_fields.cache_write_flat == ("cache_creation_input_tokens",)
    # AgentV2 normalizes native thinking blocks to its stable internal
    # ``reasoning_content`` field so the TUI and tool loop can consume them.
    assert caps.usage_fields.reasoning == ("reasoning_content",)
    assert caps.pricing.cache_write_per_mtok == 6.25


def test_thinking_defaults_per_mainstay_full():
    """§7.8 问 5：Opus4.8 默认关（须显式 adaptive）；Fable 思考不可关。"""
    opus48 = providers.resolve({"model_name": "claude-opus-4-8"}).capabilities({"model_name": "claude-opus-4-8"})
    assert opus48.thinking_default_on is False
    fable = providers.resolve({"model_name": "claude-fable-5"}).capabilities({"model_name": "claude-fable-5"})
    assert fable.thinking_default_on is True
    haiku = providers.resolve({"model_name": "claude-haiku-4-5"}).capabilities({"model_name": "claude-haiku-4-5"})
    assert haiku.thinking_default_on is False


def test_matches_case_insensitive():
    """matches 对 URL/模型名大小写不敏感。"""
    p = AnthropicProvider()
    assert p.matches("HTTPS://API.ANTHROPIC.COM/V1", "CLAUDE-OPUS-5")
    assert p.matches("https://relay.example/v1", "Claude-Sonnet-5")
