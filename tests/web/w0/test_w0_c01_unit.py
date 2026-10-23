"""WEB-W0-C01 unit contracts. These call the shipped plan scanner."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAN = REPO / "docs" / "plans" / "opus5-plan" / "rxycode -web"
DEV_ORDER = REPO / "docs" / "plans" / "opus5-plan" / "rxycode" / "architecture" / "DEV-ORDER.md"


def _scanner():
    path = PLAN / "scripts" / "check_plan.py"
    spec = importlib.util.spec_from_file_location("rxycode_web_check_plan", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w0_c01_contract():
    """Given the Web plan exists, scanning the index finds unique cards and a link for every file."""
    report = _scanner().scan_contract(PLAN)
    assert report["card_count"] == 48
    assert report["duplicate_cards"] == []
    assert report["unindexed_files"] == []


def test_w0_c01_negative(tmp_path: Path):
    """Given the old DEV-ORDER is missing, the scan is BLOCKED_PREREQUISITE."""
    missing = tmp_path / "DEV-ORDER.md"
    status = _scanner().authority_status(missing)
    assert status == "BLOCKED_PREREQUISITE"
    assert _scanner().authority_status(DEV_ORDER) == "OK"
