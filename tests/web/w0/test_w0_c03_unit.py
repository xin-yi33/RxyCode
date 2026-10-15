"""WEB-W0-C03. Session reuse is the shipped core.session path."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan_c03", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w0_c03_contract(tmp_path: Path):
    """Same session id and workspace keeps agent_runtimes and replaces emit."""
    from core.session import reuse_or_create_session

    first_emit: list[str] = []
    second_emit: list[str] = []
    first = reuse_or_create_session(
        None,
        session_id="ses-c03",
        workspace_root=tmp_path,
        emit=first_emit.append,
    )
    marker = object()
    first.agent_runtimes["architect"] = marker
    second = reuse_or_create_session(
        first,
        session_id="ses-c03",
        workspace_root=tmp_path,
        emit=second_emit.append,
    )
    assert second is first
    assert second.agent_runtimes["architect"] is marker
    second.emit("next")
    assert second_emit == ["next"]
    assert first_emit == []


def test_w0_c03_negative(tmp_path: Path):
    """A missing baseline test file is BLOCKED, not a skipped pass."""
    missing = _scanner().baseline_file_status(tmp_path / "missing_baseline_test.py")
    assert missing == "BLOCKED"
    present = _scanner().baseline_file_status(
        REPO / "tests" / "test_cache" / "test_s1_s2_split.py"
    )
    assert present == "PRESENT"
