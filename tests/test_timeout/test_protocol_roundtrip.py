"""layer=module P1"""
from __future__ import annotations

import json

from tests.test_timeout.test_protocol_models import _evidence


def test_mo_p1_01_evidence_prompt_event_roundtrip():
    """layer=module MO-P1-01 evidence→prompt→parse→event 同构往返（跨 protocol + core）"""
    from RxyCode.RxyCode1_1_0.core.timeout_decision import (
        build_decision_prompt, event_from_decision, parse_decision_response,
    )

    ev = _evidence(trigger_point="pipeline_soft_budget", elapsed_seconds=3700.0, budget_seconds=3600.0)
    prompt = build_decision_prompt(ev)
    assert '"trigger_point": "pipeline_soft_budget"' in prompt
    assert "JSON" in prompt  # 输出纪律
    resp = parse_decision_response('{"action": "continue", "extend_seconds": 600, "note": "稳步", "confidence": 0.6}')
    out = json.loads(event_from_decision(resp, ev, extension_index=1, fail_closed=False,
                                         decision_model="mini-x", cost=0.001).model_dump_json())
    assert out["trigger_point"] == "pipeline_soft_budget" and out["action"] == "continue"
    assert out["extension_index"] == 1 and out["elapsed_seconds"] == 3700.0
