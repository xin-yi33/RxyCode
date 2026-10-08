"""layer=e2e E-P-E2E-09"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from unittest.mock import MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from tests.e2e.phase_p import helpers
from tests.contract.test_timeout_cancel import _marker_pids

pytestmark = pytest.mark.e2e
MARKER = "e2e-p9-child-marker"


def _proc_tool(name, seconds, *, killed=None):
    """真实子进程 dummy：工作时长 seconds；被 Cancel 时杀子进程树并记录。"""
    tool = MagicMock()
    tool.name = name

    async def ainvoke(args):
        child = subprocess.Popen(
            [sys.executable, "-c", f"import time\ntime.sleep(30)  # {MARKER}"])
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            child.kill()
            child.wait()
            if killed is not None:
                killed.append(name)
            raise
        child.kill()
        child.wait()
        return f"{name}-done"

    tool.ainvoke = ainvoke
    tool.coroutine = ainvoke
    return tool


async def test_e2e_p_09_extend_interrupt_cleanup_then_second_round():
    """layer=e2e E-P-E2E-09 复合真实链路：延长生效→interrupt→无残留→同会话再发成功"""
    # ── 阶段 1 setup：真实 engine（scripted）+ 真实 orchestrator + 真实子进程工具 ──
    ledger = td.ExtensionLedger()
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([helpers.cont(2.0, "再放两秒"), {"hang_seconds": 60}]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=ledger, sink=(collect := []))
    orch = ToolOrchestrator(timeout_engine=engine)
    cfg = {"execution": {"tool_timeout_seconds": 0.05}}
    # ── 阶段 2 扰动 A：第一次超时 → 决策 continue → 延长内拿到真实结果 ──
    quick = _proc_tool("p9-extend", 0.4)
    orch.register("p9-extend", quick, risk="write")
    out1 = await orch.execute_tool("p9-extend", "x", cfg)
    assert out1 == "p9-extend-done"                                # continue 生效：延长后真实返回
    helpers.assert_event_fields(collect[0], trigger_point="tool_timeout", action="continue",
                               extension_index=1, fail_closed=False)
    assert collect[0]["extend_seconds"] == pytest.approx(2.0)
    # ── 阶段 2 扰动 B：长任务决策 pending → 用户 interrupt ──
    killed: list[str] = []
    long_tool = _proc_tool("p9-long", 30, killed=killed)
    orch.register("p9-long", long_tool, risk="write")
    tasks_before = set(asyncio.all_tasks())
    threads_before = len(threading.enumerate())
    run = asyncio.create_task(orch.execute_tool("p9-long", "x", cfg))
    await asyncio.sleep(0.2)                                       # 决策 pending（hang 60s）
    assert engine.pending_decisions == 1
    engine.interrupt()                                             # 用户 interrupt（作废 pending）
    run.cancel()                                                   # 用户取消路径（P6 (d) 语义）
    with pytest.raises(asyncio.CancelledError):
        await run
    # ── 阶段 3 断言 B：进程/协程清理 ──
    await asyncio.sleep(0.2)                                       # 给 OS 回收一拍
    assert killed == ["p9-long"]                                   # 原始 task 被取消
    assert _marker_pids(MARKER) == set()                           # 无子进程残留（真实探针）
    assert engine.pending_decisions == 0
    kinds = [k for k, _t in engine.trajectory]
    assert "interrupt" in kinds
    leaked = set(asyncio.all_tasks()) - tasks_before
    assert leaked == set()                                         # 无协程泄漏
    assert len(threading.enumerate()) == threads_before
    # ── 阶段 4 同会话再发一轮并成功返回 ──
    echo = _proc_tool("p9-round2", 0.0)
    orch.register("p9-round2", echo, risk="write")
    out3 = await orch.execute_tool("p9-round2", "x", cfg)
    assert out3 == "p9-round2-done"                                # 同会话复跑成功
    # E-P-E2E-07 wins: the same interrupt() settles a fail-closed stop.
    assert [e["action"] for e in collect] == ["continue", "stop"]
    assert collect[1]["fail_closed"] is True
    assert collect[1]["note"].startswith("[fail-closed] interrupted")
