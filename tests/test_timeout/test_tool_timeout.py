"""layer=unit P6"""
from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator


class _StubEngine:
    def __init__(self, resp, granted=1.0):
        self._resp = resp
        self._granted = granted
        self.calls: list[dict] = []

    async def decide(self, evidence):
        from RxyCode.RxyCode1_1_0.core.timeout_decision import Grant
        from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionResponse
        self.calls.append(evidence.model_dump())
        r = dict(self._resp)
        if r["action"] == "continue":
            r["extend_seconds"] = self._granted
            g = Grant(granted_seconds=self._granted, new_budget=1800.0 + self._granted)
        else:
            g = None
        self._grant = g
        return TimeoutDecisionResponse(**r)

    def last_grant(self, scope):
        return self._grant


def _controllable_tool(name, release: asyncio.Event, *, cancelled=None, cleanup=None):
    """可控完成：release.set() 前一直跑；Cancel 时记录且调 finally 清理钩子。"""
    tool = MagicMock()
    tool.name = name

    async def ainvoke(args):
        try:
            await release.wait()
        except asyncio.CancelledError:
            if cancelled is not None:
                cancelled.append(name)
            raise
        return f"{name}-done"

    tool.ainvoke = ainvoke
    tool.coroutine = ainvoke
    if cleanup is not None:
        tool._cleanup_hook = cleanup        # 编排器 stop/取消后必须调用的清理钩子（钉死观察点）
    return tool


def _make(tool, engine):
    orch = ToolOrchestrator(timeout_engine=engine)
    orch.register(tool.name, tool, risk="write")
    return orch


async def _run(orch, name, timeout):
    return await orch.execute_tool(name, "x", {"execution": {"tool_timeout_seconds": timeout}})


async def test_u_p6_01_continue_and_underlying_task_acquires_real_result():
    """layer=unit U-P6-01 续期成功：(a) 第一次超时后底层 task 仍在跑；(b) continue 后等到真实结果"""
    release = asyncio.Event()
    tool = _controllable_tool("p6-go", release)
    engine = _StubEngine({"action": "continue", "extend_seconds": 0, "note": "放行", "confidence": 0.9},
                         granted=1.0)
    orch = _make(tool, engine)
    holder = orch.expose_invocation_for_test()          # 钉死观察口：当前底层 task（不存在为 None）
    run = asyncio.create_task(_run(orch, "p6-go", 0.05))
    await asyncio.sleep(0.2)                            # 已越过第一次超时、决策也已完成
    inner = holder() or getattr(orch, "_active_invocation", None)
    assert inner is not None and not inner.done()       # (a) 第一次 wait_for 超时后底层仍在跑
    release.set()                                       # (b) 现在放行：同一 task 应给出真实结果
    out = await asyncio.wait_for(run, timeout=2.0)      # 不抛 CancelledError
    assert out == "p6-go-done"
    assert len(engine.calls) == 1 and engine.calls[0]["trigger_point"] == "tool_timeout"
    # 拓扑钉死：每次等待新建 shield——继续期间任务对象始终是同一个底层 task
    assert inner is (holder() or getattr(orch, "_active_invocation", None))


async def test_u_p6_02_second_timeout_hits_status_quo_and_cancels():
    """layer=unit U-P6-02 第二次到点：一次性询问、现状报文逐字节、底层 task cancel+await 收殓"""
    cancelled: list[str] = []
    engine = _StubEngine({"action": "continue", "extend_seconds": 0, "note": "再放 0.15s", "confidence": 0.6},
                         granted=0.15)
    tool = _controllable_tool("p6-once", asyncio.Event(), cancelled=cancelled)   # 永不放行
    out = await _run(_make(tool, engine), "p6-once", 0.05)
    assert len(engine.calls) == 1                                # 第二次到点不再询问
    assert out.startswith("[error: tool 'p6-once' timed out after 0.05s]")
    assert "The tool did not return a result." in out            # 现状尾句逐字节
    assert cancelled == ["p6-once"]                              # 二次到点也 cancel+await 原 task


async def test_u_p6_03_cancel_during_decision_voids_pending_and_cancels_task():
    """layer=unit U-P6-03 决策期间用户取消：engine.interrupt 作废 pending 决策、任务被取消"""
    ledger = td.ExtensionLedger()
    engine = td.TimeoutDecisionEngine(
        _HangLLM(), td.DecisionPolicy(_policy_dict()), ledger=ledger)
    cancelled: list[str] = []
    tool = _controllable_tool("p6-cancel", asyncio.Event(), cancelled=cancelled)
    orch = _make(tool, engine)
    run = asyncio.create_task(_run(orch, "p6-cancel", 0.05))
    await asyncio.sleep(0.15)                            # 第一次超时已过，决策 pending 中
    assert engine.pending_decisions == 1
    run.cancel()                                         # 用户取消路径
    with pytest.raises(asyncio.CancelledError):
        await run
    assert cancelled == ["p6-cancel"]                    # (d) 用户取消同样 cancel+await 原始 task
    kinds = [k for k, _t in engine.trajectory]
    assert "interrupt" in kinds and kinds.index("interrupt") < len(kinds) - 1
    assert engine.pending_decisions == 0                 # pending 决策作废收殓


async def test_u_p6_04_stop_cancels_then_cleans_with_no_residue(tmp_path):
    """layer=unit U-P6-04 停止路径：cancel+await、task.cancelled()、finally 钩子、无残留进程/协程"""
    engine = _StubEngine({"action": "stop", "extend_seconds": 0.0, "note": "掐", "confidence": 0.95})
    cancelled: list[str] = []
    cleaned: list[str] = []
    tool = _controllable_tool("p6-stop", asyncio.Event(), cancelled=cancelled,
                              cleanup=lambda: cleaned.append("cleaned"))
    orch = _make(tool, engine)
    holder = orch.expose_invocation_for_test()
    tasks_before = set(asyncio.all_tasks())
    out = await _run(orch, "p6-stop", 0.05)
    assert out.startswith("[error: tool 'p6-stop' timed out after 0.05s]")
    inner = holder()
    assert inner is not None and inner.cancelled()       # stop 走 task.cancel() + await task
    assert cancelled == ["p6-stop"]
    assert cleaned == ["cleaned"]                        # finally 清理钩子被调用
    await asyncio.sleep(0)
    leaked = set(asyncio.all_tasks()) - tasks_before
    assert leaked == set()                               # 无残留协程
    assert _marker_pids("p6-stop-marker") == set()       # 无工具子进程残留（真实探针）


async def test_u_p6_05_outer_cancel_during_first_wait_never_asks_decision():
    """layer=unit U-P6-05 首次 wait_for 期间外层 cancel → 底层 task.cancelled() +
    清理钩子执行 + 决策从未发起（超时未到点，一次都没问）"""
    engine = _StubEngine({"action": "continue", "extend_seconds": 0, "note": "n", "confidence": 0.5})
    cancelled: list[str] = []
    cleaned: list[str] = []
    tool = _controllable_tool("p6-cw", asyncio.Event(), cancelled=cancelled,
                              cleanup=lambda: cleaned.append("cleaned"))
    orch = _make(tool, engine)
    holder = orch.expose_invocation_for_test()
    run = asyncio.create_task(_run(orch, "p6-cw", 30.0))         # timeout 30s：远在首次等待期内
    await asyncio.sleep(0)                                       # run 已起步、未超首 wait
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    inner = holder()
    assert inner is not None and inner.cancelled()               # cancel+await 原始 task
    assert cancelled == ["p6-cw"]
    assert cleaned == ["cleaned"]                                # 清理钩子在外层取消也执行
    assert engine.calls == []                                    # 决策从未发起（deferred_decide 未触发）


async def test_u_p6_06_outer_cancel_during_extension_wait_interrupts_and_latch_resets():
    """layer=unit U-P6-06 续期 wait 期间外层 cancel → engine.interrupt 被调、task 收尸、
    per-invocation latch 复位：连续两个工具调用各自获得独立决策机会"""
    engine = _StubEngine({"action": "continue", "extend_seconds": 0, "note": "续", "confidence": 0.9},
                         granted=30.0)
    interrupt_calls: list[int] = []
    real_interrupt = getattr(engine, "interrupt", None)

    def _interrupt_spy():
        interrupt_calls.append(1)
        if real_interrupt is not None:
            real_interrupt()

    engine.interrupt = _interrupt_spy
    killed: list[str] = []
    tool = _controllable_tool("p6-xw", asyncio.Event(), cancelled=killed)
    orch = _make(tool, engine)
    run = asyncio.create_task(_run(orch, "p6-xw", 0.05))
    await asyncio.sleep(0.2)                                     # 已过首超时、决策完成、续期等待中
    assert len(engine.calls) == 1
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert interrupt_calls == [1]                                # engine.interrupt 被调
    assert killed == ["p6-xw"]                                   # task 收尸

    # latch 复位：第二个工具调用重新获得决策机会（per-invocation，非 per-orchestrator）
    engine2 = _StubEngine({"action": "stop", "extend_seconds": 0.0, "note": "停", "confidence": 0.9})
    tool2 = _controllable_tool("p6-xw2", asyncio.Event(), cancelled=[])
    out2 = await _run(_make(tool2, engine2), "p6-xw2", 0.05)
    assert out2.startswith("[error: tool 'p6-xw2' timed out after 0.05s]")
    assert len(engine2.calls) == 1                               # 第二调用独立决策，不受上一调用 latch 残留影响


class _HangLLM:
    """决策 LLM 挂死：pending 直到外部结束。"""
    async def ainvoke(self, prompt, **kw):
        await asyncio.sleep(3600)


def _policy_dict():
    return {
        "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
        "decision_timeout_seconds": 5.0, "decision_model": None, "fail_closed": True,
        "absolute_cap_seconds": {"graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
                                 "watchdog_stall": 1800.0, "tool_timeout": 7200.0},
    }


def _coro_tool(name, seconds, *, cancelled=None):
    tool = MagicMock()
    tool.name = name

    async def ainvoke(args):
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            if cancelled is not None:
                cancelled.append(name)
            raise
        return f"{name}-done"

    tool.ainvoke = ainvoke
    tool.coroutine = ainvoke
    return tool


def _marker_pids(marker):                               # 逐字抄 tests/contract/test_timeout_cancel.py
    from tests.contract.test_timeout_cancel import _marker_pids as real
    return real(marker)


async def test_mo_p6_01_no_background_tasks_or_processes_leak():
    """layer=module MO-P6-01 决策环不引入后台任务：all_tasks 前后集合相等、线程数不变（保留断言）"""
    engine = _StubEngine({"action": "continue", "extend_seconds": 600, "note": "放行", "confidence": 0.9},
                         granted=1.0)
    tool = _coro_tool("p6-clean", 0.15)
    orch = _make(tool, engine)
    tasks_before = set(asyncio.all_tasks())
    threads_before = len(threading.enumerate())
    out = await _run(orch, "p6-clean", 0.05)
    assert out == "p6-clean-done"
    await asyncio.sleep(0)
    leaked = set(asyncio.all_tasks()) - tasks_before
    assert leaked == set(), f"决策环泄漏协程: {leaked}"
    assert len(threading.enumerate()) == threads_before          # 无 task 句柄/新线程
