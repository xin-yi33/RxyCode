"""layer=unit P7"""
from __future__ import annotations

from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui
from RxyCode.RxyCode1_1_0.protocol.timeout_decision import TimeoutDecisionEvent


def _event(**over):
    base = dict(
        session_id="sess_7", run_id="run_7", event_id="e7", seq=3,
        timestamp="2026-10-01T08:00:00Z", trigger_point="pipeline_soft_budget",
        action="continue", extend_seconds=1200.0, note="k2", confidence=0.81,
        extension_index=2, elapsed_seconds=3600.0, fail_closed=False,
        decision_model="mini-x", cost=0.0017,
    )
    base.update(over)
    return TimeoutDecisionEvent(**base)


def test_u_p7_01_event_full_fields_reach_protocol_tui():
    """layer=unit U-P7-01 event/timeout_decision 全字段原样到达 ProtocolTui emit"""
    captured = []
    tui = ProtocolTui("sess_7", emit=captured.append, run_id="run_7")
    tui.write_timeout_decision(_event())
    assert len(captured) == 1
    ev = captured[0]
    assert isinstance(ev, TimeoutDecisionEvent)
    assert ev.method == "event/timeout_decision"
    assert ev.action == "continue" and ev.extend_seconds == 1200.0
    assert ev.extension_index == 2 and ev.fail_closed is False
    assert ev.decision_model == "mini-x" and ev.cost == 0.0017
