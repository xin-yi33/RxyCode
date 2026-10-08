"""layer=e2e E-P-E2E-01"""
from __future__ import annotations

import asyncio
import time

import pytest

from RxyCode.RxyCode1_1_0.core import graph as graph_mod
from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from tests.e2e.phase_p import helpers
from tests.e2e.phase_p.helpers import assert_event_fields

pytestmark = pytest.mark.e2e


class _Tracker:
    def __init__(self):
        self.last_activity = time.monotonic()
        self.error_count = 0
        self.last_error = ""
        self.chunks_received = 0
        self.guidance_notes = []

    def seconds_since_activity(self):
        return time.monotonic() - self.last_activity


async def test_e2e_p_01_continue_twice_then_finish(monkeypatch):
    """layer=e2e E-P-E2E-01 决策 continue×2 后任务正常完成"""
    # ── 阶段 1 setup：真实 Policy/Ledger/Engine，仅决策 LLM 是 stub ──
    ledger = td.ExtensionLedger()
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([helpers.cont(0.3, "k1"), helpers.cont(0.3, "k2")]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=ledger,
        sink=(_collect := []),
    )
    monkeypatch.setattr(graph_mod, "_timeout_engine", lambda cfg: engine)
    tracker = _Tracker()

    async def _executor_side():
        """被监护任务：1.15s 后正常完成（期间两次越过 0.3s 死线都被决策救回）。"""
        for _ in range(23):
            await asyncio.sleep(0.05)
            tracker.last_activity = time.monotonic()   # 活心跳：非 stall
        return "task-done"

    # ── 阶段 2 扰动：max_time=0.3s 两次到点 ──
    exec_task = asyncio.create_task(_executor_side())
    watch_task = asyncio.create_task(graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.3,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: helpers.evidence_dict(elapsed_seconds=0.3, budget_seconds=0.3),
    ))
    # ── 阶段 3 断言：事件、编号、证据、结果 ──
    result = await asyncio.wait_for(exec_task, timeout=5.0)
    assert result == "task-done"                       # 任务结果正常
    watch_task.cancel()
    try:
        await watch_task
    except asyncio.CancelledError:
        pass
    assert engine.ledger is ledger                     # 交叉②：两次 granted 落进同一 ledger
    assert len(_collect) == 2                          # 恰两次决策事件
    assert_event_fields(_collect[0], trigger_point="graph_task_max_time", action="continue",
                       extension_index=1, extend_seconds=0.3, fail_closed=False)
    assert_event_fields(_collect[1], trigger_point="graph_task_max_time", action="continue",
                       extension_index=2, extend_seconds=0.6, fail_closed=False)  # growth=2
    assert ledger.count(("sess_e2e", "task_e2e")) == 2     # 交叉①：ledger（scope 键）
    assert ledger.total_extended(("sess_e2e", "task_e2e")) == pytest.approx(0.9)
    g2 = engine.last_grant(("sess_e2e", "task_e2e"))       # 预算链只走 Grant.new_budget
    assert (g2.granted_seconds, g2.new_budget) == (pytest.approx(0.6), pytest.approx(0.6 + 0.6))
