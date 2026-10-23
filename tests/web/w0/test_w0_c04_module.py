"""WEB-W0-C04. A new command that reuses an old protocol name stays blocked."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan_c04m", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w0_c04_integration():
    """session/prompt already belongs to the old JSON-RPC protocol."""
    ruling = _scanner().protocol_name_ruling(REPO, PLAN, "session/prompt")
    assert ruling["ruling"] == "BLOCKED"
    assert ruling["conflict_id"] == "CW04"
    assert ruling["old_method"] == "session/prompt"
    kind_only = _scanner().protocol_name_ruling(REPO, PLAN, "needs_input")
    assert kind_only["ruling"] == "CLEAR"
    assert kind_only["old_method"] == ""
