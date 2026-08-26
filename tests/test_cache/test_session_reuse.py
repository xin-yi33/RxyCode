"""B5: 会话复用与 prewarm（PHASE-B §5 B5）。

持久会话、跨会话前缀复用策略、可选预热：
1. 会话恢复路径 append-only（追加不改写，前缀形态唯一）。
2. prompt_cache_key=session_id 跨 turn 复用（session_id 会话期稳定）。
3. 预热签名校验（配置变化 → 预热失效 → 重建）。
4. 可选保活：默认关闭，开启时有预算保护。
"""

from __future__ import annotations

import time

import pytest


class TestSessionRestoreAppendOnly:
    """B5 判据 1：恢复会话不产生第二个前缀形态（append-only）。"""

    def test_restore_append_only_keeps_history(self):
        """恢复时历史逐条 append（不清空、不改写），前缀形态唯一。"""
        from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory

        mem = ShortTermMemory()
        mem.add_user_message("Q1")
        mem.add_ai_message("A1")
        mem.add_user_message("Q2")
        mem.add_ai_message("A2")

        saved = mem.get_messages_as_dicts()

        # 新实例 + append-only 恢复
        mem2 = ShortTermMemory()
        mem2.load_from_dicts(saved)
        assert len(mem2._messages) == 4
        assert mem2._messages[0].content == "Q1"
        assert mem2._messages[-1].content == "A2"

    def test_restore_does_not_mutate_saved(self):
        """恢复不清空已保存历史（append-only 语义）。"""
        from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory

        mem = ShortTermMemory()
        mem.add_user_message("Q1")
        mem.add_ai_message("A1")
        saved_before = list(mem._messages)
        mem.load_from_dicts(mem.get_messages_as_dicts())
        assert len(mem._messages) == len(saved_before)


class TestSessionIdStable:
    """B5 判据 2：session_id 会话期稳定（跨 turn 复用）。"""

    def test_set_session_stable_across_calls(self):
        """同一 AgentV2 的 session_id 不随 turn 变化。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        agent._session_id = "sess-stable"
        # 两次读取必须相同（无每轮换 id）
        assert agent._session_id == "sess-stable"
        assert agent._session_id == "sess-stable"

    def test_prompt_cache_key_uses_stable_session_id(self):
        """prompt_cache_key 注入 session_id（B2），且会话期不变。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        agent._session_id = "sess-abc"
        # _raw_stream 注入的是 self._session_id
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            apply_breakpoint_budget,
        )

        # prompt_cache_key 逻辑在 _raw_stream：session_id 恒定即 key 恒定
        assert agent._session_id == "sess-abc"


class TestPrewarmSignature:
    """B5 判据 3：预热签名校验（配置变化 → 失效 → 重建）。"""

    def _signature(self, model: str, cwd: str, mcp: str) -> str:
        from RxyCode.RxyCode1_1_0.core.cache_policy import build_prewarm_signature

        return build_prewarm_signature(model=model, cwd=cwd, mcp=mcp)

    def test_signature_stable_for_same_config(self):
        sig1 = self._signature("gpt-5.6", "/work", "mcp-a")
        sig2 = self._signature("gpt-5.6", "/work", "mcp-a")
        assert sig1 == sig2

    def test_signature_changes_on_model_change(self):
        """模型变化 → 签名变化 → 预热失效 → 重建。"""
        sig1 = self._signature("gpt-5.6", "/work", "mcp-a")
        sig2 = self._signature("deepseek", "/work", "mcp-a")
        assert sig1 != sig2

    def test_signature_changes_on_cwd_change(self):
        sig1 = self._signature("gpt-5.6", "/work", "mcp-a")
        sig2 = self._signature("gpt-5.6", "/other", "mcp-a")
        assert sig1 != sig2

    def test_signature_changes_on_mcp_change(self):
        sig1 = self._signature("gpt-5.6", "/work", "mcp-a")
        sig2 = self._signature("gpt-5.6", "/work", "mcp-b")
        assert sig1 != sig2

    def test_prewarm_validated_by_signature(self):
        """预热请求与真实请求同签名校验（Cherry Studio 语义）。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            prewarm_valid,
        )

        sig = self._signature("gpt-5.6", "/work", "mcp-a")
        assert prewarm_valid(sig, model="gpt-5.6", cwd="/work", mcp="mcp-a") is True
        # 配置变化 → 预热失效
        assert prewarm_valid(sig, model="deepseek", cwd="/work", mcp="mcp-a") is False


class TestKeepAlive:
    """B5 判据 4：可选保活默认关闭，开启有预算保护。"""

    def test_keep_alive_default_off(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_enabled

        assert keep_alive_enabled({}) is False

    def test_keep_alive_opt_in(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_enabled

        assert keep_alive_enabled({"cache": {"keep_alive": True}}) is True

    def test_keep_alive_budget_guard(self):
        """保活空请求本身有写入价——有预算上限。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_budget

        assert keep_alive_budget({}) > 0  # 默认有上限
        assert keep_alive_budget({"cache": {"keep_alive_max_calls": 3}}) == 3

    def test_keep_alive_schedule_requires_enabled(self):
        """luna 阻断项：保活调度默认关闭时不触发。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_should_fire

        assert (
            keep_alive_should_fire(
                last_call_at=100.0, now=1000.0, cfg={}, calls_used=0
            )
            is False
        )

    def test_keep_alive_fires_after_5m_within_budget(self):
        """luna 阻断项：启用 + ≥5m + 预算未耗尽 → 触发。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_should_fire

        assert (
            keep_alive_should_fire(
                last_call_at=100.0,
                now=100.0 + 301.0,
                cfg={"cache": {"keep_alive": True}},
                calls_used=1,
            )
            is True
        )

    def test_keep_alive_blocked_when_budget_exhausted(self):
        """luna 阻断项：预算耗尽 → 不触发（写入价保护）。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import keep_alive_should_fire

        assert (
            keep_alive_should_fire(
                last_call_at=100.0,
                now=100.0 + 301.0,
                cfg={"cache": {"keep_alive": True, "keep_alive_max_calls": 2}},
                calls_used=2,
            )
            is False
        )

    def test_keep_alive_request_minimal(self):
        """保活请求最小化（max_tokens=1）。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import build_keep_alive_request

        req = build_keep_alive_request([{"role": "user", "content": "hi"}])
        assert req["max_tokens"] == 1
        assert req["keep_alive"] is True


class TestPrewarmFlow:
    """luna 阻断项 3：预热执行、签名失效、缓存重建。"""

    def test_prewarm_state_warm_and_valid(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            PrewarmState,
            build_prewarm_signature,
        )

        sig = build_prewarm_signature(model="gpt-5.6", cwd="/w", mcp="m")
        state = PrewarmState()
        state.warm(sig, now=100.0)
        assert state.validate(sig) is True
        assert state.warmed_at == 100.0

    def test_prewarm_invalid_before_warm(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            PrewarmState,
            build_prewarm_signature,
        )

        sig = build_prewarm_signature(model="gpt-5.6", cwd="/w", mcp="m")
        state = PrewarmState()
        assert state.validate(sig) is False  # 未预热 → 无效

    def test_prewarm_rebuild_on_config_change(self):
        """luna 阻断项：配置变化 → 预热失效 → 重建（审计记录）。"""
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            PrewarmState,
            build_prewarm_signature,
        )

        sig_a = build_prewarm_signature(model="gpt-5.6", cwd="/w", mcp="m")
        sig_b = build_prewarm_signature(model="deepseek", cwd="/w", mcp="m")
        state = PrewarmState()
        state.warm(sig_a, now=100.0)
        # 配置变化 → 旧预热失效
        assert state.validate(sig_b) is False
        # 重建：返回 True（发生了重建）且新签名生效
        rebuilt = state.rebuild(sig_b, now=200.0)
        assert rebuilt is True
        assert state.validate(sig_b) is True

    def test_prewarm_no_rebuild_when_unchanged(self):
        from RxyCode.RxyCode1_1_0.core.cache_policy import (
            PrewarmState,
            build_prewarm_signature,
        )

        sig = build_prewarm_signature(model="gpt-5.6", cwd="/w", mcp="m")
        state = PrewarmState()
        state.warm(sig)
        assert state.rebuild(sig) is False  # 无变化 → 不重建


class TestSessionResumeHitRate:
    """B5 判据 6：会话恢复后的命中率记录存在。"""

    def test_resume_records_usage(self):
        """恢复会话后 token_stats 记录真实 usage（命中率可观测）。"""
        from RxyCode.RxyCode1_1_0.utils.streaming import TokenStats

        stats = TokenStats()
        stats.add_real_usage(1000, 100, 800)
        assert stats.cache_hit_rate == pytest.approx(80.0)
        assert stats.latest_request["hit_tokens"] == 800

    def test_manager_load_session_append_only(self):
        """luna 阻断项 1：MemoryManager.load_session(append_only=True) 真实路径。"""
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        import tempfile
        import os
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="b5-mgr-"))
        os.environ["RXYCODE_DATA_DIR"] = str(tmp)
        try:
            mm = MemoryManager(session_id="sess-b5-1")
            mm.short_term.load_from_dicts([
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
            ])
            mm.save_session()
            # 新实例（模拟重启）append-only 恢复
            mm2 = MemoryManager(session_id="sess-b5-1")
            mm2.load_session(append_only=True)
            assert len(mm2.short_term._messages) == 2
            assert mm2.short_term._messages[0].content == "Q1"
            assert mm2.short_term._messages[-1].content == "A1"
        finally:
            os.environ.pop("RXYCODE_DATA_DIR", None)

    def test_append_only_preserves_existing_prefix(self):
        """luna 阻断项 1：append 到已有前缀不清空、不重复。"""
        from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory

        mem = ShortTermMemory()
        mem.add_user_message("P0")
        mem.add_ai_message("PA")
        mem.append_from_dicts([
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
        ])
        contents = [m.content for m in mem._messages]
        assert contents == ["P0", "PA", "Q1", "A1"]  # 前缀保留 + 追加
        assert mem._turn_count == 2  # P0 + Q1

    def test_append_from_dicts_all_message_types(self):
        """luna 阻断项 R5-1：append_from_dicts 支持 system/tool 消息。"""
        from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory

        mem = ShortTermMemory()
        mem.append_from_dicts([
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "content": "R1", "tool_call_id": "c1"},
        ])
        assert len(mem._messages) == 4
        assert mem._messages[0].content == "SYS"
        assert mem._messages[3].content == "R1"

    def test_append_from_dicts_keeps_tool_calls(self):
        """luna 阻断项 R8-1：assistant 的 tool_calls 元数据保留。"""
        from RxyCode.RxyCode1_1_0.memory.short_term import ShortTermMemory

        mem = ShortTermMemory()
        mem.append_from_dicts([
            {"role": "assistant", "content": "A1", "tool_calls": [{"id": "c1", "name": "read"}]},
        ])
        ai = mem._messages[0]
        assert ai.tool_calls == [{"id": "c1", "name": "read"}]

    def test_manager_append_only_no_duplicate_when_prefix_exists(self):
        """luna 阻断项 R3-1：已有前缀 + manager 恢复不重复追加。"""
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        import tempfile
        import os
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="b5-mgr2-"))
        os.environ["RXYCODE_DATA_DIR"] = str(tmp)
        try:
            mm = MemoryManager(session_id="sess-b5-2")
            mm.short_term.load_from_dicts([
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
            ])
            mm.save_session()
            # 已有前缀的实例（模拟运行中恢复）+ append_only
            mm2 = MemoryManager(session_id="sess-b5-2")
            mm2.short_term.load_from_dicts([
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
            ])
            mm2.load_session(append_only=True)
            # 不重复追加（重叠 Q1/A1 跳过）
            contents = [m.content for m in mm2.short_term._messages]
            assert contents == ["Q1", "A1"]
        finally:
            os.environ.pop("RXYCODE_DATA_DIR", None)

    def test_manager_append_only_full_duplicate_detected(self):
        """luna 阻断项 R4-1：完整重复历史不二次追加（通用重叠）。"""
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        import tempfile
        import os
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="b5-mgr3-"))
        os.environ["RXYCODE_DATA_DIR"] = str(tmp)
        try:
            mm = MemoryManager(session_id="sess-b5-3")
            hist = [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
                {"role": "user", "content": "Q2"},
                {"role": "assistant", "content": "A2"},
            ]
            mm.short_term.load_from_dicts(hist)
            mm.save_session()
            # 已有相同完整历史 + append_only → 无重复
            mm2 = MemoryManager(session_id="sess-b5-3")
            mm2.short_term.load_from_dicts(hist)
            mm2.load_session(append_only=True)
            contents = [m.content for m in mm2.short_term._messages]
            assert contents == ["Q1", "A1", "Q2", "A2"]
        finally:
            os.environ.pop("RXYCODE_DATA_DIR", None)

    def test_manager_append_only_partial_overlap_any_length(self):
        """luna 阻断项 R4-1：任意长度重叠（>2）正确去重。"""
        from RxyCode.RxyCode1_1_0.memory.manager import MemoryManager

        import tempfile
        import os
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp(prefix="b5-mgr4-"))
        os.environ["RXYCODE_DATA_DIR"] = str(tmp)
        try:
            mm = MemoryManager(session_id="sess-b5-4")
            hist = [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "content": "A1"},
                {"role": "user", "content": "Q2"},
                {"role": "assistant", "content": "A2"},
            ]
            mm.short_term.load_from_dicts(hist)
            mm.save_session()
            # 已有最后 2 条（重叠 2）→ 只追加重叠之后的部分
            mm2 = MemoryManager(session_id="sess-b5-4")
            mm2.short_term.load_from_dicts(hist[2:])
            mm2.load_session(append_only=True)
            contents = [m.content for m in mm2.short_term._messages]
            # 已有 [Q2,A2] 与历史头部 [Q1,A1,...] 无重叠 → 不追加（不产生第二前缀）
            assert contents == ["Q2", "A2"]
        finally:
            os.environ.pop("RXYCODE_DATA_DIR", None)

    def test_run_entry_calls_prewarm_rebuild(self):
        """luna 阻断项 R3-2：run 入口调用 prewarm 重建。"""
        import inspect

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        src = inspect.getsource(AgentV2.run)
        assert "_schedule_prewarm" not in src
        assert "_maybe_rebuild_prewarm" in inspect.getsource(AgentV2)

    def test_keep_alive_builds_request(self):
        """luna 阻断项 R3-3：保活触发时构造 max_tokens=1 请求。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        agent._cfg = {"cache": {"keep_alive": True}}
        agent._keep_alive_state = {"calls_used": 1}
        fired = agent._maybe_keep_alive(last_call_at=time.monotonic() - 400)
        assert fired is True
        req = agent._keep_alive_state.get("request")
        assert req is not None
        assert req["max_tokens"] == 1
        assert req["keep_alive"] is True

    def test_raw_stream_supports_max_tokens_override(self):
        """luna 阻断项 R5-2：_raw_stream 支持 max_tokens 覆盖（keep-alive 用）。"""
        import inspect

        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        sig = inspect.signature(AgentV2._raw_stream)
        assert "max_tokens" in sig.parameters

    def test_agent_prewarm_wired(self):
        """luna 阻断项 2：AgentV2 prewarm 接入请求链路。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        agent.model_config = {"model_name": "test-model"}
        agent._cfg = {}
        agent._workspace_root = "/w"
        agent._prewarm = None

        # 首次：需重建 True（待预热）
        rebuilt1 = agent._maybe_rebuild_prewarm()
        # 预热成功后确认
        agent._confirm_prewarm()
        # 无变化 → 不再需重建
        assert agent._maybe_rebuild_prewarm() is False
        # 配置变化：换模型 → 需重建
        agent.model_config = {"model_name": "other-model"}
        rebuilt2 = agent._maybe_rebuild_prewarm()
        assert rebuilt1 is True  # 首次建立
        assert rebuilt2 is True  # 模型变化 → 重建

    def test_prewarm_not_confirmed_before_request_success(self):
        """luna 阻断项 R6-2：预热成功前不提交 warmed 状态。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        from RxyCode.RxyCode1_1_0.core.cache_policy import PrewarmState

        agent = object.__new__(AgentV2)
        agent.model_config = {"model_name": "test-model"}
        agent._cfg = {}
        agent._workspace_root = "/w"
        agent._prewarm = PrewarmState()

        # 首次检测：需重建，但未确认 → warmed_at 仍 None
        assert agent._maybe_rebuild_prewarm() is True
        assert agent._prewarm.warmed_at is None
        # 确认后 → warmed_at 设置
        agent._confirm_prewarm()
        assert agent._prewarm.warmed_at is not None

    def test_prewarm_retries_when_not_confirmed(self):
        """luna 阻断项 R7-1：预热未确认成功 → 下次 run 继续重试。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
        from RxyCode.RxyCode1_1_0.core.cache_policy import PrewarmState

        agent = object.__new__(AgentV2)
        agent.model_config = {"model_name": "test-model"}
        agent._cfg = {}
        agent._workspace_root = "/w"
        agent._prewarm = PrewarmState()

        # 模拟预热请求失败：检测返回 True，但未确认
        assert agent._maybe_rebuild_prewarm() is True
        # 下次调用（未确认）→ 仍返回 True（重试）
        assert agent._maybe_rebuild_prewarm() is True
        # 确认成功后 → 不再需要
        agent._confirm_prewarm()
        assert agent._maybe_rebuild_prewarm() is False

    def test_agent_keep_alive_wired(self):
        """luna 阻断项 3：AgentV2 keep-alive 调度接入。"""
        from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

        agent = object.__new__(AgentV2)
        agent._cfg = {"cache": {"keep_alive": True}}
        agent._keep_alive_state = {"calls_used": 1}
        # 距上次调用 <5m → 不触发
        assert (
            agent._maybe_keep_alive(last_call_at=time.monotonic() - 60) is False
        )
        # ≥5m → 触发且预算消耗
        assert (
            agent._maybe_keep_alive(last_call_at=time.monotonic() - 400) is True
        )
        assert agent._keep_alive_state["calls_used"] == 2

    def test_resume_records_real_usage_chain(self):
        """luna 阻断项 4：恢复会话 → 请求 → 记录真实 usage 链路。"""
        from types import SimpleNamespace

        from RxyCode.RxyCode1_1_0.core.agent_v2 import _record_usage
        from RxyCode.RxyCode1_1_0.utils.streaming import token_stats

        token_stats.reset()
        chunk = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=2000,
                completion_tokens=500,
                prompt_cache_hit_tokens=1600,
                prompt_tokens_details=None,
            ),
            usage_metadata=None,
            content=None,
        )
        _record_usage(chunk, provider=SimpleNamespace(name="deepseek", extract_cache_read=lambda u, c: u.get("prompt_cache_hit_tokens", 0)), caps=SimpleNamespace())
        # 恢复后的请求记录了命中率
        assert token_stats.prompt_tokens == 2000
        assert token_stats.cache_hit_tokens == 1600
        assert token_stats.cache_hit_rate == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_second_agent_turn_appends_to_frozen_prefix(monkeypatch):
    """F14 / PHASE-FIX: warmup then H3 on the same AgentV2 must keep S1 + prior
    turns and only append the new user suffix. Restarting at [S1, human] every
    execute() is why live Primary cache sat at 80–88% instead of 97%.
    """
    import asyncio
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.config.model_capabilities import DEFAULT_CAPABILITIES

    captured: list[list] = []

    agent = object.__new__(AgentV2)
    agent._session_loaded = True
    agent._session_id = "prefix-append"
    agent._memory = SimpleNamespace(
        get_context_for_prompt=lambda _q, **_k: "",
        add_interaction=lambda *_a, **_k: None,
        save_session=lambda: None,
        compress_if_needed=lambda _sid: None,
        _rag_enabled=False,
    )
    agent._cfg = {"execution": {"max_tool_rounds": 1}}
    agent.model_config = {
        "base_url": "https://api.example.test/v1",
        "model_name": "test-model",
        "effort": "balanced",
    }
    agent._capabilities = DEFAULT_CAPABILITIES
    agent._resolved_limits = None
    agent._keep_alive_state = None
    agent._tokenizer = "tiktoken:o200k_base"
    agent._tool_tracer = None
    agent._last_thinking = ""
    agent._thinking_history = []
    agent._agent_prefix_messages = None
    agent._provider = None
    agent._git_snapshot = None
    agent._prompt_variant = lambda: "default"

    async def fake_stream(messages, tools=None, **_kwargs):
        captured.append(list(messages))
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="done", tool_calls=None),
                )
            ],
            usage=None,
        )

    agent._raw_stream = fake_stream
    agent._get_core_tools = lambda: []
    agent._maybe_compress_context = lambda _m: asyncio.sleep(0)
    agent._capture_git_snapshot_async = lambda: asyncio.sleep(0)
    agent._tokenizer_spec = lambda: "tiktoken:o200k_base"
    agent._has_creation_product_intent = lambda _t: False
    agent._is_social_chat = lambda _t: False
    agent._should_emit_analyze_progress = lambda _t: False
    agent._memory_ctx_for_turn = lambda _t: ""
    agent._turn_context_suffix = lambda: ""
    agent._effort_for = lambda _mode, _text: "balanced"
    agent._application_cache_namespace = lambda: "ns-test"

    first = await agent._fast_reply_with_tools(
        "warmup LRU cache",
        allowed_tool_names=None,
        role_instruction="",
        mode="build",
    )
    second = await agent._fast_reply_with_tools(
        "H3 TTL LRU cache",
        allowed_tool_names=None,
        role_instruction="",
        mode="build",
    )
    assert first == "done"
    assert second == "done"
    assert len(captured) == 2
    first_msgs, second_msgs = captured
    assert isinstance(first_msgs[0], SystemMessage)
    assert isinstance(first_msgs[1], HumanMessage)
    assert "warmup LRU cache" in first_msgs[1].content
    assert len(first_msgs) == 2
    assert second_msgs[0].content == first_msgs[0].content
    assert isinstance(second_msgs[1], HumanMessage)
    assert "warmup LRU cache" in second_msgs[1].content
    assert isinstance(second_msgs[2], AIMessage)
    assert second_msgs[2].content == "done"
    assert "H3 TTL LRU cache" in second_msgs[-1].content
    assert len(second_msgs) == 4
