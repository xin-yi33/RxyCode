"""F5-8：溢出首步收紧、工具豁免、clear_at_least。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.compaction import (
    TOOL_RESULT_TOMBSTONE,
    compact_messages,
    microcompact_messages,
    plan_compaction,
)


def _record_keep(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod

    seen: list[int] = []
    real = compaction_mod._fold_middle_section

    def wrapped(messages, keep_tail, **kwargs):
        seen.append(int(keep_tail))
        return real(messages, keep_tail, **kwargs)

    monkeypatch.setattr(compaction_mod, "_fold_middle_section", wrapped)
    return seen


def test_u_f5_8_01_first_tighten_jumps_when_overflow_is_large(monkeypatch):
    seen = _record_keep(monkeypatch)
    messages = [SystemMessage(content="SYS"), HumanMessage(content="head")]
    for index in range(12):
        messages.append(HumanMessage(content=f"turn {index} " + ("x" * 3000)))
        messages.append(AIMessage(content="a" * 400))
    compact_messages(messages, tail_turns=8)
    reduced = [keep for keep in seen if keep < 8]
    assert reduced
    assert reduced[0] <= 6

    seen.clear()
    small = [SystemMessage(content="SYS"), HumanMessage(content="head")]
    for _index in range(6):
        small.append(HumanMessage(content="m" * 2000))
        small.append(AIMessage(content="a"))
    small.extend(
        [
            HumanMessage(content="tail-one"),
            AIMessage(content="t1"),
            HumanMessage(content="tail-two"),
            AIMessage(content="t2"),
        ]
    )
    compact_messages(small, tail_turns=2)
    assert seen
    assert all(keep >= 2 for keep in seen)


def test_u_f5_8_02_exclude_tools_skips_named_results():
    skill = ToolMessage(content="SECRET-SKILL " + ("s" * 200), name="skill", tool_call_id="a")
    bash = ToolMessage(content="SECRET-BASH " + ("b" * 200), name="bash", tool_call_id="b")
    messages = [
        AIMessage(
            content="call",
            tool_calls=[
                {"id": "a", "name": "skill", "args": {}},
                {"id": "b", "name": "bash", "args": {}},
            ],
        ),
        skill,
        bash,
    ]
    kept, _tel = microcompact_messages(messages, keep_recent=0, exclude_tools=["skill"])
    by_id = {message.tool_call_id: str(message.content) for message in kept if getattr(message, "type", None) == "tool"}
    assert "SECRET-SKILL" in by_id["a"]
    assert by_id["b"] == TOOL_RESULT_TOMBSTONE
    cleared, _tel = microcompact_messages(messages, keep_recent=0, exclude_tools=[])
    by_id = {message.tool_call_id: str(message.content) for message in cleared if getattr(message, "type", None) == "tool"}
    assert by_id["a"] == TOOL_RESULT_TOMBSTONE
    assert by_id["b"] == TOOL_RESULT_TOMBSTONE


def _tools(old: str) -> list:
    messages = [SystemMessage(content="S"), HumanMessage(content="h")]
    messages.append(
        AIMessage(content="old", tool_calls=[{"id": "old", "name": "bash", "args": {}}])
    )
    messages.append(ToolMessage(content=old, name="bash", tool_call_id="old"))
    for name in ("r1", "r2"):
        messages.append(
            AIMessage(content=name, tool_calls=[{"id": name, "name": "bash", "args": {}}])
        )
        messages.append(ToolMessage(content="ok", name="bash", tool_call_id=name))
    return messages


def test_exclude_tools_reads_the_assistant_tool_call_name():
    messages = [
        AIMessage(content="call", tool_calls=[{"id": "a", "name": "skill", "args": {}}]),
        ToolMessage(content="SECRET-SKILL", tool_call_id="a"),
        AIMessage(content="other", tool_calls=[{"id": "b", "name": "bash", "args": {}}]),
        ToolMessage(content="SECRET-BASH", tool_call_id="b"),
    ]
    kept, _tel = microcompact_messages(messages, keep_recent=0, exclude_tools=["skill"])
    by_id = {
        message.tool_call_id: str(message.content)
        for message in kept
        if getattr(message, "type", None) == "tool"
    }
    assert "SECRET-SKILL" in by_id["a"]
    assert by_id["b"] == TOOL_RESULT_TOMBSTONE


def test_u_f5_8_03_clear_at_least_requires_enough_release_and_room():
    def count(text: str) -> int:
        return len(text or "")

    small = plan_compaction(
        _tools("z" * 400),
        context_window=350,
        reserved=0,
        count=count,
        clear_at_least=2000,
    )
    assert small["rung"] == "fold"

    fitted = plan_compaction(
        _tools("z" * 3000),
        context_window=1000,
        reserved=0,
        count=count,
        clear_at_least=2000,
    )
    assert fitted["rung"] == "microcompact"

    still_over = _tools("z" * 3000)
    still_over.insert(1, HumanMessage(content="h" * 4000))
    over = plan_compaction(
        still_over,
        context_window=500,
        reserved=0,
        count=count,
        clear_at_least=2000,
    )
    assert over["rung"] == "fold"


@pytest.mark.asyncio
async def test_agent_keeps_explicit_zero_clear_at_least(monkeypatch):
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    monkeypatch.setattr(compaction_mod, "DEFAULT_RESERVED_TOKENS", 0)
    seen: dict[str, int] = {}
    real = compaction_mod.plan_compaction

    def wrapped(*args, **kwargs):
        seen["clear"] = kwargs.get("clear_at_least")
        return real(*args, **kwargs)

    monkeypatch.setattr(compaction_mod, "plan_compaction", wrapped)
    agent = AgentV2.__new__(AgentV2)
    agent._llm = object()
    agent._capabilities = type("Caps", (), {"context_window": 300, "tokenizer": "tiktoken:o200k_base"})()
    agent._memory = type("Mem", (), {"flush_before_compaction": lambda self, _messages: None})()
    agent._session_id = ""
    agent._cfg = {"execution": {"compaction": {"clear_at_least": 0}}}
    await agent._maybe_compress_context(
        [SystemMessage(content="S"), HumanMessage(content="hi")],
        force=False,
    )
    assert seen["clear"] == 0
    agent._cfg = {}
    await agent._maybe_compress_context(
        [SystemMessage(content="S"), HumanMessage(content="hi")],
        force=False,
    )
    assert seen["clear"] == 2000
