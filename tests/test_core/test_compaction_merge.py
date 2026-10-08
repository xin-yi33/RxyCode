"""F5-5：第二次压缩必须把旧摘要并进新摘要，不能原样复用。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from RxyCode.RxyCode1_1_0.core.compaction import (
    compact_messages,
    parse_state_snapshot,
    run_compaction_ladder,
)


def _summary_text(messages) -> str:
    found = [
        str(getattr(message, "content", "") or "")
        for message in messages
        if getattr(message, "type", "") == "system"
        and bool((getattr(message, "additional_kwargs", None) or {}).get("is_compaction_summary"))
    ]
    assert found, "压缩后必须有一条 compaction summary"
    return found[-1]


def _first_chain():
    return [
        SystemMessage(content="SYS"),
        HumanMessage(content="ANCHOR-A1 搭骨架"),
        AIMessage(content="WORKSTATE-OLD " + ("x" * 3000)),
    ]


def _with_second_turn(messages):
    return list(messages) + [
        HumanMessage(content="以后都用 pytest 跑测试 NEXT-MOVE-PYTEST"),
        AIMessage(content="已把命令改成 pytest " + ("y" * 3000)),
    ]


def _folding_chain():
    """默认保留 2 轮时，断点后仍有可折叠内容。"""
    return [
        SystemMessage(content="SYS"),
        HumanMessage(content="ANCHOR-A1 搭骨架"),
        AIMessage(content="WORKSTATE-OLD " + ("x" * 2000)),
        HumanMessage(content="中段一"),
        AIMessage(content="m1 " + ("x" * 1500)),
        HumanMessage(content="中段二"),
        AIMessage(content="m2 " + ("x" * 1500)),
        HumanMessage(content="尾部保留一"),
        AIMessage(content="t1"),
        HumanMessage(content="尾部保留二"),
        AIMessage(content="t2"),
    ]


def _folding_second(messages):
    return list(messages) + [
        HumanMessage(content="中段新 NEXT-MOVE-PYTEST"),
        AIMessage(content="n1 " + ("y" * 1500)),
        HumanMessage(content="新尾一"),
        AIMessage(content="u1"),
        HumanMessage(content="以后都用 pytest 跑测试 NEXT-MOVE-PYTEST"),
        AIMessage(content="u2"),
    ]


class _RecordingSummarizer:
    def __init__(self, *, incomplete: bool = False):
        self.calls: list[tuple[list, str | None]] = []
        self.incomplete = incomplete

    def __call__(self, fold_msgs, prior_summary=None):
        self.calls.append((list(fold_msgs), prior_summary))
        if self.incomplete:
            return {"objective": "partial-only"}
        objective = "ANCHOR-A1"
        next_step = "install"
        if prior_summary:
            next_step = "NEXT-MOVE-PYTEST"
        return {
            "objective": objective,
            "constraints": "keep the first objective",
            "progress": "WORKSTATE-OLD",
            "files_touched": [],
            "next_step": next_step,
            "blockers": "none",
        }


def test_u_f5_5_01_second_fold_receives_prior_summary_and_new_messages():
    """U-F5-5-01：第二次 fold 的摘要参数含 S1 全文和新折叠段。"""
    summarizer = _RecordingSummarizer()
    first, first_tel = compact_messages(
        _first_chain(),
        tail_turns=0,
        return_telemetry=True,
        summarizer=summarizer,
    )
    assert "ANCHOR-A1" in _summary_text(first)
    second, second_tel = compact_messages(
        _with_second_turn(first),
        tail_turns=0,
        return_telemetry=True,
        summarizer=summarizer,
    )
    assert len(summarizer.calls) == 2
    _fold, prior = summarizer.calls[1]
    assert prior is not None and "ANCHOR-A1" in prior
    assert any("NEXT-MOVE-PYTEST" in str(getattr(message, "content", "") or "") for message in _fold)
    text = _summary_text(second)
    assert "ANCHOR-A1" in text
    assert "NEXT-MOVE-PYTEST" in text
    assert second_tel["summary_source"] == "llm"
    assert first_tel["summary_source"] == "llm"


def test_u_f5_5_02_rule_fallback_merges_prior_summary():
    """U-F5-5-02：没有 summarizer 时也不能原样复用旧摘要。"""
    first, _tel = compact_messages(_first_chain(), tail_turns=0, return_telemetry=True)
    old = _summary_text(first)
    second, _tel2 = compact_messages(
        _with_second_turn(first),
        tail_turns=0,
        return_telemetry=True,
        summarizer=None,
    )
    text = _summary_text(second)
    assert text != old
    assert "ANCHOR-A1" in text
    assert "WORKSTATE-OLD" in text
    assert "NEXT-MOVE-PYTEST" in text


def test_u_f5_5_03_incomplete_snapshot_uses_merged_rule_summary():
    """U-F5-5-03：缺字段走 rule，并且两次压缩都发生、旧状态还在。"""
    assert parse_state_snapshot({"objective": "only"}) is None
    summarizer = _RecordingSummarizer(incomplete=True)
    first, first_tel = run_compaction_ladder(
        _folding_chain(),
        force=True,
        context_window=200_000,
        reserved=0,
        summarizer=summarizer,
    )
    second, second_tel = run_compaction_ladder(
        _folding_second(first),
        force=True,
        context_window=200_000,
        reserved=0,
        summarizer=summarizer,
    )
    assert first_tel["did_compact"] is True
    assert second_tel["did_compact"] is True
    assert second_tel["summary_source"] == "rule"
    text = _summary_text(second)
    assert "ANCHOR-A1" in text
    assert "NEXT-MOVE-PYTEST" in text


def test_rule_merge_keeps_multiline_prior_fields():
    """旧摘要的约束、进度和失败记录可以跨行，不能只留冒号后的第一行。"""
    from RxyCode.RxyCode1_1_0.core.compaction import compact_messages

    prior = "\n".join(
        [
            "<summary>",
            "Objective: ANCHOR-A1",
            "Constraints: 以后都用 pytest 跑测试",
            "and do not switch runners",
            "Progress: WORKSTATE-OLD",
            "line two of progress",
            "Files Touched: a.py",
            "b.py",
            "Next Step: old step",
            "Blockers: tool 返回报错 pytest-collect-failed",
            "the command was pytest",
            "</summary>",
        ]
    )
    seeded = [
        SystemMessage(content="SYS"),
        HumanMessage(content="ANCHOR-A1 搭骨架"),
        SystemMessage(content=prior, additional_kwargs={"is_compaction_summary": True}),
        HumanMessage(content="NEXT-MOVE-PYTEST"),
        AIMessage(content="y" * 2000),
    ]
    merged, telemetry = compact_messages(
        seeded, tail_turns=0, return_telemetry=True, summarizer=None
    )
    text = _summary_text(merged)
    assert "and do not switch runners" in text
    assert "line two of progress" in text
    assert "b.py" in text
    assert "the command was pytest" in text
    assert "NEXT-MOVE-PYTEST" in text
    assert telemetry["summary_source"] == "rule"


def test_keyword_only_prior_and_kwargs_summarizer_stay_on_the_llm_path():
    """keyword-only 要收到 prior；单参数加 **kwargs 不能因为多传位置参数改走 rule。"""
    seen: dict[str, object] = {}

    def keyword_only(fold_msgs, *, prior_summary=None):
        del fold_msgs
        seen["prior"] = prior_summary
        return {
            "objective": "FROM-KEYWORD" if prior_summary else "ANCHOR-A1",
            "constraints": "keep",
            "progress": "second",
            "files_touched": [],
            "next_step": "NEXT-MOVE-PYTEST",
            "blockers": "none",
        }

    def kwargs_only(fold_msgs, **kwargs):
        del fold_msgs
        seen["kwargs"] = dict(kwargs)
        return {
            "objective": "FROM-KWARGS",
            "constraints": "keep",
            "progress": "second",
            "files_touched": [],
            "next_step": "NEXT-MOVE-PYTEST",
            "blockers": "none",
        }

    first, _tel = compact_messages(
        _first_chain(), tail_turns=0, return_telemetry=True, summarizer=keyword_only
    )
    second, second_tel = compact_messages(
        _with_second_turn(first),
        tail_turns=0,
        return_telemetry=True,
        summarizer=keyword_only,
    )
    assert isinstance(seen.get("prior"), str) and "ANCHOR-A1" in seen["prior"]
    assert "FROM-KEYWORD" in _summary_text(second)
    assert second_tel["summary_source"] == "llm"

    seen.clear()
    again, again_tel = compact_messages(
        _with_second_turn(first),
        tail_turns=0,
        return_telemetry=True,
        summarizer=kwargs_only,
    )
    assert again_tel["summary_source"] == "llm"
    assert "FROM-KWARGS" in _summary_text(again)
    assert "prior_summary" in seen["kwargs"]


@pytest.mark.asyncio
async def test_one_arg_prefetch_replacement_still_compacts(monkeypatch):
    """F5-3 的单参数预取替身不能被第二个位置参数打成 TypeError。"""
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    monkeypatch.setattr(compaction_mod, "DEFAULT_RESERVED_TOKENS", 0)

    async def _no_summary(_messages):
        return None

    agent = AgentV2.__new__(AgentV2)
    agent._llm = SimpleNamespace()
    agent._capabilities = SimpleNamespace(context_window=300, tokenizer="tiktoken:o200k_base")
    agent._memory = SimpleNamespace(flush_before_compaction=lambda _messages: None)
    agent._session_id = ""
    agent._prefetch_compaction_summary = _no_summary
    messages = _folding_chain()
    await agent._maybe_compress_context(messages, force=True)
    assert agent._band_full_on_next is True
    assert "ANCHOR-A1" in _summary_text(messages)


@pytest.mark.asyncio
async def test_mo_f5_5_01_second_over_limit_still_prefetches_prior_summary(monkeypatch):
    """MO-F5-5-01：真实 _maybe_compress_context 在已有摘要后仍预取，且只调用一次模型。"""
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    monkeypatch.setattr(compaction_mod, "DEFAULT_RESERVED_TOKENS", 0)

    class _SpyLLM:
        def __init__(self):
            self.prompts: list[str] = []

        async def ainvoke(self, messages, **_kwargs):
            text = "\n".join(str(getattr(message, "content", "") or "") for message in messages)
            self.prompts.append(text)
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "objective": "ANCHOR-A1",
                        "constraints": "none",
                        "progress": "WORKSTATE-OLD",
                        "files_touched": [],
                        "next_step": "NEXT-MOVE-PYTEST" if len(self.prompts) > 1 else "install",
                        "blockers": "none",
                    }
                )
            )

    agent = AgentV2.__new__(AgentV2)
    agent._llm = _SpyLLM()
    agent._capabilities = SimpleNamespace(context_window=300, tokenizer="tiktoken:o200k_base")
    agent._memory = SimpleNamespace(flush_before_compaction=lambda _messages: None)
    agent._session_id = ""
    messages = _folding_chain()
    await agent._maybe_compress_context(messages)
    messages.extend(_folding_second([]))
    await agent._maybe_compress_context(messages)
    assert len(agent._llm.prompts) == 2
    assert "ANCHOR-A1" in agent._llm.prompts[1]
    assert "NEXT-MOVE-PYTEST" in agent._llm.prompts[1]
    text = _summary_text(messages)
    assert "ANCHOR-A1" in text
    assert "NEXT-MOVE-PYTEST" in text
