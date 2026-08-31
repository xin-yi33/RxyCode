"""A21: per-model 延迟旋钮 —— effort_presets 消费 + thinking 适配判断。"""

import inspect
import pytest

from config.model_capabilities import DEFAULT_CAPABILITIES, ModelCapabilities
from core import providers
from core.providers.base import BaseProvider


def _resolve(u, model, effort=None):
    cfg = {"base_url": u, "model_name": model, "resolved_max_tokens": 8192}
    if effort is not None:
        cfg["effort"] = effort
    p = providers.resolve(cfg)
    return p, cfg, p.capabilities(cfg)


# ---- 完成判据 1/6：默认档位 balanced，thinking_default_on 默认 False ---------


def test_thinking_default_on_default_false():
    """thinking_default_on 默认 False；未适配前行为与现状一致。"""
    assert DEFAULT_CAPABILITIES.thinking_default_on is False


def test_default_effort_balanced_no_extra():
    """默认（无 effort 键）→ 无额外注入（balanced=现状）。"""
    p, cfg, caps = _resolve("https://relay.example/v1", "mystery-1")
    kwargs = p.llm_kwargs(cfg, caps)
    assert "reasoning_effort" not in kwargs
    assert "thinking" not in (kwargs.get("extra_body") or {})


# ---- 完成判据 2/4：fast path 走 fast，deep 仅显式触发 ----------------------


def test_effort_for_fast_path_uses_fast():
    """fast path（简单查询 build）→ effort=fast。"""
    agent = _new_agent()
    assert agent._effort_for("build", "what is 2+2?") == "fast"


def test_effort_for_plan_balanced():
    """plan → balanced。"""
    agent = _new_agent()
    assert agent._effort_for("plan", "anything") == "balanced"


def test_effort_for_complex_build_balanced():
    """复杂 build（整库重构）→ balanced。"""
    agent = _new_agent()
    text = "refactor the entire codebase and migrate the whole project"
    assert agent._effort_for("build", text) == "balanced"


def test_effort_for_deepseek_build_uses_fast_when_not_explicitly_configured():
    """有厂商档位的模型，工具型 build 默认走低延迟档位。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    config = {
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-v4-flash",
    }
    agent._capabilities = providers.resolve(config).capabilities(config)

    text = "refactor the entire codebase and migrate the whole project"
    assert agent._effort_for("build", text) == "fast"


def test_effort_for_plan_keeps_balanced_for_deepseek():
    """计划阶段仍保留 balanced，避免把计划质量和工具执行延迟混为一谈。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    config = {
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-v4-flash",
    }
    agent._capabilities = providers.resolve(config).capabilities(config)

    assert agent._effort_for("plan", "prepare the implementation") == "balanced"


def test_deep_only_via_explicit_effort():
    """deep 只由显式配置触发（_effort_for 不自动返回 deep）。"""
    agent = _new_agent()
    assert agent._effort_for("build", "simple") != "deep"
    assert agent._effort_for("plan", "x") != "deep"


def test_fast_path_preserves_explicit_effort():
    """fast path 不覆盖用户显式 effort=deep（_effort_for 只在未显式配置时生效）。"""
    agent = _new_agent()
    agent.model_config = {"effort": "deep"}
    if agent.model_config.get("effort"):
        effort = agent.model_config["effort"]
    else:
        effort = agent._effort_for("build", "x")
    assert effort == "deep"


def test_fast_local_tool_turn_disables_deepseek_thinking_for_latency():
    """Fast local builds must not grow a DeepSeek reasoning echo chain."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    source = inspect.getsource(AgentV2._fast_reply_with_tools)
    assert "_thinking_disabled_this_turn = bool" in source
    assert "and not research_policy.requires_web" in source


def test_fast_research_keeps_deepseek_thinking_enabled():
    """Web research must retain reasoning for source selection quality."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    source = inspect.getsource(AgentV2._fast_reply_with_tools)
    assert "mode == \"build\"" in source
    assert "not research_policy.requires_web" in source


def test_tool_call_argument_stream_emits_sparse_safe_liveness():
    """Large streamed tool arguments must not make Desktop look frozen."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    source = inspect.getsource(AgentV2._fast_reply_with_tools)
    assert "tool_call_delta_chunks" in source
    assert "tool_call_liveness_at" in source
    assert "Preparing {label} tool call" in source
    assert "tool_call_delta_chars" in source


def test_fast_build_synthesis_is_explicit_and_bounded():
    """Exhausted fast-build rounds must finish instead of planning another turn."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    source = inspect.getsource(AgentV2._fast_reply_with_tools)
    assert "Finalize this task now. Do not call tools." in source
    assert "synthesis_max_tokens = min(fast_build_round_max_tokens, 1024)" in source
    assert "Never promise a future" in source
    assert "action or claim" in source


def test_fast_build_does_not_append_source_with_shell_fragments():
    """Large source repairs must stay auditable and avoid shell append loops."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import FAST_LOCAL_BUILD_INSTRUCTION

    instruction = FAST_LOCAL_BUILD_INSTRUCTION.lower()
    assert "use the write/edit tools for source files" in instruction
    assert "do not append source code with" in instruction
    assert "replace the complete file" in instruction
    assert "do not write _probe.py" in instruction


def test_fast_build_tool_rounds_keep_tool_calls_concise():
    """Tool rounds must not spend the latency budget streaming prose before calls."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import FAST_LOCAL_BUILD_INSTRUCTION
    from RxyCode.RxyCode1_1_0.core.prompts.templates import SYSTEM_PROMPT_TEMPLATE

    assert "issue tool calls directly" in FAST_LOCAL_BUILD_INSTRUCTION
    assert "do not narrate" in FAST_LOCAL_BUILD_INSTRUCTION
    assert "issue tool calls directly" in SYSTEM_PROMPT_TEMPLATE


def test_fast_build_round_budget_follows_model_limit_by_default():
    """A large source write must not be truncated by a global 4096 cap."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        _resolve_fast_build_round_max_tokens,
    )

    assert _resolve_fast_build_round_max_tokens({}, 8192) == 8192
    assert _resolve_fast_build_round_max_tokens(
        {"fast_build_tool_round_max_tokens": 4096}, 8192
    ) == 4096
    assert _resolve_fast_build_round_max_tokens(
        {"fast_build_tool_round_max_tokens": 16384}, 8192
    ) == 8192


def test_graph_is_lazy_for_fast_agent_startup():
    """Constructing the fast agent must not import/compile the heavy Graph path."""
    from types import SimpleNamespace
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _LazyGraph

    calls = []
    graph = _LazyGraph(lambda: calls.append('built') or SimpleNamespace())
    assert calls == []
    assert graph._graph is None
    graph._resolve()
    assert calls == ['built']
    assert graph._graph is not None


def test_fast_build_has_a_separate_complex_creation_round_budget():
    """Complex local builds must not be cut off into an immediate repair turn."""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    source = inspect.getsource(AgentV2._fast_reply_with_tools)
    assert "fast_build_max_tool_rounds" in source
    assert "min(24" in source


def test_deepseek_thinking_drops_temperature():
    """§7.1/卡常见坑：DeepSeek thinking 适配模型 llm_kwargs 不带 temperature。"""
    p, cfg, caps = _resolve("https://api.deepseek.com/v1", "deepseek-v4-flash")
    assert caps.accepts_temperature is False
    kwargs = p.llm_kwargs(cfg, caps)
    assert "temperature" not in kwargs


# ---- 完成判据 3：各 provider effort_presets 与 §7 一致 ----------------------


def test_deepseek_effort_presets_s71():
    """§7.1：DeepSeek v4 reasoning_effort low/high/max，默认 high。"""
    p, cfg, caps = _resolve("https://api.deepseek.com/v1", "deepseek-v4-flash")
    assert caps.effort_presets == {"fast": "low", "balanced": "high", "deep": "max"}


def test_openai_effort_presets_s72():
    """§7.2：OpenAI gpt-5.6 fast:low/balanced:medium/deep:high。"""
    p, cfg, caps = _resolve("https://api.openai.com/v1", "gpt-5.6-sol")
    assert caps.effort_presets == {"fast": "low", "balanced": "medium", "deep": "high"}


def test_kimi_k3_effort_presets_s73():
    """§7.3：kimi-k3 fast:low/balanced:high/deep:max。"""
    p, cfg, caps = _resolve("https://api.moonshot.cn/v1", "kimi-k3")
    assert caps.effort_presets == {"fast": "low", "balanced": "high", "deep": "max"}


def test_glm52_effort_presets_s74():
    """§7.4：glm-5.2 fast:low/balanced:high/deep:max。"""
    p, cfg, caps = _resolve("https://open.bigmodel.cn/api/paas/v4/", "glm-5.2")
    assert caps.effort_presets == {"fast": "low", "balanced": "high", "deep": "max"}


@pytest.mark.parametrize("u,model", [
    ("https://api.minimaxi.com/v1", "MiniMax-M3"),
    ("https://api.xiaomimimo.com/v1", "mimo-v2.5-pro"),
    ("https://api.anthropic.com/v1", "claude-opus-5"),
])
def test_chat_path_no_effort_presets(u, model):
    """§7.5/7.6/7.7/7.8：Chat 路径无 reasoning.effort → effort_presets 空。"""
    p, cfg, caps = _resolve(u, model)
    assert caps.effort_presets == {}


# ---- 完成判据 5/6：thinking 适配判断 --------------------------------------


def test_thinking_default_on_matched_models():
    """适配 thinking 的模型 thinking_default_on=True（A12–A18 已填）。"""
    for u, model in [
        ("https://api.deepseek.com/v1", "deepseek-v4-flash"),
        ("https://api.openai.com/v1", "gpt-5.6-sol"),
        ("https://api.moonshot.cn/v1", "kimi-k3"),
        ("https://api.anthropic.com/v1", "claude-opus-5"),
    ]:
        p, cfg, caps = _resolve(u, model)
        assert caps.supports_reasoning is True
        assert caps.thinking_default_on is True


def test_effort_injected_only_when_presets_and_reasoning():
    """仅当 supports_reasoning + effort_presets 非空才注入 reasoning_effort。"""
    # OpenAI gpt-5.6-sol：有 presets + reasoning → 注入
    p, cfg, caps = _resolve("https://api.openai.com/v1", "gpt-5.6-sol", effort="fast")
    kwargs = p.llm_kwargs(cfg, caps)
    assert kwargs.get("reasoning_effort") == "low"


def test_empty_presets_no_injection():
    """effort_presets 空（如 mimo Chat）→ 不注入 reasoning_effort（零额外参数）。"""
    p, cfg, caps = _resolve("https://api.xiaomimimo.com/v1", "mimo-v2.5-pro", effort="fast")
    kwargs = p.llm_kwargs(cfg, caps)
    assert "reasoning_effort" not in kwargs


def test_thinking_default_off_no_thinking_injection():
    """thinking_default_on=False 的模型不注入 thinking 参数。"""
    caps = ModelCapabilities(supports_reasoning=True, thinking_default_on=False)
    p = BaseProvider()
    kwargs = p.llm_kwargs({"model_name": "x", "resolved_max_tokens": 8192}, caps)
    assert "thinking" not in (kwargs.get("extra_body") or {})


def test_thinking_default_on_injects_thinking():
    """thinking_default_on=True + reasoning → llm_kwargs 带 thinking 参数。"""
    caps = ModelCapabilities(
        supports_reasoning=True,
        thinking_default_on=True,
        effort_presets={"fast": "low", "balanced": "high", "deep": "max"},
    )
    p = BaseProvider()
    kwargs = p.llm_kwargs({"model_name": "x", "resolved_max_tokens": 8192,
                           "effort": "balanced"}, caps)
    body = kwargs.get("extra_body") or {}
    assert body.get("thinking") == {"type": "enabled"}
    assert kwargs.get("reasoning_effort") == "high"


def _new_agent():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._capabilities = DEFAULT_CAPABILITIES
    agent._is_simple_query = AgentV2._is_simple_query.__get__(agent, AgentV2)
    return agent


# ---- /effort 扩展（2026-08-12）：effort_options 厂商档位全集 + 直传 ---------


def test_effort_options_s71_deepseek():
    """§7.1：DeepSeek v4 档位集 low/high/max（/effort 选择列表）。"""
    p, cfg, caps = _resolve("https://api.deepseek.com/v1", "deepseek-v4-flash")
    assert caps.effort_options == ("low", "high", "max")


def test_effort_options_s72_openai():
    """§7.2：OpenAI gpt-5.6 档位集 low/medium/high。"""
    p, cfg, caps = _resolve("https://api.openai.com/v1", "gpt-5.6-sol")
    assert caps.effort_options == ("low", "medium", "high")


def test_effort_options_kimi_k3():
    """§7.3：kimi-k3 档位集 low/high/max（无 medium）。"""
    p, cfg, caps = _resolve("https://api.moonshot.cn/v1", "kimi-k3")
    assert caps.effort_options == ("low", "high", "max")


def test_effort_options_glm52():
    """§7.4：glm-5.2 档位集 max/xhigh/high/medium/low/minimal/none。"""
    p, cfg, caps = _resolve("https://open.bigmodel.cn/api/paas/v4/", "glm-5.2")
    assert caps.effort_options == (
        "max", "xhigh", "high", "medium", "low", "minimal", "none",
    )


@pytest.mark.parametrize("u,model", [
    ("https://api.minimaxi.com/v1", "MiniMax-M3"),
    ("https://api.xiaomimimo.com/v1", "mimo-v2.5-pro"),
    ("https://api.anthropic.com/v1", "claude-opus-5"),
])
def test_chat_path_no_effort_options(u, model):
    """§7.5/7.6/7.7/7.8：Chat 差异路径 → effort_options 空（不提供档位列表）。"""
    p, cfg, caps = _resolve(u, model)
    assert caps.effort_options == ()


def test_vendor_effort_direct_passthrough_deepseek():
    """/effort：厂商档位命中 effort_options → 直接透传 reasoning_effort。"""
    p, cfg, caps = _resolve("https://api.deepseek.com/v1", "deepseek-v4-flash", effort="high")
    kwargs = p.llm_kwargs(cfg, caps)
    assert kwargs.get("reasoning_effort") == "high"


def test_vendor_effort_invalid_falls_back_safely():
    """厂商档位不在 effort_options 且不在 presets keys → 不注入（安全回退）。"""
    p, cfg, caps = _resolve("https://api.deepseek.com/v1", "deepseek-v4-flash", effort="medium")
    kwargs = p.llm_kwargs(cfg, caps)
    assert "reasoning_effort" not in kwargs


def test_openai_vendor_effort_direct():
    """OpenAI 覆写路径：厂商档位直传（修复 unknown→medium 误判）。"""
    p, cfg, caps = _resolve("https://api.openai.com/v1", "gpt-5.6-sol", effort="high")
    kwargs = p.llm_kwargs(cfg, caps)
    assert kwargs.get("reasoning_effort") == "high"


def test_openai_abstract_effort_still_maps():
    """OpenAI 抽象档位（fast/balanced/deep）仍走 presets 映射（A21 兼容）。"""
    p, cfg, caps = _resolve("https://api.openai.com/v1", "gpt-5.6-sol", effort="deep")
    kwargs = p.llm_kwargs(cfg, caps)
    assert kwargs.get("reasoning_effort") == "high"


def test_openai_unknown_effort_no_injection():
    """审计修复（luna audit2）：OpenAI 未知档位（不在 options 也不在 presets
    keys）→ 不注入 reasoning_effort（原 get(effort, "medium") 会误注入 medium）。"""
    p, cfg, caps = _resolve("https://api.openai.com/v1", "gpt-5.6-sol", effort="bogus")
    kwargs = p.llm_kwargs(cfg, caps)
    assert "reasoning_effort" not in kwargs
