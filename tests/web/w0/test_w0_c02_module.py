"""WEB-W0-C02 integration: a verdict must trace into a real ADR."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan_c02m", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w0_c02_integration():
    """A reviewer can follow a verdict to an ADR and read its limit and version."""
    traced = _scanner().trace_verdict(PLAN, "linux-sandbox")
    assert traced["limit"]
    assert traced["version"]
    adr_text = (PLAN / traced["adr"]).read_text(encoding="utf-8")
    assert traced["version"] in adr_text
    assert traced["limit"] in adr_text
