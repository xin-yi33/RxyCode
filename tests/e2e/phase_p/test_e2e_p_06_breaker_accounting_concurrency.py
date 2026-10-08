"""layer=e2e E-P-E2E-06"""
from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM, _OUTER_BREAKER_HELD
from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence
from tests.e2e.phase_p import helpers

pytestmark = pytest.mark.e2e


def _ev(tp, subject):
    return TimeoutEvidence(**helpers.evidence_dict(trigger_point=tp, subject_id=subject))


async def test_e2e_p_06_accounting_once_and_concurrent_isolation(monkeypatch):
    """layer=e2e E-P-E2E-06 决策计账不双重计数；并发两触发点互不串扰（scope/ContextVar 隔离）"""
    # ── 阶段 1 setup：spy 真实 UsageTrackingLLM 包装 ──
    calls = {"wraps": 0, "ainvokes": 0}
    real = UsageTrackingLLM

    class _SpyLLM:
        def __init__(self, inner):
            calls["wraps"] += 1
            self._inner = real(inner)

        async def ainvoke(self, prompt, **kw):
            calls["ainvokes"] += 1
            return await self._inner.ainvoke(prompt, **kw)

    monkeypatch.setattr(td, "UsageTrackingLLM", _SpyLLM)
    shared_ledger = td.ExtensionLedger()
    events: list[dict] = []
    engine = td.from_config(
        {"timeout_decision": helpers.policy_dict()},
        base_llm=helpers.ScriptedDecisionLLM([helpers.cont(600, "a"), helpers.cont(300, "b")]),
        ledger=shared_ledger, sink=events)
    # ── 阶段 2 扰动：外层熔断持有中，并发两触发点决策 ──
    token = _OUTER_BREAKER_HELD.set(True)                        # ainvoke 外层持有
    try:
        r1, r2 = await asyncio.gather(
            engine.decide(_ev("graph_task_max_time", "graph_task_1")),
            engine.decide(_ev("tool_timeout", "call_1")))
        assert _OUTER_BREAKER_HELD.get() is True                 # 决策不覆写外层 ContextVar
    finally:
        _OUTER_BREAKER_HELD.reset(token)
    # ── 阶段 3 断言 ──
    assert calls["wraps"] == 1                                   # 决策 LLM 恰包装一次
    assert calls["ainvokes"] == 2                                # 两次决策=两次逻辑调用（不双重计数）
    assert (r1.action, r2.action) == ("continue", "continue")
    by_point = {e["trigger_point"]: e for e in events}
    assert set(by_point) == {"graph_task_max_time", "tool_timeout"}
    assert by_point["graph_task_max_time"]["extension_index"] == 1   # scope 独立计数
    assert by_point["tool_timeout"]["extension_index"] == 1
    assert shared_ledger.count(("sess_e2e", "graph_task_1")) == 1
    assert shared_ledger.count(("sess_e2e", "call_1")) == 1
    assert _OUTER_BREAKER_HELD.get() is False                    # reset 后环境干净（不泄漏到下个 turn）
