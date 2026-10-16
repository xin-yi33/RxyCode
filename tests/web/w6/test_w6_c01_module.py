"""WEB-W6-C01. A remote target with a missing capability explains why."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
_CORE = REPO / "packages" / "rxycode-core" / "src"
for _entry in (REPO, _CORE):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))


class Tool:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


def test_w6_c01_integration() -> None:
    """Remote selection says which capability the target did not declare."""
    from execution.tool_orchestrator import ToolOrchestrator

    orchestrator = ToolOrchestrator()
    orchestrator.register("read", Tool("read", "read a file"))
    orchestrator.register("click", Tool("click", "click a desktop element"))
    selected = orchestrator.select_tools(
        [],
        target="remote",
        capabilities=["fs.read"],
    )
    names = {tool.name for tool in selected}
    assert "read" in names
    assert "click" not in names
    report = orchestrator.selection_report()
    click = next(item for item in report if item["tool_name"] == "click")
    assert click["status"] == "unavailable"
    reason = click["reason"].lower()
    assert "desktop.input" in reason
    assert "remote" in reason
    assert "not declared" in reason or "unavailable" in reason
