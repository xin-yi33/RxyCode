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
