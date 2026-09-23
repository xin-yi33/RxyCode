"""A19: per-model 缓存参数 —— 3 新字段默认 + cache_params() + 断点校验器 + 8 族表。"""

import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelCapabilities
from core import providers
from core.providers.base import BaseProvider


# ---- 3 新字段默认值（完成判据 1） ------------------------------------------


def test_new_fields_default_to_not_applicable():
    """三个新字段默认全部为「不适用」（None / 空元组），既有行为零变化。"""
    caps = DEFAULT_CAPABILITIES
    assert caps.cache_min_block_tokens is None
    assert caps.cache_ttl_s is None
    assert caps.cache_breakpoints == ()


def test_default_capabilities_unchanged_behavior():
    """默认能力与 A1 既有测试兼容（字段只追加）。"""
    caps = DEFAULT_CAPABILITIES
    assert caps.provider == "openai"
    assert caps.context_window == 256_000
    assert caps.tokenizer == "tiktoken:o200k_base"


# ---- cache_params() 辅助输出（操作步骤 3） ---------------------------------


def test_cache_params_default_package():
    """未配置时 cache_params() 返回「不适用」包。"""
    p = BaseProvider()
    caps = DEFAULT_CAPABILITIES
    out = p.cache_params(caps)
    assert out == {
        "min_block_tokens": None,
        "ttl_s": None,
        "breakpoints": [],
        "hit_field_flat": list(caps.usage_fields.cache_read_flat),
        "hit_field_nested": list(caps.usage_fields.cache_read_nested),
    }


def test_cache_params_reflects_caps():
    """cache_params() 反映 caps 上的三个新字段与命中字段映射。"""
    p = BaseProvider()
    caps = ModelCapabilities(
        cache_min_block_tokens=512,
        cache_ttl_s=300,
        cache_breakpoints=("tools", "system"),
    )
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 512
    assert out["ttl_s"] == 300
    assert out["breakpoints"] == ["tools", "system"]


# ---- 断点布局校验器（操作步骤 6；校验器放 base.py） ------------------------


@pytest.mark.parametrize("bad", [
    ("tools", "system", "session_static", "tail", "extra"),  # >4 个
    ("system", "tools"),                                     # 乱序（tools 应最前）
    ("tools", "dynamic"),                                    # 动态块不允许
    ("tools", "tail", "system"),                             # tail 之后还有
])
def test_breakpoint_validator_rejects(bad):
    """校验器拒绝：>4 个 / 乱序 / 含动态块 / tail 后还有块。"""
    with pytest.raises(ValueError):
        BaseProvider().validate_breakpoints(bad)


@pytest.mark.parametrize("good", [
    (),
    ("tools",),
    ("tools", "system"),
    ("tools", "system", "session_static", "tail"),
])
def test_breakpoint_validator_accepts(good):
    """校验器接受：空 / 合法静态布局（最多 4 个，静态在前动态在后）。"""
    assert BaseProvider().validate_breakpoints(good) is None


def test_capabilities_reject_invalid_breakpoints():
    """cache_params() 消费非法断点时抛 ValueError（校验器接线）。"""
    caps = ModelCapabilities(cache_breakpoints=("tools", "dynamic"))
    with pytest.raises(ValueError):
        BaseProvider().cache_params(caps)


# ---- 8 族 cache_params() 与 §7 报告逐条一致（完成判据 2） -------------------


def _caps(base_url, model_name):
    cfg = {"base_url": base_url, "model_name": model_name}
    p = providers.resolve(cfg)
    return p, p.capabilities(cfg)


def test_deepseek_cache_params_s71():
    """§7.1：自动 disk 缓存，最小 64 token prefix unit；无显式断点。"""
    p, caps = _caps("https://api.deepseek.com/v1", "deepseek-v4-flash")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 1024
    assert out["ttl_s"] is None
    assert out["breakpoints"] == []
    assert "prompt_cache_hit_tokens" in out["hit_field_flat"]


def test_openai_cache_params_s72():
    """§7.2：自动前缀缓存，GPT-5.6+ 最小 1024；TTL 30m（1800s）。"""
    p, caps = _caps("https://api.openai.com/v1", "gpt-5.6-sol")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 1024
    assert out["ttl_s"] == 1800
    assert out["breakpoints"] == []
    assert ("prompt_tokens_details", "cached_tokens") in [
        tuple(x) for x in out["hit_field_nested"]
    ]


def test_kimi_cache_params_s73():
    """§7.3：自动 Context Caching，前次 prompt > 256 才缓存。"""
    p, caps = _caps("https://api.moonshot.cn/v1", "kimi-k3")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 256
    assert out["ttl_s"] is None
    assert out["breakpoints"] == []


def test_glm_cache_params_s74():
    """§7.4：隐式缓存，最小块未找到 → None。"""
    p, caps = _caps("https://open.bigmodel.cn/api/paas/v4/", "glm-5.2")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] is None
    assert out["ttl_s"] is None
    assert out["breakpoints"] == []


def test_minimax_cache_params_s75():
    """§7.5：被动缓存，输入 ≥512 tokens。"""
    p, caps = _caps("https://api.minimaxi.com/v1", "MiniMax-M3")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 512
    assert out["ttl_s"] is None
    assert out["breakpoints"] == []


def test_mimo_cache_params_s76():
    """§7.6：隐式 Prompt Cache，最小块未找到 → None。"""
    p, caps = _caps("https://api.xiaomimimo.com/v1", "mimo-v2.5-pro")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] is None
    assert out["ttl_s"] is None
    assert out["breakpoints"] == []


def test_qwen_cache_params_s77():
    """§7.7：显式 cache_control（最小 1024 / TTL 5min=300s）+ 隐式（256）。"""
    p, caps = _caps("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 1024
    assert out["ttl_s"] == 300
    assert out["breakpoints"] == []
    # 显式创建写字段应可观测
    assert ("prompt_tokens_details", "cache_creation_input_tokens") in [
        tuple(x) for x in caps.usage_fields.cache_write_nested
    ]


def test_anthropic_cache_params_s78():
    """§7.8：显式 cache_control 断点（最多 4 个，tools→system→tail）；TTL 5min。"""
    p, caps = _caps("https://api.anthropic.com/v1", "claude-opus-5")
    out = p.cache_params(caps)
    assert out["min_block_tokens"] == 512
    assert out["ttl_s"] == 300
    assert out["breakpoints"] == ["tools", "system", "session_static", "tail"]
    assert "cache_read_input_tokens" in out["hit_field_flat"]


def test_anthropic_haiku_min_block_4096():
    """§7.8：Haiku 4.5 最小缓存块 4096（≠ Opus 512）。"""
    p, caps = _caps("https://api.anthropic.com/v1", "claude-haiku-4-5")
    assert p.cache_params(caps)["min_block_tokens"] == 4096


@pytest.mark.parametrize("name,minblock", [
    ("claude-opus-5", 512),
    ("claude-fable-5", 512),
    ("claude-sonnet-5", 1024),
    ("claude-opus-4-8", 1024),
    ("claude-haiku-4-5", 4096),
])
def test_anthropic_per_model_min_block(name, minblock):
    """§7.8 问 4：Anthropic 按型号最小缓存块。"""
    p, caps = _caps("https://api.anthropic.com/v1", name)
    assert p.cache_params(caps)["min_block_tokens"] == minblock
    assert p.cache_params(caps)["ttl_s"] == 300
    assert p.cache_params(caps)["breakpoints"] == ["tools", "system", "session_static", "tail"]


# ---- 8 族 hit-field 映射与 cache_params 逐族一致 -------------------------


@pytest.mark.parametrize("u,model,flat,nested", [
    ("https://api.deepseek.com/v1", "deepseek-v4-flash",
     ["prompt_cache_hit_tokens"], []),
    ("https://api.openai.com/v1", "gpt-5.6-sol",
     ["prompt_cache_hit_tokens"],
     [("prompt_tokens_details", "cached_tokens"), ("input_token_details", "cache_read")]),
    ("https://api.moonshot.cn/v1", "kimi-k3",
     ["cached_tokens"], []),
    ("https://open.bigmodel.cn/api/paas/v4/", "glm-5.2",
     [], [("prompt_tokens_details", "cached_tokens")]),
    ("https://api.minimaxi.com/v1", "MiniMax-M3",
     [], [("prompt_tokens_details", "cached_tokens")]),
    ("https://api.xiaomimimo.com/v1", "mimo-v2.5-pro",
     [], [("prompt_tokens_details", "cached_tokens")]),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus",
     [], [("prompt_tokens_details", "cached_tokens")]),
    ("https://api.anthropic.com/v1", "claude-opus-5",
     ["cache_read_input_tokens"], [("input_token_details", "cache_read")]),
])
def test_family_hit_fields(u, model, flat, nested):
    """8 族 cache_params() 命中字段映射与 §7 报告一致。"""
    p, caps = _caps(u, model)
    out = p.cache_params(caps)
    assert out["hit_field_flat"] == flat
    assert out["hit_field_nested"] == nested
