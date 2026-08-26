"""A20: per-model token 治理 —— 3 新字段默认 + 消费点（fake provider）。"""

from types import SimpleNamespace

import pytest

from config.model_capabilities import (
    DEFAULT_CAPABILITIES,
    ModelCapabilities,
)


# ---- 完成判据 1：四个字段默认全为 None（现状零变化） ---------------------


def test_new_fields_default_to_none():
    """max_output_tokens / few_shot_policy / tool_send_policy / tool_output_token_limit
    默认全 None（现状零变化）。"""
    caps = DEFAULT_CAPABILITIES
    assert caps.max_output_tokens is None
    assert caps.few_shot_policy is None
    assert caps.tool_send_policy is None
    assert caps.tool_output_token_limit is None


def test_default_capabilities_unchanged():
    """默认能力既有字段保持。"""
    caps = DEFAULT_CAPABILITIES
    assert caps.provider == "openai"
    assert caps.context_window == 256_000
    assert caps.tokenizer == "tiktoken:o200k_base"


def test_fields_are_append_only():
    """字段只追加：构造时设定值可读回，未设定保持 None。"""
    caps = ModelCapabilities(
        few_shot_policy="first2",
        tool_send_policy="subset",
        tool_output_token_limit=1000,
    )
    assert caps.few_shot_policy == "first2"
    assert caps.tool_send_policy == "subset"
    assert caps.tool_output_token_limit == 1000
    assert caps.max_output_tokens is None


# ---- 真实消费点：AgentV2._get_core_tools（fake orchestrator） -------------


def _new_agent(caps: ModelCapabilities, tools: list):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._capabilities = caps
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: {t.name: t for t in tools})
    agent._memory = SimpleNamespace(_rag_enabled=False)
    return agent


def test_agent_get_core_tools_role_allowlist_does_not_crop_schema():
    """FX6: role allowlist is an execution deny, not an API schema crop."""
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    names = ["read", "write", "bash", "grep"]
    tools = [SimpleNamespace(name=n) for n in names]
    agent = object.__new__(AgentV2)
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: {t.name: t for t in tools})
    agent._memory = SimpleNamespace(_rag_enabled=False)
    agent._capabilities = SimpleNamespace(tool_send_policy=None)
    agent._role_tool_allowlist = frozenset({"read", "grep"})
    out = {t.name for t in agent._get_core_tools()}
    assert out == set(names)


def test_agent_get_core_tools_default_full():
    """默认（tool_send_policy=None）→ _get_core_tools 全量，现状不变。"""
    tools = [SimpleNamespace(name=f"tool{i:02d}") for i in range(12)]
    agent = _new_agent(DEFAULT_CAPABILITIES, tools)
    out = agent._get_core_tools()
    assert len(out) == 12


def test_agent_get_core_tools_subset():
    """tool_send_policy="subset" → 前 8 个（按名排序确定性子集）。"""
    tools = [SimpleNamespace(name=f"tool{i:02d}") for i in range(12)]
    agent = _new_agent(ModelCapabilities(tool_send_policy="subset"), tools)
    out = agent._get_core_tools()
    assert len(out) == 8
    assert [t.name for t in out] == sorted(t.name for t in tools)[:8]


def test_agent_get_core_tools_subset_small_pool():
    """工具少于 8 个时 subset 返回全部（不截断）。"""
    tools = [SimpleNamespace(name=f"tool{i:02d}") for i in range(4)]
    agent = _new_agent(ModelCapabilities(tool_send_policy="subset"), tools)
    assert len(agent._get_core_tools()) == 4


def test_agent_turn_tools_use_local_build_subset_for_creation_tasks():
    """创建型任务不应每轮携带所有与当前任务无关的工具 schema。"""
    agent = _new_agent(DEFAULT_CAPABILITIES, [
        SimpleNamespace(name=name)
        for name in (
            "agent", "bash", "datetime", "diagnostics", "download_file",
            "download_mcp", "download_skill", "edit", "file_download", "format",
            "git", "glob", "grep", "history", "ls", "memory", "open_file",
            "patch", "question", "read", "skill", "task", "view", "webfetch",
            "websearch", "write",
        )
    ])

    selected = agent._select_turn_tools(
        agent._get_core_tools(),
        "Create a Java Swing number bomb game in the current workspace.",
        requires_web=False,
        allowed_tool_names=None,
    )

    assert {tool.name for tool in selected} == {
        "bash", "datetime", "edit", "format", "git", "glob", "grep", "ls",
        "open_file", "patch", "read", "skill", "write",
    }
    assert "websearch" not in {tool.name for tool in selected}
    assert "diagnostics" not in {tool.name for tool in selected}


def test_agent_turn_tools_keep_research_tools_for_web_tasks():
    """研究任务保留 websearch/webfetch，同时继续使用本地产物工具。"""
    agent = _new_agent(DEFAULT_CAPABILITIES, [
        SimpleNamespace(name=name)
        for name in (
            "bash", "datetime", "edit", "ls", "read", "skill", "webfetch",
            "websearch", "write", "question",
        )
    ])

    selected = agent._select_turn_tools(
        agent._get_core_tools(),
        "Search the web and build a market BI report.",
        requires_web=True,
        allowed_tool_names=None,
    )

    assert {tool.name for tool in selected} == {
        "bash", "datetime", "edit", "ls", "read", "skill", "webfetch", "websearch", "write",
    }


def test_agent_turn_tools_respect_explicit_allowlist():
    """计划/社交等显式 allowlist 不能被任务裁剪策略扩大。"""
    agent = _new_agent(DEFAULT_CAPABILITIES, [
        SimpleNamespace(name=name) for name in ("datetime", "read", "write", "websearch")
    ])
    selected = agent._select_turn_tools(
        agent._get_core_tools(),
        "Create a website",
        requires_web=True,
        allowed_tool_names=frozenset({"read", "datetime"}),
    )

    assert [tool.name for tool in selected] == ["datetime", "read"]


def test_agent_include_few_shot_none_true():
    """few_shot_policy=None（现状）→ include_few_shot=True。"""
    agent = _new_agent(DEFAULT_CAPABILITIES, [])
    assert agent._include_few_shot() is True


def test_agent_include_few_shot_none_value():
    """few_shot_policy="none" → include_few_shot=False。"""
    agent = _new_agent(ModelCapabilities(few_shot_policy="none"), [])
    assert agent._include_few_shot() is False


def test_agent_include_few_shot_full_true():
    """few_shot_policy="full" → include_few_shot=True。"""
    agent = _new_agent(ModelCapabilities(few_shot_policy="full"), [])
    assert agent._include_few_shot() is True


def test_agent_few_shot_limit_none():
    """few_shot_policy=None/full → _few_shot_limit()=None（全量）。"""
    for policy in (None, "full"):
        agent = _new_agent(ModelCapabilities(few_shot_policy=policy), [])
        assert agent._few_shot_limit() is None


def test_agent_few_shot_limit_first2():
    """few_shot_policy="first2" → _few_shot_limit()=2（只留前 2 条）。"""
    agent = _new_agent(ModelCapabilities(few_shot_policy="first2"), [])
    assert agent._few_shot_limit() == 2


def test_format_few_shot_limit_first2():
    """format_few_shot(limit=N) 只注入前 N 条（goal_planner 有 2 条，limit=1 → 1 条）。"""
    from RxyCode.RxyCode1_1_0.core.prompts.few_shot import format_few_shot

    full = format_few_shot("goal_planner")
    assert full.count("Example ") == 2
    limited = format_few_shot("goal_planner", limit=1)
    assert limited.count("Example ") == 1
    assert len(limited) < len(full)


# ---- 8 族 provider：A20 四字段默认全 None（本卡只建参数，默认全量） ---------


@pytest.mark.parametrize("u,model", [
    ("https://api.deepseek.com/v1", "deepseek-v4-flash"),
    ("https://api.openai.com/v1", "gpt-5.6-sol"),
    ("https://api.moonshot.cn/v1", "kimi-k3"),
    ("https://open.bigmodel.cn/api/paas/v4/", "glm-5.2"),
    ("https://api.minimaxi.com/v1", "MiniMax-M3"),
    ("https://api.xiaomimimo.com/v1", "mimo-v2.5-pro"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus"),
    ("https://api.anthropic.com/v1", "claude-opus-5"),
])
def test_family_governance_fields_default_none(u, model):
    """8 族 provider 的 A20 治理字段默认全 None（卡面「只建参数，默认全量」）。

    A20 三个旋钮（few_shot_policy / tool_send_policy / tool_output_token_limit）
    严格断言 is None；max_output_tokens 属 A12/A20 共用能力字段，A13–A18 已
    各设调研值，此处仅断言其为非负整数或 None（本卡不新增治理值）。
    """
    from core import providers

    cfg = {"base_url": u, "model_name": model, "resolved_max_tokens": 8192}
    caps = providers.resolve(cfg).capabilities(cfg)
    assert caps.few_shot_policy is None
    assert caps.tool_send_policy is None
    assert caps.tool_output_token_limit is None
    # max_output_tokens 是 A12/A20 共用能力字段（A13–A18 填调研值），非本卡旋钮
    assert caps.max_output_tokens is None or (
        isinstance(caps.max_output_tokens, int) and caps.max_output_tokens > 0
    )


# ---- 真实消费点：_truncate_tool_text（文本副本，不改 ToolMessage） ----------


def test_truncate_tool_text_none_no_change(monkeypatch):
    """tool_output_token_limit=None 且 B6 字符维度关闭 → 原样返回（token 维度现状）。"""
    agent = _new_agent(DEFAULT_CAPABILITIES, [])
    monkeypatch.setattr(agent, "_tool_output_max_chars", lambda: None)
    text = "x" * 5000
    assert agent._truncate_tool_text(text) == text


def test_truncate_tool_text_returns_copy_keeps_original():
    """截断返回文本副本，原始内容不变（ToolMessage 契约）。"""
    agent = _new_agent(ModelCapabilities(tool_output_token_limit=50), [])
    text = "A" * 300 + "B" * 300 + "C" * 300
    out = agent._truncate_tool_text(text)
    assert text == "A" * 300 + "B" * 300 + "C" * 300  # original untouched
    assert "[truncated]" in out
    assert out.startswith("A")
    assert out.endswith("C")
    assert len(out) < len(text)


def test_truncate_tool_text_short_untouched():
    """内容 token 数 ≤ limit 时不截断。"""
    agent = _new_agent(ModelCapabilities(tool_output_token_limit=10_000), [])
    assert agent._truncate_tool_text("short") == "short"


def test_truncate_tool_text_strictly_bounded():
    """超限时输出估算 token ≤ limit（硬上限，覆盖极小 limit）。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _estimate_tokens

    long_text = "word " * 500  # 远超任何小 limit
    for limit in (1, 2, 5, 20):
        agent = _new_agent(ModelCapabilities(tool_output_token_limit=limit), [])
        out = agent._truncate_tool_text(long_text)
        est = _estimate_tokens(out, agent._tokenizer_spec())
        assert est <= limit, f"limit={limit} exceeded: est={est}"
        # 输出不能是空串；限足够大时保留截断标记。
        assert out.strip() != ""
        if limit >= 10:
            assert "[truncated]" in out


def test_truncate_tool_text_within_limit_untouched():
    """估算 token ≤ limit 时原样返回（不截断）。"""
    agent = _new_agent(ModelCapabilities(tool_output_token_limit=1000), [])
    text = "short"
    assert agent._truncate_tool_text(text) == text


def test_truncate_tool_text_empty_ok():
    agent = _new_agent(ModelCapabilities(tool_output_token_limit=50), [])
    assert agent._truncate_tool_text("") == ""


# ---- 真实消费点：RAG 分支也应用 subset -------------------------------------


def test_agent_get_core_tools_subset_with_rag():
    """RAG 开启时 subset 仍生效（不绕过）。"""
    tools = [SimpleNamespace(name=f"tool{i:02d}") for i in range(12)]
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._capabilities = ModelCapabilities(tool_send_policy="subset")
    agent._tool_orchestrator = SimpleNamespace(get_all=lambda: {t.name: t for t in tools})
    agent._memory = SimpleNamespace(_rag_enabled=True)
    out = agent._get_core_tools()
    assert len(out) == 8
    assert [t.name for t in out] == sorted(t.name for t in tools)[:8]


def test_agent_get_core_tools_subset_session_stable():
    """subset 会话内固定：后续 MCP 工具变化不改变已确定的子集。"""
    tools = [SimpleNamespace(name=f"tool{i:02d}") for i in range(12)]
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    agent._capabilities = ModelCapabilities(tool_send_policy="subset")
    registry = list(tools)
    agent._tool_orchestrator = SimpleNamespace(
        get_all=lambda: {t.name: t for t in registry}
    )
    agent._memory = SimpleNamespace(_rag_enabled=False)
    first = [t.name for t in agent._get_core_tools()]
    assert len(first) == 8
    # 会话中途新增工具（MCP 热载）→ 子集不变。
    registry.append(SimpleNamespace(name="zzz-new-mcp-tool"))
    second = [t.name for t in agent._get_core_tools()]
    assert second == first
    assert "zzz-new-mcp-tool" not in second


# ---- 消费点：max_output_tokens 经 resolver 生效（Phase 3 M4） ---------------


def test_max_output_tokens_feeds_resolver_input():
    """max_output_tokens 作为 resolver 的能力上限输入（A20 卡步骤 3 的 max_tokens 覆盖）。"""
    caps = ModelCapabilities(max_output_tokens=65_536)
    # resolver 在 agent_v2._build_llm_from_config 消费 caps.max_output_tokens；
    # 此处断言字段可被读入 resolver 的 capability_max_output_tokens 参数。
    assert caps.max_output_tokens == 65_536


def test_max_output_tokens_resolver_behavior():
    """Phase-3 resolver：capability_max_output_tokens 作为 provider_default 生效。"""
    from RxyCode.RxyCode1_1_0.config.model_limits import resolve_configured_max_tokens

    caps = ModelCapabilities(max_output_tokens=65_536)
    r = resolve_configured_max_tokens(
        model_config={"model_name": "fake-model", "base_url": "https://x/v1"},
        capability_max_output_tokens=caps.max_output_tokens,
        configured_max_tokens=None,
    )
    assert r.resolved_max_tokens == 65_536


# ---- 消费点：few_shot_policy 决定 include_few_shot --------------------------


def test_few_shot_policy_none_keeps_current():
    """None → 保持现状（include_few_shot 沿用 A9 前行为）。"""
    caps = DEFAULT_CAPABILITIES
    assert caps.few_shot_policy is None


def test_few_shot_policy_values():
    """few_shot_policy 允许 full / first2 / none。"""
    for v in ("full", "first2", "none"):
        caps = ModelCapabilities(few_shot_policy=v)
        assert caps.few_shot_policy == v


# ---- 消费点：tool_output_token_limit 驱动截断阈值 ---------------------------
# （真实实现 _truncate_tool_text 见上方；此处仅保留字段语义测试）
