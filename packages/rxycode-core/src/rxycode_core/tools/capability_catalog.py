"""Read-only projection of registered tools onto capability domains.

A target declares capabilities. Profile full does not put every ToolSpec
into the selection. Desktop input stays on the local machine.
"""

from __future__ import annotations

from typing import Any

from RxyCode.RxyCode1_1_0.core.cu.spec import ACTION_TOOLS, TOOL_RISK
from RxyCode.RxyCode1_1_0.core.safety.policy import (
    RiskLevel,
    apply_mcp_hint,
    get_tool_risk,
)

DESKTOP_INPUT = frozenset(ACTION_TOOLS)
FS_READ = frozenset(
    {"read", "view", "grep", "glob", "ls", "datetime", "websearch", "webfetch"}
)


def capability_of(name: str) -> str:
    if name in DESKTOP_INPUT:
        return "desktop.input"
    if name in FS_READ:
        return "fs.read"
    if name == "bash":
        return "shell"
    return "general"


def target_of(name: str) -> str:
    if name in DESKTOP_INPUT:
        return "local"
    return "any"


def risk_of(name: str) -> RiskLevel:
    if name in TOOL_RISK:
        return TOOL_RISK[name]
    return get_tool_risk(name)


def timeout_of(name: str) -> float:
    from execution.tool_orchestrator import ToolOrchestrator

    if name in ToolOrchestrator._SLOW_START_TOOLS:
        return float(ToolOrchestrator._SLOW_START_TOOLS[name])
    if name in ToolOrchestrator._TOOL_STALL_SECONDS:
        return float(ToolOrchestrator._TOOL_STALL_SECONDS[name])
    return float(ToolOrchestrator._DEFAULT_STALL_SECONDS)


def idempotent_of(name: str) -> bool:
    return name not in DESKTOP_INPUT and risk_of(name) == RiskLevel.READ


def inventory(tools: Any) -> list[dict[str, Any]]:
    """Project tools to tool_name, capability, target, risk, timeout, idempotent."""
    rows: list[dict[str, Any]] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        rows.append(
            {
                "tool_name": name,
                "capability": capability_of(name),
                "target": target_of(name),
                "risk": risk_of(name).name,
                "timeout": timeout_of(name),
                "idempotent": idempotent_of(name),
            }
        )
    return rows


def classify_mcp(name: str, annotations: dict[str, Any] | None) -> RiskLevel:
    """Classify a new MCP tool. Hints may raise risk. They cannot lower it to READ."""
    return apply_mcp_hint(name, get_tool_risk(name), annotations)


def filter_selection(
    tools: list[Any],
    *,
    target: str | None,
    capabilities: list[str] | None,
    profile: str | None,
    permission: Any | None,
) -> tuple[list[Any], list[dict[str, str]]]:
    """Drop tools the target did not declare. Full profile does not add them back."""
    del profile
    declared = set(capabilities or [])
    kept: list[Any] = []
    report: list[dict[str, str]] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        capability = capability_of(name)
        if target == "cloud" and capability == "desktop.input":
            report.append(
                {
                    "tool_name": name,
                    "status": "unavailable",
                    "reason": "cloud target does not expose local desktop input",
                }
            )
            continue
        if target == "remote" and capability not in declared and capability != "general":
            report.append(
                {
                    "tool_name": name,
                    "status": "unavailable",
                    "reason": f"unavailable: remote does not declare {capability}",
                }
            )
            continue
        if permission is not None:
            decision = permission.evaluate(name)
            kind = getattr(getattr(decision, "kind", None), "name", "")
            if kind == "DENY":
                report.append(
                    {
                        "tool_name": name,
                        "status": "denied",
                        "reason": str(getattr(decision, "reason", "") or "permission denied"),
                    }
                )
                continue
        report.append(
            {
                "tool_name": name,
                "status": "selected",
                "reason": "target capability allows this tool",
            }
        )
        kept.append(tool)
    return kept, report
