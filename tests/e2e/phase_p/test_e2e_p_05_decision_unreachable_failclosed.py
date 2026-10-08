"""layer=e2e E-P-E2E-05"""
from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from tests.e2e.phase_p import helpers
from tests.e2e.phase_p.helpers import assert_event_fields

pytestmark = pytest.mark.e2e


def _coro_tool(name, seconds, cancelled):
    tool = MagicMock()
    tool.name = name

    async def ainvoke(args):
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            cancelled.append(name)
            raise
        return f"{name}-done"

    tool.ainvoke = ainvoke
    tool.coroutine = ainvoke
    return tool


async def test_e2e_p_05_fail_closed_when_decision_unreachable():
    """layer=e2e E-P-E2E-05 决策 LLM 不可达：按现状取消、event fail_closed=true、无泄漏协程"""
    # ── 阶段 1 setup：真实 engine + 不可达决策 LLM（ConnectionError）──
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([ConnectionError("no route to decision model")]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=td.ExtensionLedger(), sink=(collect := []))
    orch = ToolOrchestrator(timeout_engine=engine)
    cancelled: list[str] = []
    orch.register("e2e-ghost", _coro_tool("e2e-ghost", 30, cancelled), risk="write")
    tasks_before = set(asyncio.all_tasks())
    threads_before = len(threading.enumerate())
    # ── 阶段 2 扰动：工具 0.05s 到点，决策环本身炸 ──
    out = await orch.execute_tool("e2e-ghost", "x", {"execution": {"tool_timeout_seconds": 0.05}})
    # ── 阶段 3 断言 ──
    assert out.startswith("[error: tool 'e2e-ghost' timed out after 0.05s]")  # 按现状取消
    assert cancelled == ["e2e-ghost"]                            # 交叉①：C7 语义
    assert len(collect) == 1
    assert_event_fields(collect[0], trigger_point="tool_timeout", action="stop",
                        extend_seconds=0.0, fail_closed=True, extension_index=0, confidence=0.0)
    assert collect[0]["note"].startswith("[fail-closed] ")
    await asyncio.sleep(0)
    assert set(asyncio.all_tasks()) - tasks_before == set()      # 交叉②：无泄漏协程
    assert len(threading.enumerate()) == threads_before
