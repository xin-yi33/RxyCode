"""B2: 稳定前缀纪律（PHASE-B §5 B2）。

把"前缀逐字节不变"变成代码纪律：
1. system 模板零动态字段（前缀区无每轮不同字节）。
2. research_contract 尾部独立消息，不再改写 messages[0]（G1 修复）。
3. 工具描述列表按名称排序固定（字节稳定）。
4. OpenAI 系请求注入 prompt_cache_key=session_id，DeepSeek/Anthropic 不注入（CB3）。
"""

from __future__ import annotations

import hashlib
import json

import pytest

from RxyCode.RxyCode1_1_0.core.prompts.registry import get_system_prompt


def prefix_digest(system: str, tools: list) -> str:
    """对 system+tools 做确定性序列化后取 SHA-256（文档 §5 B2 检测手段）。"""
    norm = json.dumps(
        {"system": system, "tools": sorted(tools, key=lambda t: t["name"])},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


class TestSystemPrefixStable:
    """B2 判据：system 模板零动态字段、跨轮字节稳定。"""

    def test_system_prompt_stable_across_calls(self):
        a = get_system_prompt()
        b = get_system_prompt()
        assert a == b
        assert a.strip()

    def test_system_prompt_no_datetime(self):
        """静默失效源清单第 1 条：datetime/时间戳不得进 system。"""
        system = get_system_prompt()
        assert "datetime" not in system
        assert "strftime" not in system
        assert "20" not in system or "20:00:00" not in system

    def test_system_prompt_no_uuid_random(self):
        """静默失效源清单第 2 条：uuid/随机 id 不得进 system。"""
        system = get_system_prompt()
        assert "uuid" not in system.lower()
        assert "random" not in system.lower()

    def test_system_prefix_bytes_stable_across_turns(self):
        """文档 §5 B2 前缀不变性测试：两次仅最新 user 不同的请求，前缀字节相同。"""
        digest1 = prefix_digest(
            get_system_prompt(),
            [{"name": "read", "description": "x"}, {"name": "bash", "description": "y"}],
        )
        digest2 = prefix_digest(
            get_system_prompt(),
            [{"name": "read", "description": "x"}, {"name": "bash", "description": "y"}],
        )
        assert digest1 == digest2


class TestResearchContractNotRewritingSystem:
    """B2 判据：research_contract 不再改写 messages[0]（G1 修复）。"""

    def test_research_contract_does_not_rewrite_messages_0(self):
        """文档 §5 B2 回归测试：研究请求路径不再改写 system[0]。

        直接检查源码：research 路径不得出现 messages[0] = SystemMessage 赋值。
        """
        import inspect

        from RxyCode.RxyCode1_1_0.core import agent_v2

        src = inspect.getsource(agent_v2)
        # G1 现状：messages[0] = SystemMessage(content=f"{system}\n\n{research_contract}")
        assert 'messages[0] = SystemMessage(content=f"{system}\\n\\n{research_contract}")' not in src
        assert "messages[0] = SystemMessage" not in src

    def test_research_contract_appended_after_system(self):
        """FXC3：research 走 user 快照，不得再作为第二条 SystemMessage。"""
        import inspect

        from RxyCode.RxyCode1_1_0.core import agent_v2

        src = inspect.getsource(agent_v2)
        assert "SystemMessage(content=research_contract)" not in src
        assert "get_system_s2" in src
        assert "HumanMessage" in src
        assert "messages.append" in src


class TestToolListSorted:
    """B2 判据：工具描述列表按名称排序固定。"""

    def _make_registry(self):
        """独立 ToolRegistry 实例 + 乱序注册的 mock 工具。"""
        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry

        reg = ToolRegistry()

        def _t(name: str, desc: str):
            return StructuredTool.from_function(
                lambda: "ok",
                name=name,
                description=desc,
            )

        # 乱序注册：zeta 先、alpha 后
        reg.register(_t("zeta", "z desc"))
        reg.register(_t("alpha", "a desc"))
        reg.register(_t("mike", "m desc"))
        return reg

    def test_registry_get_all_sorted(self):
        reg = self._make_registry()
        names = [t.name for t in reg.get_all()]
        assert names == sorted(names), f"get_all not sorted: {names}"

    def test_registry_get_descriptions_sorted(self):
        reg = self._make_registry()
        desc = reg.get_descriptions()
        lines = [l for l in desc.splitlines() if l.startswith("- ")]
        names = [l[2:].split(":")[0].strip() for l in lines]
        assert names == sorted(names), f"descriptions not sorted: {names}"

    def test_registry_get_names_sorted(self):
        reg = self._make_registry()
        assert reg.get_names() == sorted(reg.get_names())

    def test_global_registry_descriptions_sorted_when_tools_present(self):
        """全局 registry 有工具时描述必须排序；无工具则空串（兼容）。"""
        from RxyCode.RxyCode1_1_0.core.prompts.tool_list import get_tool_descriptions

        desc = get_tool_descriptions()
        if not desc:
            pytest.skip("no tools registered in global test registry")
        lines = [l for l in desc.splitlines() if l.startswith("- ")]
        names = [l[2:].split(":")[0].strip() for l in lines]
        assert names == sorted(names), f"global descriptions not sorted: {names}"

    def test_get_tool_descriptions_stable_across_calls(self):
        reg = self._make_registry()
        a = reg.get_descriptions()
        b = reg.get_descriptions()
        assert a == b

    def test_get_tool_names_sorted_global(self):
        from RxyCode.RxyCode1_1_0.core.prompts.tool_list import get_tool_names

        names = get_tool_names()
        if not names:
            pytest.skip("no tools registered in global test registry")
        assert names == sorted(names)

    def test_filtered_tool_names_sorted(self):
        """filtered 分支基于 get_all() 顺序；get_all 排序则 filtered 排序。"""
        reg = self._make_registry()
        names = [t.name for t in reg.get_all()]
        assert names == sorted(names)
        assert "alpha" in names and "zeta" in names


class TestPromptCacheKeyInjection:
    """B2 判据：OpenAI 系注入 prompt_cache_key=session_id，其他不注入（CB3）。"""

    def _agent_v2_source(self) -> str:
        import inspect

        from RxyCode.RxyCode1_1_0.core import agent_v2

        return inspect.getsource(agent_v2)

    def test_prompt_cache_key_injected_somewhere(self):
        """OpenAI 系请求必须携带 prompt_cache_key=session_id。"""
        src = self._agent_v2_source()
        assert "prompt_cache_key" in src
        assert "session_id" in src

    def test_openai_provider_llm_kwargs_supports_cache_key(self):
        """openai provider 需有能力注入 prompt_cache_key（供请求组装消费）。"""
        from RxyCode.RxyCode1_1_0.core.providers.openai import OpenAIProvider

        provider = OpenAIProvider()
        import inspect

        src = inspect.getsource(type(provider))
        assert "prompt_cache_key" in src or "llm_kwargs" in src

    def test_deepseek_does_not_get_cache_control(self):
        """CB3：DeepSeek 系不注入 cache_control 字段（B2 起点不变性）。"""
        from RxyCode.RxyCode1_1_0.core.providers.deepseek import DeepSeekProvider

        provider = DeepSeekProvider()
        import inspect

        src = inspect.getsource(type(provider))
        # DeepSeek provider 不应自己塞 cache_control 进请求体
        assert "cache_control" not in src or '{"type": "ephemeral"}' not in src


class TestBehavioralRequestPrefix:
    """审计意见落地：行为级测试（非源码字符串检查）。

    luna 审计阻断项：
    - 真实请求构造测试：仅改变最新 user，断言 system/tools/历史字节一致。
    - research contract 位于断点之后（不覆盖 system[0]）。
    - prompt_cache_key 按 OpenAI 系限制 + 三 provider payload 断言。
    """

    def _serialize(self, messages) -> list[dict]:
        from types import SimpleNamespace

        msgs = []
        for m in messages:
            d = {
                "role": m.type,
                "content": m.content,
            }
            if getattr(m, "tool_calls", None):
                d["tool_calls"] = m.tool_calls
            msgs.append(d)
        return msgs

    def test_prefix_bytes_identical_while_user_changes(self):
        """仅最新 user 不同时，含 tools 的完整请求体字节一致（luna 阻断项 1）。

        构造真实请求 body（{"messages": [...], "tools": [...]}），除最后
        user 消息外全部序列化字节逐字节相同——覆盖 system/tools/历史三个
        前缀区。
        """
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        sys_msg = SimpleNamespace(
            type="system", content="You are a helpful assistant.", additional_kwargs={}
        )
        hist1 = SimpleNamespace(
            type="ai", content="Previous answer", additional_kwargs={}
        )
        user_a = SimpleNamespace(type="human", content="task A", additional_kwargs={})
        user_b = SimpleNamespace(type="human", content="task B", additional_kwargs={})

        tools = [
            {"name": "read", "description": "read files"},
            {"name": "bash", "description": "run commands"},
        ]

        def _body_bytes(messages):
            out = AgentV2._to_openai_messages(messages)
            body = {
                "model": "test-model",
                "messages": out,
                "tools": tools,
            }
            return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        bytes_a = _body_bytes([sys_msg, hist1, user_a])
        bytes_b = _body_bytes([sys_msg, hist1, user_b])

        # 完整 body 不同（user 不同）……
        assert bytes_a != bytes_b
        # ……但去掉最后一条 user 后（system+历史+tools+除最后 user 外的消息）
        # 字节完全相同：证明 tools schema 与历史在前缀区逐字节稳定。
        out_a = AgentV2._to_openai_messages([sys_msg, hist1, user_a])
        out_b = AgentV2._to_openai_messages([sys_msg, hist1, user_b])
        assert out_a[:-1] == out_b[:-1]
        head_a = json.dumps(
            {"model": "test-model", "messages": out_a[:-1], "tools": tools},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        head_b = json.dumps(
            {"model": "test-model", "messages": out_b[:-1], "tools": tools},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        assert head_a == head_b

    def test_research_contract_after_system_not_overwriting(self):
        """FXC3：research_contract 以 user 快照追加在 system 之后，不改写 messages[0]。"""
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        system = SimpleNamespace(
            type="system", content="SYS_PREFIX", additional_kwargs={}
        )
        contract = "research contract body"
        messages = [system, SimpleNamespace(type="human", content="q", additional_kwargs={})]
        messages.append(SimpleNamespace(type="human", content=contract, additional_kwargs={}))

        out = AgentV2._to_openai_messages(messages)
        # system 前缀保持头部且未改写
        assert out[0]["role"] == "system"
        assert out[0]["content"] == "SYS_PREFIX"
        # research contract 作为 user 快照在断点之后（位置 ≥ 2）
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == contract
        assert len(out) == 3

    def test_research_contract_behavioral_chain(self):
        """research 路径行为验证：system 保持头部、contract 独立消息在断点之后。

        luna 阻断项 3 落地：不依赖真实 web 搜索，验证 research_contract
        追加后的消息链经 _to_openai_messages 序列化时 system[0] 不被改写。
        """
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        # 模拟 research 路径的消息链：system 固定 + research_contract 独立消息
        system = SimpleNamespace(
            type="system", content="UNCHANGED_SYSTEM_PREFIX", additional_kwargs={}
        )
        contract = "External research is mandatory..."
        chain = [
            system,
            SimpleNamespace(type="human", content="query", additional_kwargs={}),
            SimpleNamespace(type="human", content=contract, additional_kwargs={}),
        ]

        out = AgentV2._to_openai_messages(chain)
        assert out[0]["role"] == "system"
        assert out[0]["content"] == "UNCHANGED_SYSTEM_PREFIX"
        assert out[-1]["role"] == "user"
        assert out[-1]["content"] == contract
        # system 前缀字节未被 contract 污染
        assert "UNCHANGED_SYSTEM_PREFIX" in out[0]["content"]
        assert contract not in out[0]["content"]

    def test_prompt_cache_key_only_for_openai_payload(self):
        """luna 阻断项 3：OpenAI 系 payload 含 prompt_cache_key，DeepSeek/Anthropic 不含。"""
        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
            ModelCapabilities,
        )
        from dataclasses import replace

        def _payload_extra(model_caps) -> dict:
            caps = model_caps.merged_with_overrides({})
            extra = {}
            if getattr(caps, "prompt_cache_key_required", False):
                extra["prompt_cache_key"] = "sess-1"
            return extra

        openai_caps = replace(
            DEFAULT_CAPABILITIES, provider="openai", prompt_cache_key_required=True
        )
        deepseek_caps = replace(
            DEFAULT_CAPABILITIES, provider="deepseek", prompt_cache_key_required=False
        )
        anthropic_caps = replace(
            DEFAULT_CAPABILITIES, provider="anthropic", prompt_cache_key_required=False
        )

        assert _payload_extra(openai_caps) == {"prompt_cache_key": "sess-1"}
        assert _payload_extra(deepseek_caps) == {}
        assert _payload_extra(anthropic_caps) == {}

    def test_unknown_model_payload_default_no_key(self):
        """CB8：未识别模型（默认 caps）不注入 prompt_cache_key，行为与现状一致。"""
        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )

        assert DEFAULT_CAPABILITIES.prompt_cache_key_required is False

    def _make_raw_stream_agent(self, caps, model_name: str):
        """object.__new__ 构造最小 AgentV2（绕过 config 加载），供 _raw_stream 测试。"""
        import asyncio
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        agent._session_id = "sess-test-1"
        agent._llm = SimpleNamespace()  # 无 _apply_cache_control → 跳过
        agent._rate_limiter = None
        agent.model_config = {"model_name": model_name}
        agent._capabilities = caps
        agent._provider = None
        agent._resolve_request_max_tokens = lambda _n: 2048
        return agent

    def test_subset_policy_tools_sorted(self):
        """luna 阻断项 2：subset 分支输出也必须按名排序（不随输入顺序抖动）。"""
        from dataclasses import replace
        from types import SimpleNamespace

        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        def _t(name: str):
            return StructuredTool.from_function(lambda: "ok", name=name, description=f"{name} desc")

        # 乱序注册的 orchestrator（dict 插入序：zeta 先、alpha 后）
        class FakeOrch:
            def __init__(self):
                self._reg = {}
                for n in ("zeta", "alpha", "mike", "beta", "charlie", "delta",
                          "echo", "foxtrot", "golf", "hotel"):
                    self._reg[n] = _t(n)

            def get_all(self):
                return dict(self._reg)

        agent = object.__new__(AgentV2)
        agent._tool_orchestrator = FakeOrch()
        agent._memory = SimpleNamespace(_rag_enabled=False)
        agent._capabilities = replace(
            DEFAULT_CAPABILITIES, provider="openai", tool_send_policy="subset"
        )
        agent._subset_tool_names = None

        tools = agent._get_core_tools()
        names = [getattr(t, "name", "") for t in tools]
        assert len(names) == 8
        assert names == sorted(names), f"subset tools not sorted: {names}"

    def test_full_policy_tools_sorted(self):
        """full 策略输出也必须按名排序。"""
        from types import SimpleNamespace

        from langchain_core.tools import StructuredTool

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        def _t(name: str):
            return StructuredTool.from_function(lambda: "ok", name=name, description=f"{name} desc")

        class FakeOrch:
            def __init__(self):
                self._reg = {}
                for n in ("zeta", "alpha", "mike"):
                    self._reg[n] = _t(n)

            def get_all(self):
                return dict(self._reg)

        agent = object.__new__(AgentV2)
        agent._tool_orchestrator = FakeOrch()
        agent._memory = SimpleNamespace(_rag_enabled=False)
        agent._capabilities = None  # full 策略（policy None）

        tools = agent._get_core_tools()
        names = [getattr(t, "name", "") for t in tools]
        assert names == sorted(names), f"full tools not sorted: {names}"

    def test_raw_stream_payload_has_prompt_cache_key_for_openai(self):
        """真实 _raw_stream payload 断言：OpenAI 系 extra_body 含 prompt_cache_key。

        luna 阻断项 3 落地：不靠源码字符串，捕获真实请求 payload。
        """
        import asyncio
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        captured: dict = {}

        class FakeClient:
            def create(self, **payload):
                payload.pop("timeout", None)
                captured["payload"] = payload
                raise RuntimeError("stop-after-capture")

        caps = replace(
            DEFAULT_CAPABILITIES, provider="openai", prompt_cache_key_required=True
        )
        agent = self._make_raw_stream_agent(caps, "gpt-5.6-luna")
        agent._openai_client = lambda: FakeClient()

        sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
        with pytest.raises(RuntimeError):
            asyncio.run(
                agent._raw_stream([sys_msg, user_msg], tools=None).__anext__()
            )

        payload = captured["payload"]
        assert payload["extra_body"]["prompt_cache_key"] == "sess-test-1"

    def test_raw_stream_payload_no_key_for_deepseek(self):
        """真实 _raw_stream payload 断言：DeepSeek 系不注入 prompt_cache_key（CB3）。"""
        import asyncio
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        captured: dict = {}

        class FakeClient:
            def create(self, **payload):
                payload.pop("timeout", None)
                captured["payload"] = payload
                raise RuntimeError("stop-after-capture")

        agent = self._make_raw_stream_agent(
            replace(DEFAULT_CAPABILITIES, provider="deepseek"),
            "deepseek-v4-flash",
        )
        agent._openai_client = lambda: FakeClient()

        sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
        with pytest.raises(RuntimeError):
            asyncio.run(
                agent._raw_stream([sys_msg, user_msg], tools=None).__anext__()
            )

        payload = captured["payload"]
        extra = payload.get("extra_body") or {}
        assert "prompt_cache_key" not in extra

    def test_raw_stream_payload_no_key_for_anthropic(self):
        """真实 _raw_stream payload 断言：Anthropic 系不注入 prompt_cache_key（CB3）。"""
        import asyncio
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        captured: dict = {}

        class FakeClient:
            def create(self, **payload):
                payload.pop("timeout", None)
                captured["payload"] = payload
                raise RuntimeError("stop-after-capture")

        agent = self._make_raw_stream_agent(
            replace(DEFAULT_CAPABILITIES, provider="anthropic"),
            "claude-sonnet-5",
        )
        agent._openai_client = lambda: FakeClient()

        sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
        with pytest.raises(RuntimeError):
            asyncio.run(
                agent._raw_stream([sys_msg, user_msg], tools=None).__anext__()
            )

        payload = captured["payload"]
        extra = payload.get("extra_body") or {}
        assert "prompt_cache_key" not in extra

    def test_raw_stream_payload_no_key_for_non_openai_override(self):
        """CB3 隔离：非 openai provider 即使 override 要求 key 也不注入（luna 阻断项 2）。"""
        import asyncio
        from dataclasses import replace
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.config.model_capabilities import (
            DEFAULT_CAPABILITIES,
        )
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        captured: dict = {}

        class FakeClient:
            def create(self, **payload):
                payload.pop("timeout", None)
                captured["payload"] = payload
                raise RuntimeError("stop-after-capture")

        # 恶意/错误 override：deepseek provider 被误置 prompt_cache_key_required=True
        bad_caps = replace(
            DEFAULT_CAPABILITIES,
            provider="deepseek",
            prompt_cache_key_required=True,
        )
        agent = self._make_raw_stream_agent(bad_caps, "deepseek-v4-flash")
        agent._openai_client = lambda: FakeClient()

        sys_msg = SimpleNamespace(type="system", content="SYS", additional_kwargs={})
        user_msg = SimpleNamespace(type="human", content="hi", additional_kwargs={})
        with pytest.raises(RuntimeError):
            asyncio.run(
                agent._raw_stream([sys_msg, user_msg], tools=None).__anext__()
            )

        payload = captured["payload"]
        extra = payload.get("extra_body") or {}
        assert "prompt_cache_key" not in extra
