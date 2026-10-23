"""WEB-W0-C04. Requirement rows and the W1 gate come from the plan files."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan_c04", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w0_c04_contract():
    """Each of the seven requirements has an owner, a card, and a test id."""
    rows = _scanner().trace_requirements(PLAN)
    wanted = {f"WEB-RQ0{index}" for index in range(1, 8)}
    found = {row["id"] for row in rows}
    assert wanted <= found
    for row in rows:
        if row["id"] not in wanted:
            continue
        assert row["owner"]
        assert row["card"].startswith("WEB-W")
        assert row["test_id"]
        assert row["test_defined"] is True


def test_w0_c04_negative():
    """Unresolved P0 conflicts reject the move to W1."""
    conflicts = _scanner().load_conflicts(PLAN)
    assert any(
        item["severity"] == "P0" and item["status"] == "OPEN" for item in conflicts
    )
    gate = _scanner().w1_gate
    assert gate(conflicts) == "REJECTED"
    assert gate([{"severity": "P0", "status": "NEEDS_VERIFICATION"}]) == "REJECTED"
    assert gate([{"severity": "P0", "status": "CONFIRMED"}]) == "REJECTED"
    assert gate([{"severity": "P0", "status": "RESOLVED"}]) == "ALLOWED"
    assert gate([{"severity": "P0", "status": "FALSE_POSITIVE"}]) == "ALLOWED"
