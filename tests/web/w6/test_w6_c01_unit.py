"""WEB-W6-C01. Cloud selection hides local desktop input. MCP hints cannot lower risk."""

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


def _orchestrator():
    from execution.tool_orchestrator import ToolOrchestrator

    orchestrator = ToolOrchestrator()
    orchestrator.register("read", Tool("read", "read a file"))
    orchestrator.register("click", Tool("click", "click a desktop element"))
    orchestrator.register("type_text", Tool("type_text", "type into the desktop"))
    orchestrator.register("bash", Tool("bash", "run a shell command"))
    return orchestrator


def test_w6_c01_contract() -> None:
    """A cloud target does not receive local desktop input tools."""
    from core.safety.policy import RiskLevel
    from core.subagents.permissions import PermissionPolicy
    from execution.tool_orchestrator import ToolOrchestrator
    from protocol.subagents import PermissionSpec
    from rxycode_core.tools.capability_catalog import inventory

    orchestrator = _orchestrator()
    selected = orchestrator.select_tools([], target="cloud", profile="full")
    names = {tool.name for tool in selected}
    assert "read" in names
    assert "click" not in names
    assert "type_text" not in names
    report = orchestrator.selection_report()
    click = next(item for item in report if item["tool_name"] == "click")
    assert click["status"] == "unavailable"
    assert "desktop" in click["reason"].lower()
    assert "input" in click["reason"].lower()

    rows = {row["tool_name"]: row for row in inventory(orchestrator.get_all().values())}
    for field in ("tool_name", "capability", "target", "risk", "timeout", "idempotent"):
        assert field in rows["click"]
        assert field in rows["read"]
    assert rows["click"]["capability"] == "desktop.input"
    assert rows["click"]["target"] == "local"
    assert rows["click"]["idempotent"] is False
    assert rows["read"]["capability"] == "fs.read"
    assert rows["read"]["idempotent"] is True
    assert rows["read"]["timeout"] == ToolOrchestrator._TOOL_STALL_SECONDS["read"]
    assert rows["click"]["timeout"] == ToolOrchestrator._DEFAULT_STALL_SECONDS
    assert rows["click"]["risk"] == RiskLevel.DANGER.name

    denied = orchestrator.select_tools(
        [],
        target="local",
        capabilities=["desktop.input", "fs.read"],
        permission=PermissionPolicy(permission=PermissionSpec()),
    )
    denied_names = {tool.name for tool in denied}
    assert "click" not in denied_names
    click_denied = next(
        item for item in orchestrator.selection_report() if item["tool_name"] == "click"
    )
    assert click_denied["status"] == "denied"
    assert "deny" in click_denied["reason"].lower()

    from core.builtin_tool_registration import register_builtin_tools

    class Registry:
        def __init__(self) -> None:
            self.tools: dict[str, Tool] = {}

        def register(self, tool: Tool, *, risk: str = "read") -> None:
            del risk
            self.tools[tool.name] = tool

        def register_alias(self, alias: str, target_name: str) -> bool:
            del alias, target_name
            return True

        def get_names(self) -> list[str]:
            return list(self.tools)

        def get(self, name: str) -> Tool | None:
            return self.tools.get(name)

    builtin = ToolOrchestrator()
    register_builtin_tools(Registry(), builtin, rag_enabled=False)
    builtin_names = set(builtin.list_names())
    assert "read" in builtin_names
    assert "click" not in builtin_names
    assert "type_text" not in builtin_names


def test_w6_c01_negative() -> None:
    """A new MCP readOnlyHint cannot be classified down to READ."""
    from core.safety.policy import RiskLevel
    from rxycode_core.tools.capability_catalog import classify_mcp

    readonly = classify_mcp("mcp_fresh_widget", {"readOnlyHint": True})
    destructive = classify_mcp(
        "mcp_fresh_wipe",
        {"readOnlyHint": True, "destructiveHint": True},
    )
    assert readonly != RiskLevel.READ
    assert readonly == RiskLevel.WRITE
    assert destructive == RiskLevel.DANGER
