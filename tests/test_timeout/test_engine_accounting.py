"""layer=module P2"""
from __future__ import annotations

from tests.test_timeout.test_decision_engine import _StubLLM, _evidence

async def test_mo_p2_01_decision_call_accounted_via_usage_tracking(monkeypatch, tmp_path):
    """layer=module MO-P2-01 决策调用走 UsageTrackingLLM 计账；enabled=false 引擎不介入"""
    from RxyCode.RxyCode1_1_0.core import timeout_decision as td
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    wrapped = []
    real = UsageTrackingLLM

    def _spy(inner, *a, **k):
        obj = real(inner, *a, **k)
        wrapped.append(obj)
        return obj

    monkeypatch.setattr(td, "UsageTrackingLLM", _spy)
    engine = td.from_config(
        {"timeout_decision": {
            "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
            "decision_timeout_seconds": 5.0, "decision_model": None, "fail_closed": True,
            "absolute_cap_seconds": {"graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
                                     "watchdog_stall": 1800.0, "tool_timeout": 7200.0}}},
        base_llm=_StubLLM(replies=['{"action": "stop", "extend_seconds": 0, "note": "d", "confidence": 0.5}']),
    )
    assert len(wrapped) == 1 and isinstance(wrapped[0], real)   # 决策 LLM 必经计账包装
    r = await engine.decide(_evidence())
    assert r.action == "stop"

    off = td.from_config({"timeout_decision": {"enabled": False}}, base_llm=_StubLLM())
    assert off is None                                          # enabled=false：无引擎，走逐字节现状路径
