"""layer=unit P1"""
from __future__ import annotations

import json

import pytest

from RxyCode.RxyCode1_1_0.protocol.timeout_decision import (
    TimeoutDecisionEvent,
    TimeoutDecisionResponse,
    TimeoutEvidence,
)
from RxyCode.RxyCode1_1_0.core.timeout_decision import parse_decision_response


def _evidence(**over):
    base = dict(
        trigger_point="graph_task_max_time",
        session_id="sess_1",
        run_id="run_1",
        subject_id="task_login",
        task_hint="build login page",
        elapsed_seconds=7200.0,
        budget_seconds=7200.0,
        extension_index=0,
        progress="[1/3] login form",
        last_error="",
    )
    base.update(over)
    return TimeoutEvidence(**base)


def test_u_p1_01_response_validation_rejects_bad_payloads():
    """layer=unit U-P1-01 缺字段/非法 action/extend<0 一律拒绝"""
    with pytest.raises(Exception, match="action"):
        TimeoutDecisionResponse(extend_seconds=60.0, note="n", confidence=0.5)
    with pytest.raises(Exception, match="action"):
        TimeoutDecisionResponse(action="extend", extend_seconds=60.0, note="n", confidence=0.5)
    with pytest.raises(Exception, match="extend_seconds"):
        TimeoutDecisionResponse(action="continue", extend_seconds=-1.0, note="n", confidence=0.5)
    with pytest.raises(Exception, match="confidence"):
        TimeoutDecisionResponse(action="stop", extend_seconds=0.0, note="n", confidence=1.5)
    ok = TimeoutDecisionResponse(action="steer", extend_seconds=120.0, note="聚焦单测", confidence=0.8)
    assert ok.action == "steer" and ok.extend_seconds == 120.0 and ok.confidence == 0.8
    with pytest.raises(Exception, match="subject_id"):           # evidence 缺 scope 载体拒绝
        TimeoutEvidence(trigger_point="tool_timeout", session_id="s", run_id="r",
                        task_hint="t", elapsed_seconds=1.0, budget_seconds=2.0,
                        extension_index=0, progress="", last_error="")


def test_u_p1_02_parse_tolerates_markdown_fence_and_stays_json_only():
    """layer=unit U-P1-02 JSON-only 解析；容忍 ```json fence；非 JSON 拒绝"""
    fenced = "```json\n{\"action\": \"continue\", \"extend_seconds\": 300, \"note\": \"alive\", \"confidence\": 0.9}\n```"
    r = parse_decision_response(fenced)
    assert r.action == "continue" and r.extend_seconds == 300.0 and r.note == "alive" and r.confidence == 0.9
    bare = json.dumps({"action": "stop", "extend_seconds": 0, "note": "done", "confidence": 0.95})
    assert parse_decision_response(bare).action == "stop"
    with pytest.raises(ValueError, match="JSON"):
        parse_decision_response("continue for 300 seconds, looks alive")
    with pytest.raises(ValueError, match="JSON"):
        parse_decision_response("前言\n{\"action\": \"stop\", \"extend_seconds\": 0, \"note\": \"d\", \"confidence\": 0.5}\n后记")


def test_u_p1_03_event_serialization_full_fieldset():
    """layer=unit U-P1-03 event/timeout_decision 全字段序列化，缺一字段即红"""
    ev = TimeoutDecisionEvent(
        session_id="sess_1", run_id="run_1", event_id="e1", seq=7, timestamp="2026-10-01T00:00:00Z",
        trigger_point="tool_timeout", action="continue", extend_seconds=600.0,
        note="granted", confidence=0.77, extension_index=1, elapsed_seconds=1800.0,
        fail_closed=False, decision_model="mini-x", cost=0.0023,
    )
    d = json.loads(ev.model_dump_json())
    assert d["method"] == "event/timeout_decision"
    assert set(d) == {
        "method", "session_id", "run_id", "event_id", "seq", "timestamp",
        "trigger_point", "action", "extend_seconds", "note", "confidence",
        "extension_index", "elapsed_seconds", "fail_closed", "decision_model", "cost",
    }
    assert d["trigger_point"] == "tool_timeout" and d["extension_index"] == 1
    assert d["fail_closed"] is False and d["cost"] == 0.0023
