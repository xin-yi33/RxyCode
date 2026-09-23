"""B3: 断点预算缓存策略（PHASE-B §5 B3）。

移植 opencode 4 断点预算（tools→system→messages、TTL 5m/1h 双档），
把 _apply_cache_control 从"单一 system 断点"升级为完整的断点预算策略：
- Anthropic 系显式 cache_control 打点（按 caps.cache_breakpoints 分配序）
- OpenAI 系 prompt_cache_key（B2 已做），不注入 cache_control（CB3）
- DeepSeek 自动前缀 + 命中字段验证，不注入 cache_control（CB3）
- 末条 user 断点（P0-2 cline 语义）
"""

from __future__ import annotations

import pytest


class TestBreakpointPolicyAllocator:
    """B3 判据 1：断点数量 ≤4、分配序固定、超额丢弃。"""

    def test_budget_limit_four(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import BREAKPOINT_BUDGET

        assert BREAKPOINT_BUDGET == 4

    def test_allocation_order_tools_system_messages(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import allocate_breakpoints

        # 分配序：tools→system→messages
        order = allocate_breakpoints(
            tools=["read", "bash"], system="SYS", messages=["m1", "m2", "m3"]
        )
        assert order == ["tools", "system", "messages"]

    def test_over_budget_discards_not_extends(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            BREAKPOINT_BUDGET,
            allocate_breakpoints,
        )

        result = allocate_breakpoints(
            tools=["a", "b", "c", "d", "e"], system="SYS", messages=["x"]
        )
        assert len(result) <= BREAKPOINT_BUDGET

    def test_budget_forced_capped_at_four(self):
        """luna 重要项：调用方传更大预算也强制 ≤4。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            BREAKPOINT_BUDGET,
            allocate_breakpoints,
        )

        result = allocate_breakpoints(
            tools=["a", "b", "c"], system="SYS", messages=["x"],
            budget=99,
        )
        assert len(result) <= BREAKPOINT_BUDGET

    def test_budget_zero_returns_empty(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import allocate_breakpoints

        assert allocate_breakpoints(
            ["a"], "SYS", ["x"], budget=0
        ) == []


class TestTtlTiers:
    """B3 判据 2：TTL 5m/1h 双档可配。"""

    def test_default_ttl_5m(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import resolve_ttl_seconds

        assert resolve_ttl_seconds({}) == 300  # 5m 默认

    def test_ttl_5m_tier(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import resolve_ttl_seconds

        assert resolve_ttl_seconds({"cache": {"ttl": "5m"}}) == 300

    def test_ttl_1h_tier(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import resolve_ttl_seconds

        assert resolve_ttl_seconds({"cache": {"ttl": "1h"}}) == 3600

    def test_ttl_numeric_seconds_compat(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import resolve_ttl_seconds

        assert resolve_ttl_seconds({"cache": {"ttl": 3600}}) == 3600


class TestApplyCacheControlDispatch:
    """B3 判据 3：Anthropic 含 cache_control、OpenAI 无、DeepSeek 无但验证。"""

    def _make_agent(self, provider_name: str, caps):
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

        agent = object.__new__(UsageTrackingLLM)
        agent._cache_enabled = True
        agent._provider = SimpleNamespace(
            supports_prompt_cache=lambda c: getattr(c, "supports_prompt_cache", False),
            name=provider_name,
        )
        agent._capabilities = caps
        agent._cfg = {}
        agent.model_config = {"model_name": "claude-sonnet-4.5"}
        return agent

    def _msgs(self, n_sys: int = 1, n_user: int = 1, n_tool: int = 0):
        from types import SimpleNamespace

        msgs = []
        for i in range(n_sys):
            msgs.append(
                SimpleNamespace(type="system", content=f"SYS{i}", additional_kwargs={})
            )
        for i in range(n_user):
            msgs.append(
                SimpleNamespace(type="human", content=f"USER{i}", additional_kwargs={})
            )
        for i in range(n_tool):
            msgs.append(
                SimpleNamespace(
                    type="tool", content=f"TOOL{i}", tool_call_id=f"c{i}", additional_kwargs={}
                )
            )
        return msgs

    def test_anthropic_gets_cache_control_on_system(self):
        """Anthropic 系：system 消息带 cache_control ephemeral。"""
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="anthropic",
            supports_prompt_cache=True,
            cache_breakpoints=("system",),
        )
        agent = self._make_agent("anthropic", caps)
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}

    def test_ttl_1h_is_shared_across_system_user_and_tools(self):
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            apply_breakpoint_budget,
            cache_control_for_ttl,
        )

        hour = cache_control_for_ttl(3600)
        assert hour == {"type": "ephemeral", "ttl": "1h"}
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="anthropic",
            supports_prompt_cache=True,
            cache_breakpoints=("tools", "system", "tail"),
        )
        agent = self._make_agent("anthropic", caps)
        agent._cfg = {"cache": {"ttl": 3600}}
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") == hour
        assert out[1].additional_kwargs.get("cache_control") == hour
        msgs, _allocated, ttl = apply_breakpoint_budget(
            self._msgs(),
            tools=["read", "bash"],
            caps=caps,
            cfg={"cache": {"ttl": 3600}},
            contract={"cache_mode": "explicit_breakpoints", "breakpoints_max": 4},
        )
        assert ttl == 3600
        assert msgs[0].additional_kwargs.get("cache_control") == hour
        assert msgs[1].additional_kwargs.get("cache_control") == hour

    def test_openai_gets_no_cache_control(self):
        """OpenAI 系：不注入 cache_control（B2 走 prompt_cache_key，CB3）。"""
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="openai",
            supports_prompt_cache=True,
            cache_breakpoints=(),
        )
        agent = self._make_agent("openai", caps)
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") is None

    def test_deepseek_gets_no_cache_control(self):
        """DeepSeek：不注入 cache_control（自动前缀，CB3）。"""
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="deepseek",
            supports_prompt_cache=True,
            cache_breakpoints=(),
        )
        agent = self._make_agent("deepseek", caps)
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") is None

    def test_unsupported_model_unchanged(self):
        """CB8：不支持缓存时行为与现状一致（无 cache_control）。"""
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        caps = replace(DEFAULT_CAPABILITIES, supports_prompt_cache=False)
        agent = self._make_agent("unknown", caps)
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") is None

    def test_deepseek_hard_block_even_with_bad_config(self):
        """luna 阻断项 3：DeepSeek 即使配置错误覆盖 breakpoints 也不注入。"""
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        # 恶意配置：deepseek provider 被误置 cache_breakpoints 非空
        bad_caps = replace(
            DEFAULT_CAPABILITIES,
            provider="deepseek",
            supports_prompt_cache=True,
            cache_breakpoints=("system",),
        )
        agent = self._make_agent("deepseek", bad_caps)
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") is None

    def test_openai_hard_block_even_with_bad_config(self):
        """luna 阻断项 1：OpenAI 错误配置 breakpoints 也不注入（CB3 白名单）。"""
        from dataclasses import replace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        bad_caps = replace(
            DEFAULT_CAPABILITIES,
            provider="openai",
            supports_prompt_cache=True,
            cache_breakpoints=("system",),
        )
        agent = self._make_agent("openai", bad_caps)
        out = agent._apply_cache_control(self._msgs())
        assert out[0].additional_kwargs.get("cache_control") is None

    def test_breakpoints_limited_by_caps_declared_types(self):
        """luna 阻断项 2：只分配 caps 声明的断点类型。"""
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.cache_policy import apply_breakpoint_budget

        # 只声明 system：存在 user 消息也不打 messages 断点
        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="anthropic",
            cache_breakpoints=("system",),
        )
        msgs = [
            SimpleNamespace(type="system", content="SYS", additional_kwargs={}),
            SimpleNamespace(type="human", content="U1", additional_kwargs={}),
        ]
        out, allocated, _ = apply_breakpoint_budget(msgs, caps=caps, cfg={})
        assert allocated == ["system"]
        assert out[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}
        # 未声明 tail/messages → user 消息不打点
        assert out[1].additional_kwargs.get("cache_control") is None

    def test_tools_participate_in_allocation(self):
        """luna 阻断项 1：tools 传入时参与分配序。"""
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.cache_policy import apply_breakpoint_budget

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="anthropic",
            cache_breakpoints=("tools", "system", "tail"),
        )
        msgs = [
            SimpleNamespace(type="system", content="SYS", additional_kwargs={}),
            SimpleNamespace(type="human", content="U1", additional_kwargs={}),
        ]
        _out, allocated, _ = apply_breakpoint_budget(
            msgs, tools=["read", "bash"], caps=caps, cfg={}
        )
        assert allocated == ["tools", "system", "messages"]

    def test_anthropic_llm_kwargs_injects_cache_ttl(self):
        """TTL is not a Chat Completions extra_body field on Anthropic."""
        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.providers.anthropic import AnthropicProvider

        provider = AnthropicProvider()
        kwargs = provider.llm_kwargs(
            {
                "model_name": "claude-sonnet-5",
                "cache_ttl": 3600,
                "resolved_max_tokens": 2048,
                "api_key": "test-key",
                "base_url": "https://relay.example/v1",
            },
            DEFAULT_CAPABILITIES,
        )
        extra = kwargs.get("extra_body") or {}
        assert "cache_ttl" not in extra

    def test_anthropic_tools_breakpoint_in_raw_stream(self):
        """luna 阻断项 2：Anthropic tools 断点注入真实 _raw_stream payload。"""
        import asyncio
        from dataclasses import replace
        from types import SimpleNamespace

        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        captured: dict = {}

        class FakeClient:
            def create(self, **payload):
                captured["payload"] = payload
                raise RuntimeError("stop-after-capture")

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="anthropic",
            cache_breakpoints=("tools", "system"),
        )
        agent = object.__new__(AgentV2)
        agent._session_id = "sess-t"
        agent._llm = SimpleNamespace()
        agent._rate_limiter = None
        agent.model_config = {"model_name": "claude-sonnet-4.5"}
        agent._capabilities = caps
        agent._provider = None
        agent._resolve_request_max_tokens = lambda _n: 2048
        agent._openai_client = lambda: FakeClient()

        tool = StructuredTool.from_function(
            lambda: "ok", name="read", description="read files"
        )
        sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
        with pytest.raises(RuntimeError):
            asyncio.run(
                agent._raw_stream([sys_msg, user_msg], tools=[tool]).__anext__()
            )

        payload = captured["payload"]
        tools = payload.get("tools") or []
        assert tools, "tools missing from payload"
        for tool_def in tools:
            assert tool_def.get("cache_control") == {
                "type": "ephemeral",
                "ttl": "1h",
            }

    def test_openai_tools_no_breakpoint(self):
        """luna 阻断项 1：OpenAI 系 tools 不注入 cache_control（CB3）。"""
        import asyncio
        from dataclasses import replace
        from types import SimpleNamespace

        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        captured: dict = {}

        class FakeClient:
            def create(self, **payload):
                captured["payload"] = payload
                raise RuntimeError("stop-after-capture")

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="openai",
            cache_breakpoints=("tools", "system"),
        )
        agent = object.__new__(AgentV2)
        agent._session_id = "sess-t"
        agent._llm = SimpleNamespace()
        agent._rate_limiter = None
        agent.model_config = {"model_name": "gpt-5.6-luna"}
        agent._capabilities = caps
        agent._provider = None
        agent._resolve_request_max_tokens = lambda _n: 2048
        agent._openai_client = lambda: FakeClient()

        tool = StructuredTool.from_function(
            lambda: "ok", name="read", description="read files"
        )
        sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
        with pytest.raises(RuntimeError):
            asyncio.run(
                agent._raw_stream([sys_msg, user_msg], tools=[tool]).__anext__()
            )

        payload = captured["payload"]
        tools = payload.get("tools") or []
        assert tools
        for tool_def in tools:
            assert tool_def.get("cache_control") is None


class TestLastUserBreakpoint:
    """B3 判据 4：末条 user 断点（P0-2 cline 语义）。"""

    def test_last_user_message_marked(self):
        """Anthropic tail 断点：最后一条 user 消息被标记。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            mark_last_user_breakpoint,
        )

        from types import SimpleNamespace

        msgs = [
            SimpleNamespace(type="system", content="SYS", additional_kwargs={}),
            SimpleNamespace(type="human", content="U1", additional_kwargs={}),
            SimpleNamespace(type="ai", content="A1", additional_kwargs={}),
            SimpleNamespace(type="human", content="U2", additional_kwargs={}),
        ]
        out = mark_last_user_breakpoint(msgs)
        # 最后 user 消息（索引 3）被标记
        assert out[3].additional_kwargs.get("cache_control") == {"type": "ephemeral"}
        # 早期 user 不被标记
        assert out[1].additional_kwargs.get("cache_control") is None

    def test_no_user_no_mark(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import mark_last_user_breakpoint

        from types import SimpleNamespace

        msgs = [SimpleNamespace(type="system", content="S", additional_kwargs={})]
        out = mark_last_user_breakpoint(msgs)
        assert len(out) == 1
        assert out[0].additional_kwargs.get("cache_control") is None

    def test_does_not_mutate_original_messages(self):
        """luna 次要项：mark_last_user_breakpoint 不改原消息对象。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import mark_last_user_breakpoint

        from types import SimpleNamespace

        user = SimpleNamespace(type="human", content="U1", additional_kwargs={})
        msgs = [
            SimpleNamespace(type="system", content="SYS", additional_kwargs={}),
            user,
        ]
        out = mark_last_user_breakpoint(msgs)
        assert out[1].additional_kwargs.get("cache_control") == {"type": "ephemeral"}
        # 原对象未被修改
        assert user.additional_kwargs.get("cache_control") is None
        assert msgs[1] is user

    def test_apply_breakpoint_budget_system_and_tail(self):
        """apply_breakpoint_budget 统一入口：system + 末条 user 断点 + TTL。"""
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.cache_policy import apply_breakpoint_budget

        caps = replace(
            DEFAULT_CAPABILITIES,
            provider="anthropic",
            cache_breakpoints=("system", "tail"),
        )
        msgs = [
            SimpleNamespace(type="system", content="SYS", additional_kwargs={}),
            SimpleNamespace(type="human", content="U1", additional_kwargs={}),
        ]
        out, allocated, ttl = apply_breakpoint_budget(
            msgs, caps=caps, cfg={"cache": {"ttl": "1h"}}
        )
        assert allocated == ["system", "messages"]
        assert ttl == 3600
        assert out[0].additional_kwargs.get("cache_control") == {
            "type": "ephemeral",
            "ttl": "1h",
        }
        assert out[1].additional_kwargs.get("cache_control") == {
            "type": "ephemeral",
            "ttl": "1h",
        }

    def test_consecutive_tool_results_merged_not_split(self):
        """合并连续 tool_result：不拆 assistant↔tool 配对（kimi 语义）。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity

        from types import SimpleNamespace

        msgs = [
            SimpleNamespace(type="ai", content="", tool_calls=[{"id": "c1"}], additional_kwargs={}),
            SimpleNamespace(type="tool", content="R1", tool_call_id="c1", additional_kwargs={}),
            SimpleNamespace(type="tool", content="R2", tool_call_id="c1", additional_kwargs={}),
        ]
        # 完整性检查：tool 消息必须跟在带对应 tool_call 的 assistant 之后
        assert tool_pair_integrity(msgs) is True

    def test_tool_not_immediately_after_assistant_rejected(self):
        """luna 阻断项 2：tool 与 assistant 之间插入普通消息 → False。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity

        from types import SimpleNamespace

        msgs = [
            SimpleNamespace(type="ai", content="", tool_calls=[{"id": "c1"}], additional_kwargs={}),
            SimpleNamespace(type="human", content="interrupt", additional_kwargs={}),
            SimpleNamespace(type="tool", content="R1", tool_call_id="c1", additional_kwargs={}),
        ]
        assert tool_pair_integrity(msgs) is False

    def test_tool_without_call_id_rejected(self):
        """luna 阻断项 2：tool_call_id 缺失的孤儿 tool → False。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity

        from types import SimpleNamespace

        msgs = [
            SimpleNamespace(type="ai", content="", tool_calls=[{"id": "c1"}], additional_kwargs={}),
            SimpleNamespace(type="tool", content="R1", tool_call_id=None, additional_kwargs={}),
        ]
        assert tool_pair_integrity(msgs) is False

    def test_orphan_tool_rejected(self):
        """无 assistant 声明的 tool → False。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity

        from types import SimpleNamespace

        msgs = [
            SimpleNamespace(type="tool", content="R1", tool_call_id="c9", additional_kwargs={}),
        ]
        assert tool_pair_integrity(msgs) is False

    def test_unconsumed_tool_call_rejected(self):
        """luna 阻断项 2：assistant 声明但 tool result 缺失 → False。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity

        from types import SimpleNamespace

        msgs = [
            SimpleNamespace(type="ai", content="", tool_calls=[{"id": "c1"}, {"id": "c2"}], additional_kwargs={}),
            SimpleNamespace(type="tool", content="R1", tool_call_id="c1", additional_kwargs={}),
        ]
        # c2 未消费 → 配对不完整
        assert tool_pair_integrity(msgs) is False


class TestDeepSeekAutoPrefixVerify:
    """B3 判据 3 附加：DeepSeek 自动前缀命中字段验证。"""

    def test_deepseek_hit_field_verify(self):
        """DeepSeek 自动前缀验证：从 usage 提取 prompt_cache_hit_tokens。"""
        from RxyCode.RxyCode1_1_0.core.providers.deepseek import (
            _DEEPSEEK_USAGE,
        )

        assert "prompt_cache_hit_tokens" in _DEEPSEEK_USAGE.cache_read_flat

    def test_verify_deepseek_prefix_warns_on_miss(self):
        """DeepSeek 命中字段缺失/为零时记录警告而非静默。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import verify_deepseek_prefix

        # 0 命中 = 冷启动或前缀被破坏 → 警告路径（返回 False 表示未验证通过）
        assert verify_deepseek_prefix(0, 0) is False
        assert verify_deepseek_prefix(100, 50) is True

    def test_deepseek_verification_wired_into_record_usage(self):
        """luna 阻断项 3：DeepSeek 验证接入 _record_usage 真实链路。

        provider.name=='deepseek' 时，raw chunk usage 记录后调用
        verify_deepseek_prefix（命中>0 → True，不阻塞）。
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        chunk = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=500,
                prompt_cache_hit_tokens=800,
                prompt_tokens_details=None,
            ),
            usage_metadata=None,
            content=None,
        )
        provider = SimpleNamespace(
            name="deepseek",
            extract_cache_read=lambda usage, caps: usage.get(
                "prompt_cache_hit_tokens", 0
            ),
        )
        with patch(
            "RxyCode.RxyCode1_1_0.core.cache_policy.verify_deepseek_prefix",
            return_value=True,
        ) as mock_verify:
            _record_usage(
                chunk, provider=provider, caps=SimpleNamespace()
            )
            mock_verify.assert_called_once_with(1000, 800)
        assert token_stats.prompt_tokens == 1000
        assert token_stats.cache_hit_tokens == 800

    def test_non_deepseek_no_verification(self):
        """非 DeepSeek provider 不触发前缀验证（分派正确）。"""
        from types import SimpleNamespace
        from unittest.mock import patch

        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        chunk = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=1000,
                completion_tokens=500,
                prompt_cache_hit_tokens=800,
                prompt_tokens_details=None,
            ),
            usage_metadata=None,
            content=None,
        )
        provider = SimpleNamespace(
            name="openai",
            extract_cache_read=lambda usage, caps: usage.get(
                "prompt_tokens_details", {}
            ).get("cached_tokens", 0) if isinstance(usage.get("prompt_tokens_details"), dict) else 0,
        )
        with patch(
            "RxyCode.RxyCode1_1_0.core.cache_policy.verify_deepseek_prefix",
            return_value=True,
        ) as mock_verify:
            _record_usage(
                chunk, provider=provider, caps=SimpleNamespace()
            )
            mock_verify.assert_not_called()

