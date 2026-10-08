"""layer=e2e E-P-E2E-02"""
from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2, build_timeout_notice
from RxyCode.RxyCode1_1_0.log.logger import bind_run_id, reset_run_id
from tests.e2e.phase_p import helpers
from tests.e2e.phase_p.helpers import assert_event_fields

pytestmark = pytest.mark.e2e


async def test_e2e_p_02_exhausted_policy_forces_stop():
    """layer=e2e E-P-E2E-02 continue×2 后第三次到点 policy 强制 stop"""
    # ── 阶段 1 setup ──
    ledger = td.ExtensionLedger()
    engine = td.TimeoutDecisionEngine(
        helpers.ScriptedDecisionLLM([helpers.cont(300, "k1"), helpers.cont(300, "k2")]),
        td.DecisionPolicy(helpers.policy_dict()),
        ledger=ledger, sink=(collect := []),
    )
    agent = AgentV2.__new__(AgentV2)
    agent._timeout_engine = engine
    agent._last_timeout_note = None
    # Scope is the live session and run id. The assert names this pair;
    # the branch does not invent it.
    agent._session_id = "sess_e2e"
    run_token = bind_run_id("task_e2e")
    budget = 3600.0
    # ── 阶段 2 扰动：三次到点 ──
    try:
        for _ in range(2):
            fake = asyncio.create_task(asyncio.sleep(60))
            stop_now, budget = await agent._pipeline_budget_branch(fake, soft_budget=budget, elapsed=3700.0)
            assert stop_now is False
            fake.cancel()
        assert budget == 3600.0 + 300.0 + 600.0            # growth=2 封顶数学
        t3 = asyncio.create_task(asyncio.sleep(60))
        final_stop, final_budget = await agent._pipeline_budget_branch(t3, soft_budget=budget, elapsed=4300.0)
        t3.cancel()                                                  # stop 后调用方按现状 :8119 取消
    finally:
        reset_run_id(run_token)
    # ── 阶段 3 断言 ──
    assert final_stop is True and final_budget == budget   # k=3 > max_extensions=2：不续
    assert agent._last_timeout_note.startswith("[policy] ")
    notice = build_timeout_notice(4300.0, decision_note=agent._last_timeout_note)
    assert notice.startswith("[Build paused at ~4300s]")       # 现状 banner 兼容
    assert "\n[timeout decision] [policy] " in notice            # notice 含决策 note
    assert len(collect) == 3                                     # 2 次 LLM + 1 次 policy 强制
    assert_event_fields(collect[2], action="stop", extension_index=2, fail_closed=False,
                        extend_seconds=0.0)
    scope = ("sess_e2e", "task_e2e")                             # _scope_of(evidence) 默认夹具
    assert ledger.count(scope) == 2                              # 交叉：ledger 终态正确（scope 键）
    assert ledger.total_extended(scope) == 900.0
    g = engine.last_grant(scope)
    assert (g.granted_seconds, g.new_budget) == (600.0, 4500.0)  # 3600→3900→4500（截断式）
