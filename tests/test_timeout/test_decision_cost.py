"""layer=module P7"""
from __future__ import annotations

from RxyCode.RxyCode1_1_0.core import timeout_decision as td
from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutEvidence


class _ReplyLLM:
    def __init__(self, text): self._text = text

    async def ainvoke(self, prompt, **kw):
        text = self._text

        class _R: content = text
        return _R()


async def test_mo_p7_01_cost_recorded_into_session_once_per_decision(monkeypatch):
    """layer=module MO-P7-01 每次决策恰一次 record_decision_cost；cost 与事件同值；total_cost 一致"""
    charged: list[tuple[str, float]] = []
    monkeypatch.setattr(td, "record_decision_cost", lambda sid, c: charged.append((sid, c)))
    engine = td.from_config(
        {"timeout_decision": {
            "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
            "decision_timeout_seconds": 5.0, "decision_model": None, "fail_closed": True,
            "absolute_cap_seconds": {"graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
                                     "watchdog_stall": 1800.0, "tool_timeout": 7200.0}}},
        base_llm=_ReplyLLM('{"action": "continue", "extend_seconds": 300, "note": "n", "confidence": 0.5}'),
    )
    ev = TimeoutEvidence(trigger_point="tool_timeout", session_id="sess_c", run_id="r",
                         subject_id="call_bash_1",
                         task_hint="bash", elapsed_seconds=1800.0, budget_seconds=1800.0,
                         extension_index=0, progress="", last_error="")
    await engine.decide(ev)
    events = engine.drain_events()
    assert len(events) == 1 and events[0]["cost"] >= 0.0
    assert events[0]["decision_model"] != ""
    assert charged == [("sess_c", events[0]["cost"])]            # 恰好一次、与事件同值
    assert engine.total_cost == events[0]["cost"]
