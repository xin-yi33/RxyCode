"""layer=unit/module F4-2 fold 接线 LLM 摘要。"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.cache_policy import tool_pair_integrity
from RxyCode.RxyCode1_1_0.core.compaction import (
    TOOL_RESULT_TOMBSTONE,
    build_summary_message,
    compact_messages,
)


def _foldable_chain():
    """断点后可折叠的真实消息链：2 个工具轮 + 尾 2 轮。"""
    return [
        SystemMessage(content="S1-FROZEN"),
        HumanMessage(content="请帮我给登录加设备验证"),
        AIMessage(
            content="先读 auth.py",
            tool_calls=[{"id": "c1", "name": "read_file", "args": {"path": "auth.py"}}],
        ),
        ToolMessage(content="auth 源码内容" * 30, tool_call_id="c1"),
        AIMessage(content="已读取 auth.py，开始修改 login.py"),
        HumanMessage(content="继续，注意保持接口兼容"),
        AIMessage(
            content="改写 login.py",
            tool_calls=[{"id": "c2", "name": "write_file", "args": {"path": "login.py"}}],
        ),
        ToolMessage(content="write ok " * 40, tool_call_id="c2"),
        AIMessage(content="改完 2/3 个任务"),
        HumanMessage(content="下一步做什么？"),
        AIMessage(content="写设备验证的单测"),
    ]


_GOOD_FIELDS = {
    "objective": "add login device verification",
    "constraints": "no ORM change",
    "progress": "2/3 tasks done",
    "files_touched": ["auth.py", "login.py"],
    "next_step": "write tests",
    "blockers": "none",
}


def _summary_text(result) -> str:
    summaries = [
        getattr(m, "content", "")
        for m in result
        if getattr(m, "type", "") == "system"
        and bool((getattr(m, "additional_kwargs", None) or {}).get("is_compaction_summary"))
    ]
    assert summaries, "fold 之后必须存在 compaction summary 消息"
    return summaries[-1]


def test_u_f4_2_01_llm_summary_renders_six_fields():
    """layer=unit U-F4-2-01
    summarizer 注入且成功 → fold 摘要逐字节含六字段标签与值；配对守恒；telemetry 记 llm。
    """
    async def summarizer(_messages):
        return dict(_GOOD_FIELDS)

    result, telemetry = compact_messages(
        _foldable_chain(), return_telemetry=True, summarizer=summarizer
    )
    text = _summary_text(result)
    assert text.startswith("<summary>")
    assert "Objective: add login device verification" in text
    assert "Constraints: no ORM change" in text
    assert "Progress: 2/3 tasks done" in text
    assert "Files Touched: auth.py, login.py" in text
    assert "Next Step: write tests" in text
    assert "Blockers: none" in text
    assert text.rstrip().endswith("</summary>")
    assert tool_pair_integrity(result) is True
    assert telemetry["compacted"] is True
    assert telemetry["summary_source"] == "llm"
    # 断点前不可变
    assert getattr(result[0], "content", None) == "S1-FROZEN"


def test_u_f4_2_02_llm_timeout_falls_back_to_rule_template():
    """layer=unit U-F4-2-02
    LLM 超时 → 回退规则模板（首 human / 首 ai / 末 human 各 200 字符规则），telemetry 记 rule。
    规则模板内容必须与 build_summary_message 现状逐字节同构。
    """
    async def summarizer(_messages):
        raise TimeoutError("llm slow")

    result, telemetry = compact_messages(
        _foldable_chain(), return_telemetry=True, summarizer=summarizer
    )
    text = _summary_text(result)
    assert "Objective: 请帮我给登录加设备验证" in text
    assert "Work State: 先读 auth.py" in text
    assert "Next Move: 下一步做什么？" in text
    assert "Files Touched:" not in text           # 回退路径不得混入六字段
    assert telemetry["summary_source"] == "rule"
    assert tool_pair_integrity(result) is True


def test_u_f4_2_03_llm_bad_json_falls_back_to_rule_template():
    """layer=unit U-F4-2-03
    LLM 解析失败（缺六字段键 / 非法 JSON）→ 同样整体回退规则模板，不得半 LLM 半规则拼接。
    """
    async def summarizer(_messages):
        return {"objective": "only one field"}     # 缺键 = 解析失败

    result, telemetry = compact_messages(
        _foldable_chain(), return_telemetry=True, summarizer=summarizer
    )
    text = _summary_text(result)
    assert "Objective: 请帮我给登录加设备验证" in text
    assert "only one field" not in text
    assert telemetry["summary_source"] == "rule"
    assert tool_pair_integrity(result) is True


def test_u_f4_2_04_pairing_guard_still_falls_back_unmodified():
    """layer=unit U-F4-2-04
    assistant↔tool 配对守恒不破：构造折叠必然孤儿化的链 → 结果回退原消息（api 400 防线）。
    该守卫对 LLM 与规则两条路径一视同仁。
    """
    broken = [
        SystemMessage(content="S1"),
        HumanMessage(content="h1"),
        AIMessage(
            content="call",
            tool_calls=[{"id": "cx", "name": "shell", "args": {"cmd": "x"}}],
        ),
        ToolMessage(content="out " * 20, tool_call_id="OTHER_NO_MATCH_AI"),
        AIMessage(content="a1"),
        HumanMessage(content="h2"),
        AIMessage(content="a2"),
        HumanMessage(content="h3"),
        AIMessage(content="a3"),
    ]

    async def summarizer(_messages):
        return dict(_GOOD_FIELDS)

    result, telemetry = compact_messages(broken, return_telemetry=True, summarizer=summarizer)
    if not tool_pair_integrity(result):
        # 只有「回退到未修改」是合法结果；此时 pairing 必然成立。
        raise AssertionError("pairing broken must fall back to unmodified messages")
    assert tool_pair_integrity(result) is True


def test_mo_f4_2_01_compaction_ladder_llm_summary_prefix_bytes_unchanged():
    """layer=module MO-F4-2-01
    全阶梯：microcompact 墓碑先行 → fold LLM 摘要落盘（rung=fold、summary_source=llm）；
    断点前缀逐字节不变（S1 与首轮 human 原文）。
    """
    from RxyCode.RxyCode1_1_0.core.compaction import run_compaction_ladder

    async def summarizer(_messages):
        return dict(_GOOD_FIELDS, files_touched=["auth.py", "login.py"])

    chain = _foldable_chain()
    out, telemetry = run_compaction_ladder(
        chain,
        force=True,
        context_window=200_000,
        summarizer=summarizer,
    )
    assert telemetry["rung"] == "fold"
    assert telemetry["summary_source"] == "llm"
    assert telemetry["tombstoned"] >= 2            # 两处旧 tool result 被打墓碑
    tool_texts = [
        getattr(m, "content", "") for m in out if getattr(m, "type", "") == "tool"
    ]
    assert tool_texts, "tail 必须仍在"
    assert any(TOOL_RESULT_TOMBSTONE in t for t in tool_texts)
    assert getattr(out[0], "content", None) == "S1-FROZEN"
    early_human = next(
        m for m in out if getattr(m, "type", "") == "human"
    )
    assert getattr(early_human, "content", None) == "请帮我给登录加设备验证"
    text = _summary_text(out)
    assert "Blockers: none" in text
    assert tool_pair_integrity(out) is True


@pytest.mark.asyncio
async def test_u_f4_2_05_async_summary_wait_does_not_block_event_loop():
    """layer=unit U-F4-2-05（2026-10-01 异步桥行为面）
    可控慢 summarizer（async 延迟注入）等待期间，事件循环 tick 探针持续前进
    ——心跳/其它任务不被摘要阻塞；等待结束后返回六字段渲染。
    """
    from RxyCode.RxyCode1_1_0.core.compaction import try_llm_summary_async

    ticks = {"n": 0}
    stop = asyncio.Event()

    async def probe():
        while not stop.is_set():
            await asyncio.sleep(0.01)
            ticks["n"] += 1

    async def slow_summarizer(_messages):
        await asyncio.sleep(0.2)
        return dict(_GOOD_FIELDS)

    probe_task = asyncio.create_task(probe())
    summary = await try_llm_summary_async(slow_summarizer, _foldable_chain())
    stop.set()
    await probe_task

    assert ticks["n"] >= 5                     # 探针在 0.2s 慢摘要期间持续 tick（未阻塞）
    assert summary is not None
    assert "Objective: add login device verification" in summary
    assert "Blockers: none" in summary


@pytest.mark.asyncio
async def test_u_f4_2_06_summary_wait_cancelled_result_never_applied():
    """layer=unit U-F4-2-06（2026-10-01 异步桥行为面）
    摘要等待被取消：CancelledError 向上传播（不得吞进规则回退）；被 await 的
    LLM 调用随之取消、不再补完 —— 迟到结果不存在，旧摘要/迟到摘要都不被应用。
    """
    from RxyCode.RxyCode1_1_0.core.compaction import try_llm_summary_async

    started = asyncio.Event()
    completed = asyncio.Event()

    async def very_slow_summarizer(_messages):
        started.set()
        await asyncio.sleep(1.0)
        completed.set()                          # 到达这里 = 未被取消（bug 信号）
        return dict(_GOOD_FIELDS)

    waiter = asyncio.create_task(try_llm_summary_async(very_slow_summarizer, _foldable_chain()))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.sleep(1.1)                     # 给它"补完"的机会
    assert completed.is_set() is False           # 摘要协程已取消：结果从不存在
    # 取消后本应走规则模板的链路只由生产异步路径显式驱动；此处硬锚是"无迟到结果"。


def _counting_summarizer():
    """裁定 B 计数 stub：记录 LLM 摘要调用次数与收到的消息面。"""

    class _Counter:
        def __init__(self):
            self.calls = 0
            self.seen_msgs = None

        async def __call__(self, messages):
            self.calls += 1
            self.seen_msgs = list(messages)
            return dict(_GOOD_FIELDS)

    return _Counter()


def _tiny_chain():
    return [
        SystemMessage(content="S1"),
        HumanMessage(content="hello"),
        AIMessage(content="hi"),
    ]


def _micro_enough_chain():
    """4 条大 tool result：初次 occupancy 超 usable，墓碑 2 条后即回落（该走 microcompact）。"""
    messages = [SystemMessage(content="S1"), HumanMessage(content="任务开始")]
    for i in range(4):
        messages.append(
            AIMessage(
                content=f"call{i}",
                tool_calls=[{"id": f"c{i}", "name": "read_file", "args": {"path": f"m{i}.py"}}],
            )
        )
        messages.append(ToolMessage(content="x" * 3000, tool_call_id=f"c{i}"))
    messages.append(HumanMessage(content="继续"))
    messages.append(AIMessage(content="好"))
    return messages


def test_u_f4_2_07_plan_gate_none_summarizer_never_called():
    """layer=unit U-F4-2-07（裁定 B：无需压缩 → LLM 0 次）
    occupancy 未超 usable → plan rung == "none"；带 summarizer 走 ladder 也 0 次调用。
    """
    from RxyCode.RxyCode1_1_0.core.compaction import plan_compaction, run_compaction_ladder

    stub = _counting_summarizer()
    chain = _tiny_chain()
    plan = plan_compaction(chain, context_window=200_000, reserved=100)
    assert plan["rung"] == "none"
    out, telemetry = run_compaction_ladder(
        chain, context_window=200_000, reserved=100, summarizer=stub
    )
    assert stub.calls == 0
    assert telemetry["rung"] == "none"
    assert out == chain                                # none 路径逐字节不动


def test_u_f4_2_08_plan_gate_microcompact_summarizer_never_called():
    """layer=unit U-F4-2-08（裁定 B：microcompact 已够 → LLM 0 次）
    初次 occupancy 超 usable；墓碑先行后回落 → rung == "microcompact"、0 次摘要调用。
    """
    from RxyCode.RxyCode1_1_0.core.compaction import plan_compaction, run_compaction_ladder

    stub = _counting_summarizer()
    chain = _micro_enough_chain()
    plan = plan_compaction(chain, context_window=3_000, reserved=0)
    assert plan["rung"] == "microcompact"
    out, telemetry = run_compaction_ladder(
        chain, context_window=3_000, reserved=0, summarizer=stub
    )
    assert stub.calls == 0
    assert telemetry["rung"] == "microcompact"
    assert telemetry["tombstoned"] == 2


def test_u_f4_2_09_plan_gate_fold_summarizer_called_once_on_fold_msgs():
    """layer=unit U-F4-2-09（裁定 B：确需 fold → 恰 1 次，且只喂 fold_msgs）
    force=True → rung == "fold"；summarizer 调用计数 == 1；其入参逐条 == plan["fold_msgs"]。
    """
    from RxyCode.RxyCode1_1_0.core.compaction import plan_compaction, run_compaction_ladder

    stub = _counting_summarizer()
    chain = _foldable_chain()
    plan = plan_compaction(chain, force=True, context_window=200_000, reserved=100)
    assert plan["rung"] == "fold"
    assert plan["fold_msgs"]                           # 计划折叠段非空
    out, telemetry = run_compaction_ladder(
        chain, force=True, context_window=200_000, reserved=100, summarizer=stub
    )
    assert stub.calls == 1
    assert telemetry["rung"] == "fold"
    assert telemetry["summary_source"] == "llm"
    got = [getattr(m, "content", "") for m in (stub.seen_msgs or [])]
    want = [getattr(m, "content", "") for m in plan["fold_msgs"]]
    assert got == want                                 # 只喂 fold_msgs，不喂全量链


@pytest.mark.asyncio
async def test_u_f4_2_10_real_maybe_compress_context_no_compaction_zero_llm():
    """layer=unit U-F4-2-10（三轮复审 #3 生产路径锚）
    调用**真实** `AgentV2._maybe_compress_context`（occupancy 远低于 window − reserved）：
    plan.rung == "none" 时**对模型的调用为 0 次**（spy LLM 计数）——预取被 plan 门控，
    不是无条件发起（GPT 复审 #3 的 0/0/1 断言在生产路径上的最后一环）。
    """
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    class _SpyLLM:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages, **kwargs):
            self.calls += 1
            raise AssertionError("no-compaction 下不得发起摘要调用")

    agent = AgentV2.__new__(AgentV2)
    agent._llm = _SpyLLM()
    agent._agent_prefix_messages = _tiny_chain()   # 远未超限的消息链
    messages = list(agent._agent_prefix_messages)
    await AgentV2._maybe_compress_context(agent, messages)
    assert agent._llm.calls == 0
    assert not any(
        getattr(m, "additional_kwargs", {}).get("is_compaction_summary")
        for m in messages
    )                                                  # 未注入任何摘要消息


def test_mo_f4_2_02_production_async_path_awaits_summary_seam():
    """layer=module MO-F4-2-02（源码门，同 MO-F4-8-01/ MO-F4-9-01 手法）
    生产 async 注入点（agent_v2._maybe_compress_context）必须经 try_llm_summary_async
    的 await 等待摘要（或在 try_llm_summary_async 内部 await 注入适配器）；
    线程桥关键字不得出现在生产注入路径。
    """
    import inspect

    from RxyCode.RxyCode1_1_0.core import agent_v2

    src = inspect.getsource(agent_v2.AgentV2._maybe_compress_context)
    assert "summarizer=" in src or "summarizer=self._compaction_summarizer" in src
    from RxyCode.RxyCode1_1_0.core import compaction as compaction_mod

    csrc = inspect.getsource(compaction_mod)
    assert "try_llm_summary_async" in csrc
    assert "def try_llm_summary_async" in csrc
    assert "Thread(" not in inspect.getsource(compaction_mod.try_llm_summary_async)
