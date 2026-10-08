"""E-F5-E2E-03. Scripted summary model, real AgentV2 compaction."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

A1 = "ANCHOR-A1"
A2 = "ANCHOR-A2"
CONSTRAINT = "以后都用 pytest 跑测试"
FAILURE = "tool 返回报错 pytest-collect-failed"
QUOTE = "下一步先修收集错误"


def _summary(messages) -> str:
    found = [
        str(getattr(message, "content", "") or "")
        for message in messages
        if getattr(message, "type", "") == "system"
        and bool((getattr(message, "additional_kwargs", None) or {}).get("is_compaction_summary"))
    ]
    assert found
    return found[-1]


def _first_wave():
    return [
        SystemMessage(content="SYS"),
        HumanMessage(content=f"{A1} 搭骨架"),
        AIMessage(content="WORKSTATE-OLD " + ("x" * 2000)),
        HumanMessage(content="中段一"),
        AIMessage(content="m1 " + ("x" * 800)),
        HumanMessage(content="中段二"),
        AIMessage(content="m2"),
        HumanMessage(content="尾部一"),
        AIMessage(content="t1"),
        HumanMessage(content="尾部二"),
        AIMessage(content="t2"),
    ]


def _second_wave():
    return [
        HumanMessage(content=f"{CONSTRAINT} {A2} {QUOTE}"),
        AIMessage(
            content="跑测试",
            tool_calls=[{"id": "c-fail", "name": "bash", "args": {"cmd": "pytest"}}],
        ),
        ToolMessage(content=FAILURE, tool_call_id="c-fail"),
        HumanMessage(content="中间记录"),
        AIMessage(content="n1 " + ("y" * 800)),
        HumanMessage(content="新尾一"),
        AIMessage(content="u1"),
        HumanMessage(content="新尾二"),
        AIMessage(content="u2"),
    ]


class _ScriptedSummary:
    """Copies anchors only when the production prompt actually contains them."""

    def __init__(self):
        self.calls = 0
        self.fail_once = False

    async def ainvoke(self, messages, **_kwargs):
        text = "\n".join(str(getattr(message, "content", "") or "") for message in messages)
        self.calls += 1
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("summarizer forced failure")
        return SimpleNamespace(
            content=json.dumps(
                {
                    "objective": A1 if self.calls == 1 or A1 in text else "lost-prior",
                    "constraints": CONSTRAINT if CONSTRAINT in text else "none",
                    "progress": A2 if A2 in text else "first-fold",
                    "files_touched": [],
                    "next_step": QUOTE if QUOTE in text else "continue",
                    "blockers": FAILURE if FAILURE in text else "none",
                }
            )
        )


def _agent(llm):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = AgentV2.__new__(AgentV2)
    agent._llm = llm
    agent._capabilities = SimpleNamespace(context_window=300, tokenizer="tiktoken:o200k_base")
    agent._memory = SimpleNamespace(flush_before_compaction=lambda _messages: None)
    agent._session_id = ""
    return agent


@pytest.mark.asyncio
async def test_e_f5_e2e_03_second_compaction_merges_prior_summary(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod

    monkeypatch.setattr(compaction_mod, "DEFAULT_RESERVED_TOKENS", 0)
    llm = _ScriptedSummary()
    agent = _agent(llm)
    messages = _first_wave()
    await agent._maybe_compress_context(messages)
    assert A1 in _summary(messages)
    messages.extend(_second_wave())
    await agent._maybe_compress_context(messages)
    text = _summary(messages)
    assert A1 in text
    assert A2 in text
    assert f"Constraints: {CONSTRAINT}" in text
    assert FAILURE in text
    assert QUOTE in text
    assert llm.calls == 2

    llm.fail_once = True
    messages.extend(
        [
            HumanMessage(content="再压一次"),
            AIMessage(content="z" * 2000),
            HumanMessage(content="规则尾一"),
            AIMessage(content="z1"),
            HumanMessage(content="规则尾二 RULE-NEXT"),
            AIMessage(content="z2"),
        ]
    )
    await agent._maybe_compress_context(messages)
    ruled = _summary(messages)
    assert A1 in ruled
    assert "RULE-NEXT" in ruled


def _over_chain():
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


def _small_chain():
    return [
        SystemMessage(content="SYS"),
        HumanMessage(content="hi"),
        AIMessage(content="ok"),
    ]


class _E2EFailLLM:
    def __init__(self):
        self.calls = 0
        self.seen: list[str] = []

    async def ainvoke(self, messages, **_kwargs):
        self.calls += 1
        self.seen.append("\n".join(str(getattr(item, "content", "") or "") for item in messages))
        raise RuntimeError("summary model down")


class _E2EOkLLM:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages, **_kwargs):
        del messages
        self.calls += 1
        return SimpleNamespace(
            content=json.dumps(
                {
                    "objective": A1,
                    "constraints": CONSTRAINT,
                    "progress": "ok",
                    "files_touched": [],
                    "next_step": QUOTE,
                    "blockers": "none",
                }
            )
        )


def _breaker_agent(llm):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

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


@pytest.mark.asyncio
async def test_e_f5_e2e_04_breaker_stops_failures_and_thrash(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod
    from RxyCode.RxyCode1_1_0.core.prefix_profile import PrefixProfile

    monkeypatch.setattr(compaction_mod, "DEFAULT_RESERVED_TOKENS", 0)
    llm = _E2EFailLLM()
    agent = _breaker_agent(llm)
    reported: list[str] = []
    agent.note_status_event = reported.append
    profile = PrefixProfile(
        kind="agent",
        session_id="sess",
        provider="glm",
        model="m",
        thinking_enabled=False,
        thinking_effort="balanced",
        tools_digest="abc",
        s1_digest="def",
        system_template_version="1",
        prompt_variant="default",
    )
    before = profile.identity()
    namespace = agent._application_cache_namespace()
    for _ in range(3):
        await agent._maybe_compress_context(_over_chain(), force=False)
    assert agent._auto_compact_stopped is True
    assert agent._compact_fail_count == 3
    frozen = llm.calls
    await agent._maybe_compress_context(_over_chain(), force=False)
    assert llm.calls == frozen
    text = " ".join(reported)
    assert "分块读大文件" in text and "/compact" in text
    assert "子代理" in text and "/clear" in text
    assert text.count("分块读大文件") == 1
    await agent._maybe_compress_context(_small_chain(), force=False)
    assert agent._compact_hold_turn is False
    assert llm.calls == frozen
    agent._llm = _E2EOkLLM()
    before_force = agent._llm.calls
    await agent._maybe_compress_context(_over_chain(), force=True)
    assert agent._llm.calls == before_force + 1
    assert profile.identity() == before
    assert agent._application_cache_namespace() == namespace
    blob = "\n".join(llm.seen)
    assert "_compact_fail_count" not in blob
    assert "_compact_thrash_count" not in blob
    assert "_auto_compact_stopped" not in blob

    thrash_llm = _E2EOkLLM()
    thrash = _breaker_agent(thrash_llm)
    thrash_notes: list[str] = []
    thrash.note_status_event = thrash_notes.append
    await thrash._maybe_compress_context(_over_chain(), force=False)
    await thrash._maybe_compress_context(_over_chain(), force=False)
    await thrash._maybe_compress_context(_over_chain(), force=False)
    calls = thrash_llm.calls
    await thrash._maybe_compress_context(_over_chain(), force=False)
    assert thrash._auto_compact_stopped is True
    assert thrash._compact_thrash_count == 3
    assert thrash_llm.calls == calls
    assert any("分块读大文件" in item for item in thrash_notes)
    assert int(getattr(thrash, "_compact_fail_count", 0) or 0) == 0
    assert agent._compact_fail_count == 0
