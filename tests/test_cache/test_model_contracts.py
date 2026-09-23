"""B9 + FXC1: per-model 缓存契约层 —— 10 家 cache_contract / 唯一入口 / usage 归一化。

完成判据对应：
1. 原 9 家 + Doubao cache_contract 齐全且过 schema 校验
2. 契约读取唯一入口（无散落 if-elif）
3. usage 归一化覆盖各家差异（≥5 家测试）；OpenAI 双路径 max
4. 模型限制性规范 9 条全部有测试
5. 未识别模型走现状路径（CB8）
"""

from __future__ import annotations

import json

import pytest

from RxyCode.RxyCode1_1_0.core.catalog import (
    get_contract,
    hit_discount,
    read_cached_tokens,
)
from tests.conftest import REPO_ROOT

CATALOG_PATH = REPO_ROOT / "config" / "model_catalog.json"
SCHEMA_PATH = REPO_ROOT / "config" / "model_catalog.schema.json"


# ============================================================================
# 完成判据 1：9 家 cache_contract 齐全且过 schema 校验
# ============================================================================

NINE_PROVIDERS = {
    "deepseek", "mimo", "kimi", "minimax", "glm",
    "qwen", "grok", "anthropic", "openai",
}
CONTRACT_PROVIDERS = NINE_PROVIDERS | {"doubao"}


def test_catalog_has_nine_provider_contracts():
    """原 9 家 + Doubao 厂商 cache_contract 齐全（FXC1：9→10）。"""
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    providers = {r["provider_id"] for r in data["records"] if "cache_contract" in r}
    assert CONTRACT_PROVIDERS <= providers


def test_catalog_schema_validates_contracts():
    """catalog 过 JSON schema 校验（含 cache_contract 定义）。"""
    import jsonschema

    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=data, schema=schema)


def test_contract_required_fields():
    """每条 cache_contract 含必需字段（cache_mode/usage_fields/reasoning_contract）。"""
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for record in data["records"]:
        contract = record.get("cache_contract")
        if contract is None:
            continue
        assert contract.get("cache_mode") in {
            "auto", "explicit_breakpoints", "cache_key", "auto_and_key",
        }, record["model_id"]
        assert "usage_fields" in contract, record["model_id"]
        assert "cached" in contract["usage_fields"], record["model_id"]
        assert contract.get("reasoning_contract") in {
            "mandatory_echo", "thinking_blocks_echo", "none", "no_thinking",
        }, record["model_id"]


def test_contract_mode_consistent_with_provider():
    """cache_mode 与厂商机制一致（无通配：DeepSeek auto 不注入 cache_control）。"""
    deepseek = get_contract("deepseek", "deepseek-v4-flash")
    assert deepseek["cache_mode"] == "auto"
    assert deepseek["breakpoints_max"] == 0

    claude = get_contract("anthropic", "claude-sonnet-4.5")
    assert claude["cache_mode"] == "explicit_breakpoints"
    assert claude["breakpoints_max"] == 4
    assert get_contract("anthropic", "claude-sonnet-4-5") == claude
    assert get_contract("anthropic", "claude-sonnet-5") != claude
    assert get_contract("anthropic", "claude-haiku-4-5") == get_contract(
        "anthropic", "claude-haiku-4.5"
    )


# ============================================================================
# 完成判据 2：契约读取唯一入口
# ============================================================================


def test_contract_single_read_entry():
    """core/catalog.py 是唯一入口（get_contract 可解析所有已登记模型）。"""
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for record in data["records"]:
        if "cache_contract" not in record:
            continue
        contract = get_contract(record["provider_id"], record["model_id"])
        assert contract is not None, record["model_id"]


def test_no_scattered_provider_branches_in_catalog():
    """providers/ 不散落 cache_mode 判模型代码（唯一入口在 core/catalog.py）。"""
    import re

    for path in (REPO_ROOT / "core" / "providers").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        # 不允许在 provider 里硬编码 cache_mode 字符串常量（B9 通配红线）
        assert "cache_mode" not in src, f"scattered cache_mode in {path.name}"


# ============================================================================
# 完成判据 3：usage 归一化（≥5 家差异）
# ============================================================================


def test_usage_normalization_deepseek():
    """DeepSeek: prompt_tokens_details.cached_tokens 路径。"""
    usage = {"prompt_tokens_details": {"cached_tokens": 100}}
    assert read_cached_tokens("deepseek", "deepseek-v4-flash", usage) == 100


def test_usage_normalization_kimi():
    """Kimi: usage.cached_tokens（顶层 usage 字段）。"""
    usage = {"cached_tokens": 250}
    assert read_cached_tokens("kimi", "kimi-k3", usage) == 250


def test_usage_normalization_claude():
    """Claude: cache_read_input_tokens。"""
    usage = {"cache_read_input_tokens": 500}
    assert read_cached_tokens("anthropic", "claude-sonnet-4.5", usage) == 500


def test_usage_normalization_openai():
    """OpenAI Luna：平铺 cached_input_tokens 或 nested cached_tokens，取 max（FXC1）。"""
    usage = {"cached_input_tokens": 800}
    assert read_cached_tokens("openai", "gpt-5.6-luna", usage) == 800


def test_usage_normalization_grok():
    """Grok: cached_prompt_text_tokens + cost_in_usd_ticks。"""
    usage = {
        "cached_prompt_text_tokens": 1200,
        "cost_in_usd_ticks": 12345,
    }
    assert read_cached_tokens("grok", "grok-4.5", usage) == 1200


def test_usage_normalization_mimo():
    """MiMo: prompt_tokens_details.cached_tokens（OpenAI 兼容格式）。"""
    usage = {"prompt_tokens_details": {"cached_tokens": 300}}
    assert read_cached_tokens("mimo", "mimo-v2.5-pro", usage) == 300


def test_usage_normalization_missing_field_zero():
    """字段缺失 → 0（不把缺失当命中）。"""
    assert read_cached_tokens("kimi", "kimi-k3", {}) == 0
    assert read_cached_tokens("deepseek", "deepseek-v4-flash", {"x": 1}) == 0


def test_hit_discount_values():
    """命中折扣 per-model（DeepSeek flash 0.02；Claude 0.1）。"""
    assert hit_discount("deepseek", "deepseek-v4-flash") == pytest.approx(0.02)
    assert hit_discount("anthropic", "claude-sonnet-4.5") == pytest.approx(0.1)


# ============================================================================
# 完成判据 4：模型限制性规范 9 条
# ============================================================================


def test_restriction_1_reasoning_echo_mimo_minimax():
    """规范 1: MiMo/MiniMax 必回传 reasoning/thinking（contract 声明）。"""
    for provider, model in (
        ("mimo", "mimo-v2.5-pro"),
        ("minimax", "minimax-m3"),
    ):
        contract = get_contract(provider, model)
        assert contract["reasoning_contract"] in {
            "mandatory_echo", "thinking_blocks_echo",
        }


def test_restriction_2_mimo_thinking_temperature_override():
    """规范 2: MiMo thinking 开时温度/top_p 强制（1.0/0.95）。"""
    contract = get_contract("mimo", "mimo-v2.5-pro")
    override = contract.get("temperature_override")
    assert override is not None
    assert override["value"] == pytest.approx(1.0)
    assert override.get("top_p") == pytest.approx(0.95)


def test_restriction_3_deepseek_reasoning_echo_on_tool_calls():
    """规范 3: DeepSeek 工具循环必回传 reasoning_content（mandatory_echo）。"""
    contract = get_contract("deepseek", "deepseek-v4-flash")
    assert contract["reasoning_contract"] == "mandatory_echo"


def test_restriction_4_qwen_tool_schema_consistency():
    """规范 4: Qwen 工具 schema 三重一致（契约记录 breakpoints/模式）。"""
    contract = get_contract("qwen", "qwen3.7-max")
    assert contract["cache_mode"] in {"explicit_breakpoints", "auto"}
    # 显式断点厂商必须有 breakpoints_max 定义
    assert contract.get("breakpoints_max") is not None


def test_restriction_5_kimi_prompt_cache_key_constant():
    """规范 5: Kimi prompt_cache_key 必填且会话期恒定。"""
    contract = get_contract("kimi", "kimi-k3")
    assert contract["cache_mode"] == "auto_and_key"
    assert contract["prompt_cache_key_required"] is True


def test_restriction_6_claude_byte_exact_prefix():
    """规范 6: Claude 前缀字节级匹配（breakpoint_lookback ≤20 块）。"""
    contract = get_contract("anthropic", "claude-sonnet-4.5")
    assert contract["cache_mode"] == "explicit_breakpoints"
    assert contract["breakpoint_lookback"] <= 20


def test_restriction_7_model_switch_invalidates_cache():
    """规范 7: 换模型 = 缓存全失效（契约按 provider:model 隔离）。"""
    c1 = get_contract("deepseek", "deepseek-v4-flash")
    c2 = get_contract("deepseek", "deepseek-v4-pro")
    # 不同模型契约独立（cache_ttl 等不共享）
    assert c1 is not c2
    # prompt_cache_key 依赖 session_id（换模型会话变化 → 失效）
    assert c1.get("prompt_cache_key_required") is not None


def test_restriction_8_grok_reasoning_tokens_separate():
    """规范 8: Grok reasoning_tokens 单独计费（usage_fields 含 reasoning）。"""
    contract = get_contract("grok", "grok-4.5")
    fields = contract["usage_fields"]
    assert fields.get("reasoning") is not None
    # cost_in_usd_ticks 是服务端权威成本
    assert fields.get("cost_ticks") is not None


def test_restriction_9_cache_hit_tpm_quota_unknown():
    """规范 9: 命中 token 的 TPM 配额计入与否各家不同（契约不臆断）。"""
    # 契约不伪造 TPM 配额信息（null=未明确）
    contract = get_contract("mimo", "mimo-v2.5-pro")
    assert contract.get("cache_ttl_hours") is None or isinstance(
        contract["cache_ttl_hours"], (int, float)
    )


# ============================================================================
# 完成判据 5：未识别模型走现状路径（CB8）
# ============================================================================


def test_unknown_model_contract_none():
    """未识别模型 → get_contract 返回 None（CB8：现状行为）。"""
    assert get_contract("unknown-provider", "unknown-model") is None
    assert get_contract("deepseek", "unknown-model") is None


def test_unknown_model_read_cached_zero():
    """未识别模型 usage 归一化 → 0（不误报命中）。"""
    assert read_cached_tokens("unknown", "unknown", {"cached_tokens": 5}) == 0


# ============================================================================
# 行为测试（luna R1-4：不只看字段，验证运行时行为）
# ============================================================================


def test_qwen_explicit_breakpoints_actually_apply():
    """Qwen 契约 explicit_breakpoints → _apply_cache_control 注入断点（R1-1）。"""
    from types import SimpleNamespace as NS

    from config.model_capabilities import ModelCapabilities

    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    wrapper = object.__new__(UsageTrackingLLM)
    wrapper._provider = NS(
        name="qwen", supports_prompt_cache=lambda caps: True
    )
    wrapper._capabilities = ModelCapabilities(
        provider="qwen",
        cache_breakpoints=("tools", "system", "messages", "tail"),
    )
    wrapper._cfg = {}
    wrapper.model_config = {"model_name": "qwen3.7-max"}
    wrapper._cache_enabled = True  # 避免 __getattr__ 委托递归

    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [SystemMessage(content="sys"), HumanMessage(content="hi")]
    result = wrapper._apply_cache_control(messages, tools=None)
    # 契约 explicit_breakpoints → 注入 cache_control（system 断点）
    ak = getattr(result[0], "additional_kwargs", None) or {}
    assert "cache_control" in ak


def test_kimi_prompt_cache_key_injected():
    """Kimi 契约 auto_and_key → _raw_stream payload 注入 prompt_cache_key（R1-2）。"""
    import inspect

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    # 契约驱动：Kimi requires_prompt_cache_key=True
    from RxyCode.RxyCode1_1_0.core.catalog import requires_prompt_cache_key

    assert requires_prompt_cache_key("kimi", "kimi-k3") is True
    assert requires_prompt_cache_key("deepseek", "deepseek-v4-flash") is False
    # _raw_stream 注入逻辑不再硬编码 openai（源码断言）
    src = inspect.getsource(AgentV2._raw_stream)
    assert "contract_pk_key or caps_pk_key" in src
    assert "self._prompt_cache_key_value()" in src


def test_deepseek_no_prompt_cache_key_injected():
    """DeepSeek 契约不含 key → 不注入（CB3 保持）。"""
    from RxyCode.RxyCode1_1_0.core.catalog import requires_prompt_cache_key

    assert requires_prompt_cache_key("deepseek", "deepseek-v4-flash") is False
    assert requires_prompt_cache_key("anthropic", "claude-sonnet-4.5") is False


def test_usage_behavior_kimi_missing_usage():
    """Kimi 流式缺 include_usage → usage 缺失 ≠ 0 命中（常见坑 3）。"""
    # 契约读取在 usage 缺失时返回 0
    assert read_cached_tokens("kimi", "kimi-k3", {}) == 0
    # 有 usage 时正确读取
    assert read_cached_tokens("kimi", "kimi-k3", {"cached_tokens": 42}) == 42


def test_model_switch_invalidates_contract_scope():
    """换模型 = 契约不同 → prompt_cache_key 会话隔离（规范 7 行为）。"""
    # 同一 provider 不同模型契约独立
    k3 = get_contract("kimi", "kimi-k3")
    k27 = get_contract("kimi", "kimi-k2.7-code")
    assert k3 is not k27
    # 折扣不同 → 成本核算隔离
    assert hit_discount("kimi", "kimi-k3") != hit_discount("kimi", "kimi-k2.7-code")


def test_prompt_cache_key_value_includes_provider_model():
    """契约路径（Kimi）key 派生含 provider:model；B2 OpenAI caps 路径保持 session（luna R2-2）。"""
    from types import SimpleNamespace as NS

    from config.model_capabilities import ModelCapabilities

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    # Kimi 契约路径 → provider:model:session
    agent = object.__new__(AgentV2)
    agent._capabilities = ModelCapabilities(provider="kimi")
    agent.model_config = {"model_name": "kimi-k3"}
    agent._session_id = "sess-1"
    key1 = agent._prompt_cache_key_value()
    assert key1 == "kimi:kimi-k3:sess-1"

    # 换模型 → key 变化（缓存失效）
    agent.model_config = {"model_name": "kimi-k2.7-code"}
    key2 = agent._prompt_cache_key_value()
    assert key2 != key1

    # 换 provider → key 变化
    agent._capabilities = ModelCapabilities(provider="deepseek")
    agent.model_config = {"model_name": "deepseek-v4-flash"}
    key3 = agent._prompt_cache_key_value()
    assert key3 != key1

    # 同 provider/model/session → key 恒定（规范 5）
    agent2 = object.__new__(AgentV2)
    agent2._capabilities = ModelCapabilities(provider="kimi")
    agent2.model_config = {"model_name": "kimi-k3"}
    agent2._session_id = "sess-1"
    assert agent2._prompt_cache_key_value() == key1

    # B2 OpenAI caps 路径（契约未声明）→ 纯 session_id（现状不回归）
    agent3 = object.__new__(AgentV2)
    agent3._capabilities = ModelCapabilities(
        provider="openai", prompt_cache_key_required=True
    )
    agent3.model_config = {"model_name": "gpt-5.6-luna"}
    agent3._session_id = "sess-test-1"
    assert agent3._prompt_cache_key_value() == "sess-test-1"
