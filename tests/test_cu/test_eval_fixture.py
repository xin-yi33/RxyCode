"""Cheap eval predicates for the computer-use tool schema fixture."""

from __future__ import annotations

import json
from pathlib import Path

from RxyCode.RxyCode1_1_0.core.cu.spec import CU_TOOL_ORDER

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "evals"
    / "baselines"
    / "computer-use-tools.json"
)


def test_eval_fixture_lists_required_ocu_and_browser_names():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = set(payload["required_tools_when_enabled"])
    assert required.issubset(set(CU_TOOL_ORDER))
    assert "computer_use_1" not in CU_TOOL_ORDER
    assert "cli_run" not in CU_TOOL_ORDER
