"""F5-7：连续摘要失败和 thrash 要停掉自动压缩。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
from RxyCode.RxyCode1_1_0.core.prefix_profile import PrefixProfile

_FIELDS = {
    "objective": "ANCHOR-A1",
    "constraints": "以后都用 pytest 跑测试",
    "progress": "folded",
    "files_touched": [],
    "next_step": "continue",
    "blockers": "none",
}


def _chain():
    return [
        SystemMessage(content="SYS"),
        HumanMessage(content="任务"),
        AIMessage(content="x" * 8000),
        HumanMessage(content="中段"),
        AIMessage(content="m"),
        HumanMessage(content="尾一"),
        AIMessage(content="t1"),
        HumanMessage(content="尾二"),
        AIMessage(content="t2"),
    ]


def _tiny():
    return [
        SystemMessage(content="SYS"),
        HumanMessage(content="hi"),
        AIMessage(content="ok"),
    ]


class _FailingLLM:
    def __init__(self):
        self.calls = 0
        self.seen: list[str] = []

    async def ainvoke(self, messages, **_kwargs):
        self.calls += 1
        self.seen.append("\n".join(str(getattr(message, "content", "") or "") for message in messages))
        raise RuntimeError("summary model down")


class _SwitchLLM:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0
        self.seen: list[str] = []

    async def ainvoke(self, messages, **_kwargs):
        self.calls += 1
        self.seen.append("\n".join(str(getattr(message, "content", "") or "") for message in messages))
        if self.calls <= self.fail_times:
            raise RuntimeError("summary model down")
        return SimpleNamespace(content=json.dumps(_FIELDS))


class _SuccessLLM:
    def __init__(self):
        self.calls = 0
        self.seen: list[str] = []

    async def ainvoke(self, messages, **_kwargs):
        self.calls += 1
        self.seen.append("\n".join(str(getattr(message, "content", "") or "") for message in messages))
        return SimpleNamespace(content=json.dumps(_FIELDS))


def _agent(llm):
    agent = AgentV2.__new__(AgentV2)
    agent._llm = llm
    agent._capabilities = SimpleNamespace(context_window=300, tokenizer="tiktoken:o200k_base")
    agent._memory = SimpleNamespace(flush_before_compaction=lambda _messages: None)
    agent._session_id = ""
    agent.model_config = {
        "base_url": "https://example.test/v1",
        "model_name": "m",
        "api_key": "k",
    }
    return agent


def _reserve_zero(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod

    monkeypatch.setattr(compaction_mod, "DEFAULT_RESERVED_TOKENS", 0)


@pytest.mark.asyncio
async def test_u_f5_7_01_three_summary_failures_stop_auto_compact(monkeypatch):
    _reserve_zero(monkeypatch)
    llm = _FailingLLM()
    agent = _agent(llm)
    reported: list[str] = []
    agent.note_status_event = reported.append
    await agent._maybe_compress_context(_tiny(), force=False)
    assert llm.calls == 0
    assert int(getattr(agent, "_compact_fail_count", 0) or 0) == 0
    for _ in range(3):
        await agent._maybe_compress_context(_chain(), force=True)
    assert agent._auto_compact_stopped is True
    assert llm.calls == 3
    await agent._maybe_compress_context(_chain(), force=False)
    assert llm.calls == 3
    assert agent._compact_hold_turn is True
    text = " ".join(reported)
    assert "分块读大文件" in text
    assert "/compact" in text
    assert "子代理" in text
    assert "/clear" in text
    assert text.count("分块读大文件") == 1


@pytest.mark.asyncio
async def test_u_f5_7_02_success_resets_fail_count_and_force_still_runs(monkeypatch):
    _reserve_zero(monkeypatch)
    llm = _SwitchLLM(fail_times=2)
    agent = _agent(llm)
    await agent._maybe_compress_context(_chain(), force=True)
    await agent._maybe_compress_context(_chain(), force=True)
    assert agent._compact_fail_count == 2
    assert agent._auto_compact_stopped is False
    await agent._maybe_compress_context(_chain(), force=True)
    assert agent._compact_fail_count == 0
    assert llm.calls == 3
    agent._auto_compact_stopped = True
    await agent._maybe_compress_context(_chain(), force=True)
    assert llm.calls == 4


@pytest.mark.asyncio
async def test_u_f5_7_03_thrash_stops_and_non_fold_resets(monkeypatch):
    _reserve_zero(monkeypatch)
    llm = _SuccessLLM()
    agent = _agent(llm)
    agent._compact_fail_count = 2
    await agent._maybe_compress_context(_chain(), force=False)
    assert agent._compact_thrash_count == 0
    assert agent._compact_fail_count == 0
    await agent._maybe_compress_context(_chain(), force=False)
    await agent._maybe_compress_context(_chain(), force=False)
    assert agent._compact_thrash_count == 2
    assert agent._auto_compact_stopped is False
    await agent._maybe_compress_context(_tiny(), force=False)
    assert agent._compact_thrash_count == 0
    assert agent._auto_compact_stopped is False
    await agent._maybe_compress_context(_chain(), force=False)
    await agent._maybe_compress_context(_chain(), force=False)
    await agent._maybe_compress_context(_chain(), force=False)
    assert agent._compact_thrash_count == 2
    calls = llm.calls
    await agent._maybe_compress_context(_chain(), force=False)
    assert agent._auto_compact_stopped is True
    assert agent._compact_thrash_count == 3
    assert llm.calls == calls
    fresh = _agent(_FailingLLM())
    for _ in range(3):
        await fresh._maybe_compress_context(_chain(), force=True)
    assert fresh._auto_compact_stopped is True
    assert int(getattr(fresh, "_compact_thrash_count", 0) or 0) == 0


@pytest.mark.asyncio
async def test_u_f5_7_04_counters_stay_out_of_cache_keys(monkeypatch):
    _reserve_zero(monkeypatch)
    llm = _FailingLLM()
    agent = _agent(llm)
    before_ns = agent._application_cache_namespace()
    profile = PrefixProfile(
        kind="agent",
        session_id="sess",
        provider="glm",
        model="m",
        thinking_enabled=True,
        thinking_effort="high",
        tools_digest="abc",
        s1_digest="def",
        system_template_version="1",
        prompt_variant="default",
    )
    before_id = profile.identity()
    await agent._maybe_compress_context(_chain(), force=True)
    await agent._maybe_compress_context(_chain(), force=True)
    await agent._maybe_compress_context(_chain(), force=True)
    assert agent._auto_compact_stopped is True
    assert agent._application_cache_namespace() == before_ns
    assert profile.identity() == before_id
    blob = "\n".join(llm.seen)
    assert "_compact_fail_count" not in blob
    assert "_compact_thrash_count" not in blob
    assert "_auto_compact_stopped" not in blob


@pytest.mark.asyncio
async def test_non_fold_clears_thrash_even_when_not_armed(monkeypatch):
    _reserve_zero(monkeypatch)
    agent = _agent(_SuccessLLM())
    agent._compact_thrash_count = 2
    agent._compact_refill_armed = False
    await agent._maybe_compress_context(_tiny(), force=False)
    assert agent._compact_thrash_count == 0


@pytest.mark.asyncio
async def test_prompt_assembly_failure_does_not_count(monkeypatch):
    _reserve_zero(monkeypatch)
    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_mod

    def boom(messages, prior_summary=None):
        del messages, prior_summary
        raise RuntimeError("prompt assemble failed")

    monkeypatch.setattr(agent_mod, "build_compaction_summary_prompt", boom)
    llm = _FailingLLM()
    agent = _agent(llm)
    await agent._maybe_compress_context(_chain(), force=True)
    assert llm.calls == 0
    assert int(getattr(agent, "_compact_fail_count", 0) or 0) == 0


@pytest.mark.asyncio
async def test_progress_outlet_error_still_runs_rule_fallback(monkeypatch):
    _reserve_zero(monkeypatch)
    from RxyCode.RxyCode1_1_0.core import agent_v2 as agent_mod

    class _BoomTui:
        def write_progress(self, text):
            del text
            raise RuntimeError("progress down")

    monkeypatch.setattr(agent_mod, "get_tui", lambda: _BoomTui())
    llm = _FailingLLM()
    agent = _agent(llm)
    messages = _chain()
    for _ in range(3):
        await agent._maybe_compress_context(messages, force=True)
    assert agent._auto_compact_stopped is True
    assert any(
        bool((getattr(message, "additional_kwargs", None) or {}).get("is_compaction_summary"))
        for message in messages
    )


@pytest.mark.asyncio
async def test_session_switch_clears_compact_breaker(monkeypatch):
    _reserve_zero(monkeypatch)
    agent = _agent(_FailingLLM())
    agent._session_id = "old-session"
    agent._memory = SimpleNamespace(
        save_session=lambda: None,
        long_term=SimpleNamespace(clear_session=lambda: 0),
        experience=SimpleNamespace(delete_session=lambda _sid: 0),
        short_term=SimpleNamespace(clear=lambda: None),
        invalidate_code_context=lambda: None,
        bind_rag_indexer=lambda _thread: None,
    )
    agent._checkpoint_store = None
    agent._compact_fail_count = 3
    agent._compact_thrash_count = 2
    agent._auto_compact_stopped = True
    agent._compact_stop_reported = True
    agent._compact_refill_armed = True
    agent._compact_hold_turn = True
    agent.reset_session()
    assert agent._auto_compact_stopped is False
    assert agent._compact_fail_count == 0
    assert agent._compact_thrash_count == 0
    assert agent._compact_hold_turn is False
    agent._auto_compact_stopped = True
    agent._compact_fail_count = 3
    agent._compact_hold_turn = True
    agent.set_session("new-session")
    assert agent._session_id == "new-session"
    assert agent._auto_compact_stopped is False
    assert agent._compact_fail_count == 0
    assert agent._compact_hold_turn is False


@pytest.mark.asyncio
async def test_fast_reply_holds_oversized_first_round_and_streams_small(monkeypatch):
    _reserve_zero(monkeypatch)
    agent = AgentV2.__new__(AgentV2)
    agent._session_loaded = True
    agent._session_id = "hold-fast"
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
        "api_key": "k",
    }
    agent._capabilities = SimpleNamespace(context_window=300, tokenizer="tiktoken:o200k_base")
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
    agent._get_core_tools = lambda: []
    agent._capture_git_snapshot_async = lambda: __import__("asyncio").sleep(0)
    agent._tokenizer_spec = lambda: "tiktoken:o200k_base"
    agent._has_creation_product_intent = lambda _t: False
    agent._is_social_chat = lambda _t: False
    agent._should_emit_analyze_progress = lambda _t: False
    agent._memory_ctx_for_turn = lambda _t: ""
    agent._turn_context_suffix = lambda: ""
    agent._effort_for = lambda _mode, _text: "balanced"
    agent._auto_compact_stopped = True
    agent._compact_stop_message = (
        "自动压缩已停。请分块读大文件，或使用 /compact 手动压缩，"
        "也可以交给子代理，或 /clear 清掉上下文。"
    )
    streamed: list[int] = []

    async def fake_stream(messages, tools=None, **_kwargs):
        del messages, tools
        streamed.append(1)
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="最终结果：小请求", tool_calls=None))],
            usage=None,
        )

    agent._raw_stream = fake_stream

    def continue_prefix(_system, user):
        if "BIG" in str(user):
            return [
                SystemMessage(content="S"),
                HumanMessage(content="x" * 8000),
                AIMessage(content="y" * 8000),
                HumanMessage(content=user),
            ]
        return [SystemMessage(content="S"), HumanMessage(content=user)]

    agent._continue_agent_prefix = continue_prefix
    held = await agent._fast_reply_with_tools("BIG 还是太大", mode="build")
    assert streamed == []
    assert "分块读大文件" in held
    allowed = await agent._fast_reply_with_tools("hi", mode="build")
    assert streamed == [1]
    assert allowed == "最终结果：小请求"


@pytest.mark.asyncio
async def test_mo_f5_7_01_real_prefetch_freezes_and_small_turn_is_not_held(monkeypatch):
    _reserve_zero(monkeypatch)
    llm = _FailingLLM()
    agent = _agent(llm)
    for _ in range(3):
        await agent._maybe_compress_context(_chain(), force=False)
    frozen = llm.calls
    assert agent._auto_compact_stopped is True
    await agent._maybe_compress_context(_chain(), force=False)
    assert llm.calls == frozen
    await agent._maybe_compress_context(_tiny(), force=False)
    assert llm.calls == frozen
    assert agent._compact_hold_turn is False
