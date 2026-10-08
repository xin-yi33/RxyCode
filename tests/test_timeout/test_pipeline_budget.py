# tests/test_timeout/test_pipeline_budget.py（文件头）
"""layer=unit P4"""
from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, build_timeout_notice


class _StubEngine:
    def __init__(self, resp):
        from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionResponse
        self._resp = TimeoutDecisionResponse(**resp)
        self.calls = []
        self._grant = None

    async def decide(self, evidence):
        from RxyCode.RxyCode1_1_0.core.timeout_decision import Grant
        self.calls.append(evidence.model_dump())
        if self._resp.action in ("continue", "steer"):
            self._grant = Grant(granted_seconds=self._resp.extend_seconds,
                                new_budget=evidence.budget_seconds + self._resp.extend_seconds)
        return self._resp

    def last_grant(self, scope):
        return self._grant

def test_u_p4_01_timeout_notice_carries_decision_note_and_stays_compatible():
    """layer=unit U-P4-01 stop：build_timeout_notice 带决策 note；两参调用逐字节现状"""
    plain = build_timeout_notice(120.0)
    assert plain.startswith("[Build paused at ~120s]")
    assert "[timeout decision]" not in plain                      # 现状调用不受影响（budget_reached 兼容）
    with_note = build_timeout_notice(120.0, decision_note="无成效，收工")
    assert with_note == plain + "\n[timeout decision] 无成效，收工"


async def test_u_p4_02_continue_raises_soft_budget_and_survives():
    """layer=unit U-P4-02 continue → soft_budget 增加且 graph_task 存活"""
    agent = AgentV2.__new__(AgentV2)                              # 薄接缝只摸三属性
    agent._timeout_engine = _StubEngine(
        {"action": "continue", "extend_seconds": 600.0, "note": "继续", "confidence": 0.9})
    agent._last_timeout_note = None
    fake = asyncio.create_task(asyncio.sleep(30))
    try:
        stop_now, new_budget = await agent._pipeline_budget_branch(fake, soft_budget=3600.0, elapsed=3601.0)
        assert stop_now is False
        assert new_budget == 4200.0
        assert not fake.done()                                    # 不得被 cancel
        assert agent._timeout_engine.calls[0]["trigger_point"] == "pipeline_soft_budget"
    finally:
        fake.cancel()


async def test_u_p4_03_stop_keeps_status_quo_and_records_note():
    """layer=unit U-P4-03 stop → (True, 原预算)；note 存到 _last_timeout_note 给 notice 用"""
    agent = AgentV2.__new__(AgentV2)
    agent._timeout_engine = _StubEngine(
        {"action": "stop", "extend_seconds": 0.0, "note": "预算烧尽", "confidence": 0.95})
    agent._last_timeout_note = None
    fake = asyncio.create_task(asyncio.sleep(30))
    stop_now, new_budget = await agent._pipeline_budget_branch(fake, soft_budget=3600.0, elapsed=3601.0)
    assert stop_now is True and new_budget == 3600.0
    assert agent._last_timeout_note == "预算烧尽"
    fake.cancel()                                                # stop 后清理由调用方负责（现状 :8119-8123）

async def test_mo_p4_01_disabled_branch_is_byte_identical_status_quo():
    """layer=module MO-P4-01 enabled=false → (True, soft_budget)：调用方 8114-8132 现状路径"""
    agent = AgentV2.__new__(AgentV2)
    agent._timeout_engine = None
    fake = asyncio.create_task(asyncio.sleep(30))
    stop_now, new_budget = await agent._pipeline_budget_branch(fake, soft_budget=3600.0, elapsed=3601.0)
    assert (stop_now, new_budget) == (True, 3600.0)
    assert build_timeout_notice(3601.0).startswith("[Build paused at ~3601s]")
    fake.cancel()
