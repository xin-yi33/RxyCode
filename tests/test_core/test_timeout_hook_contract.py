# tests/test_core/test_timeout_hook_contract.py
"""layer=unit P9"""
from __future__ import annotations

import asyncio
import time

from RxyCode.RxyCode1_1_0.core.hooks import HookRegistry
from RxyCode.RxyCode1_1_0.core.lifecycle_contract import HOOK_EVENT_CONTRACT


def test_u_p9_01_contract_matches_lifecycle_enum():
    """layer=unit U-P9-01 最小事件集契约：序列钉死、phase 全合法、PreTimeoutDecision 在册"""
    assert HOOK_EVENT_CONTRACT == (
        ("before", "tool"), ("after", "tool"),
        ("before", "compact"), ("after", "compact"),
        ("after", "stop"), ("after", "session_start"), ("after", "session_end"),
        ("before", "timeout_decision"),
    )
    from RxyCode.RxyCode1_1_0.core.hooks import HookPhase
    assert all(p in {ph.value for ph in HookPhase} for p, _s in HOOK_EVENT_CONTRACT)


async def test_u_p9_02_pre_timeout_decision_fires_before_llm():
    """layer=unit U-P9-02 PreTimeoutDecision 严格先于决策 LLM 调用"""
    from RxyCode.RxyCode1_1_0.core.timeout_decision import DecisionPolicy, ExtensionLedger, TimeoutDecisionEngine
    from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence

    order: list[str] = []
    hooks = HookRegistry(default_timeout_seconds=1.0)

    def _pre(ctx): order.append(f"hook:{ctx.phase.value}/{ctx.subject}")

    hooks.register("before", _pre, name="spy_pre")

    class _LLM:
        async def ainvoke(self, prompt, **kw):
            order.append("llm")

            class _R: content = '{"action": "stop", "extend_seconds": 0, "note": "d", "confidence": 0.5}'
            return _R()

    engine = TimeoutDecisionEngine(_LLM(), DecisionPolicy({
        "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
        "decision_timeout_seconds": 5.0, "decision_model": None, "fail_closed": True,
        "absolute_cap_seconds": {"graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
                                 "watchdog_stall": 1800.0, "tool_timeout": 7200.0}}),
        ledger=ExtensionLedger(), hooks=hooks)
    r = await engine.decide(TimeoutEvidence(
        trigger_point="tool_timeout", session_id="s", run_id="r", subject_id="call_t",
        task_hint="t",
        elapsed_seconds=1.0, budget_seconds=2.0, extension_index=0, progress="", last_error=""))
    assert r.action == "stop"
    assert order == ["hook:before/timeout_decision", "llm"]       # 决策前触发，序钉死


async def test_mo_p9_01_hook_timeout_skip_semantics_unchanged():
    """layer=module MO-P9-01 超 5s 语义：慢 hook TIMED_OUT 跳过、不阻断决策、不吞后 hook"""
    from RxyCode.RxyCode1_1_0.core.timeout_decision import DecisionPolicy, ExtensionLedger, TimeoutDecisionEngine
    from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence

    hooks = HookRegistry(default_timeout_seconds=0.05)
    ran: list[str] = []

    async def _slow(ctx):
        await asyncio.sleep(5)

    def _after_slow(ctx):
        ran.append(ctx.subject)

    hooks.register("before", _slow, name="slow", timeout_seconds=0.05)
    hooks.register("before", _after_slow, name="tail")

    class _LLM:
        async def ainvoke(self, prompt, **kw):
            class _R: content = '{"action": "stop", "extend_seconds": 0, "note": "d", "confidence": 0.5}'
            return _R()

    engine = TimeoutDecisionEngine(_LLM(), DecisionPolicy({
        "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
        "decision_timeout_seconds": 5.0, "decision_model": None, "fail_closed": True,
        "absolute_cap_seconds": {"graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
                                 "watchdog_stall": 1800.0, "tool_timeout": 7200.0}}),
        ledger=ExtensionLedger(), hooks=hooks)
    started = time.monotonic()
    r = await engine.decide(TimeoutEvidence(
        trigger_point="tool_timeout", session_id="s", run_id="r", subject_id="call_t",
        task_hint="t",
        elapsed_seconds=1.0, budget_seconds=2.0, extension_index=0, progress="", last_error=""))
    assert r.action == "stop"
    assert time.monotonic() - started < 2.0                      # 5s 慢 hook 被跳过
    assert ran == ["timeout_decision"]                           # 后续 hook 不被吞
    audits = engine.drain_hook_audits()
    assert any(a["hook_name"] == "slow" and a["status"] == "timed_out" for a in audits)
    assert all(a["status"] == "succeeded" for a in audits if a["hook_name"] == "tail")
