"""layer=e2e E-P-E2E-07"""
from __future__ import annotations

import asyncio
import time

import pytest

from RxyCode.RxyCode1_1_0.core import graph as graph_mod
from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from tests.e2e.phase_p import helpers

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


async def test_e2e_p_07_interrupt_voids_pending_decision(monkeypatch):
    """layer=e2e E-P-E2E-07 interrupt 优先：pending 决策作废、事件序正确、按现状收尾"""
    # ── 阶段 1 setup：决策 LLM 挂死（pending）──
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([{"hang_seconds": 60}]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=td.ExtensionLedger(), sink=(collect := []))
    monkeypatch.setattr(graph_mod, "_timeout_engine", lambda cfg: engine)
    tracker = _Tracker()
    started = time.monotonic()
    # ── 阶段 2 扰动：max_time 到点触发 pending 决策 → 0.3s 后 interrupt ──
    watch = asyncio.create_task(graph_mod.run_task_watchdog(
        tracker, check_interval=0.05, stall_timeout=0.0, max_timeout=0.2,
        cfg={"timeout_decision": {"enabled": True}},
        evidence_factory=lambda: helpers.evidence_dict(elapsed_seconds=0.2, budget_seconds=0.2)))
    await asyncio.sleep(0.3)                                     # 决策已 pending
    engine.interrupt()                                           # 用户 interrupt
    out = await asyncio.wait_for(watch, timeout=3.0)
    # ── 阶段 3 断言 ──
    assert out == "max_time"                                     # 现状收尾语义
    assert time.monotonic() - started < 2.0                      # interrupt 立刻生效，不等 hang 60s
    assert collect[0]["fail_closed"] is True and collect[0]["action"] == "stop"
    assert collect[0]["note"].startswith("[fail-closed] interrupted")
    kinds = [k for k, _t in engine.trajectory]
    assert kinds.index("interrupt") < kinds.index("decision.fail_closed")  # 事件序钉死
    assert engine.trajectory[-1][0] == "decision.fail_closed"    # 作废即终态，不再续跑
    await asyncio.sleep(0)
    assert engine.pending_decisions == 0                         # 挂死协程被收殓
