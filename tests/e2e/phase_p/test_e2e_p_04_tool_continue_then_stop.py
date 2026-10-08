"""layer=e2e E-P-E2E-04"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from tests.e2e.phase_p import helpers

pytestmark = pytest.mark.e2e


def _coro_tool(name, seconds, cancelled=None):
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


async def test_e2e_p_04_continue_then_second_stop_turn_survives():
    """layer=e2e E-P-E2E-04 第一次延长成功、第二次按现状 error 回喂、turn 不死"""
    # ── 阶段 1 setup：真实 orchestrator + 真实 engine（turn 级 ledger）──
    ledger = td.ExtensionLedger()
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([helpers.cont(0.5, "再放一次"), helpers.stop("够了")]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=ledger, sink=(collect := []))
    orch = ToolOrchestrator(timeout_engine=engine)
    cfg = {"execution": {"tool_timeout_seconds": 0.05}}
    # ── 阶段 2 扰动：两次调用两种命 ──
    fast = _coro_tool("e2e-fast", 0.2)
    orch.register("e2e-fast", fast, risk="write")
    out1 = await orch.execute_tool("e2e-fast", "x", cfg)
    cancelled: list[str] = []
    slow = _coro_tool("e2e-slow", 30, cancelled=cancelled)
    orch.register("e2e-slow", slow, risk="write")
    out2 = await orch.execute_tool("e2e-slow", "x", cfg)
    # ── 阶段 3 断言 ──
    assert out1 == "e2e-fast-done"                                   # 第一次延长成功执行
    assert collect[0]["action"] == "continue" and collect[0]["extension_index"] == 1
    assert out2.startswith("[error: tool 'e2e-slow' timed out after 0.05s]")  # 第二次现状回喂
    assert "The tool did not return a result." in out2
    assert cancelled == ["e2e-slow"]                                 # 交叉①：C7 取消语义
    # 交叉②：scope 粒度是 call_id（§1.4 钉死）——第二把 call 是全新 scope，
    # 上一把 call 的 continue 不会把它的序号抬到 2（事件级可查，不依赖内部键）
    assert collect[1]["action"] == "stop" and collect[1]["extension_index"] == 0
    echo = _coro_tool("e2e-echo", 0.0)
    orch.register("e2e-echo", echo, risk="write")
    assert await orch.execute_tool("e2e-echo", "x", cfg) == "e2e-echo-done"  # turn 不死
