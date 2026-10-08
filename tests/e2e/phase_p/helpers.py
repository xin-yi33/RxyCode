"""Phase P whole-product E2E shared builders."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ART_DIR = Path(__file__).parent / ".artifacts"

EVENT_FIELDS = {
    "method", "session_id", "run_id", "event_id", "seq", "timestamp",
    "trigger_point", "action", "extend_seconds", "note", "confidence",
    "extension_index", "elapsed_seconds", "fail_closed", "decision_model", "cost",
}


def dump_artifact(nodeid: str, **payload: object) -> Path:
    dest = ART_DIR / nodeid.replace("::", "_").replace("/", "_")
    dest.mkdir(parents=True, exist_ok=True)
    for name, value in payload.items():
        p = dest / name
        if isinstance(value, (dict, list)):
            p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            p.write_text(str(value), encoding="utf-8")
    return dest


def evidence_dict(**over):
    base = dict(
        trigger_point="graph_task_max_time", session_id="sess_e2e", run_id="run_e2e",
        subject_id="task_e2e", task_hint="e2e", elapsed_seconds=7200.0, budget_seconds=7200.0,
        extension_index=0, progress="", last_error="",
    )
    base.update(over)
    return base


def policy_dict(**over):
    base = {
        "enabled": True, "max_extensions_per_point": 2, "extension_growth": 2,
        "decision_timeout_seconds": 2.0, "decision_model": None, "fail_closed": True,
        "absolute_cap_seconds": {
            "graph_task_max_time": 21600.0, "pipeline_soft_budget": 10800.0,
            "watchdog_stall": 1800.0, "tool_timeout": 7200.0,
        },
    }
    base.update(over)
    return base


class ScriptedDecisionLLM:
    """按序吐决策回复的 stub LLM（唯一允许 mock 的部件）。"""
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    async def ainvoke(self, prompt, **kw):
        self.calls += 1
        item = self._replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, dict) and "hang_seconds" in item:
            import asyncio

            await asyncio.sleep(item["hang_seconds"])
        text = item if isinstance(item, str) else json.dumps(item)

        class _R:
            content = text
        return _R()


def cont(extend, note="继续", conf=0.8):
    return json.dumps({"action": "continue", "extend_seconds": extend,
                       "note": note, "confidence": conf})


def stop(note="收工", conf=0.95):
    return json.dumps({"action": "stop", "extend_seconds": 0,
                       "note": note, "confidence": conf})


def assert_event_fields(ev: dict, **expect):
    assert set(ev) == EVENT_FIELDS, f"event 字段集合漂移: {set(ev) ^ EVENT_FIELDS}"
    assert ev["method"] == "event/timeout_decision"
    for k, v in expect.items():
        assert ev[k] == v, f"{k}: got {ev[k]!r} want {v!r}"
