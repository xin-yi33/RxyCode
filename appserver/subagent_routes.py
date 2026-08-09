"""JSON-RPC routes and capability discovery for isolated subagents.

B14 · Exposes the frozen entry names:
  - ``agent/invoke`` — user ``@agent`` dispatch
  - ``task/start``   — Desktop/CLI explicit child start
  - ``subagents/list`` — mentionable agent listing
  - ``subagents/capability`` — capability discovery

All routes delegate to ChildSessionManager; they never implement their own
lifecycle, permissions, budget, or workspace logic. This module is a thin
transport adapter for Phase D Desktop and LinkAgent consumers.
"""

from __future__ import annotations

from typing import Any

from protocol.subagents import (
    BudgetSpec,
    TaskRequest,
    TriggerKind,
    WorkspaceMode,
    WorkspaceScope,
)


def capability() -> dict[str, Any]:
    """Return the subagent capability report for client discovery."""
    try:
        from ..core.subagents.registry_provider import get_manager_or_none
    except ImportError:
        from core.subagents.registry_provider import get_manager_or_none

    manager = get_manager_or_none()
    if manager is None:
        return {
            "protocol_version": 1,
            "subagents_enabled": False,
            "task": False,
            "mention": False,
            "child_tasks": False,
        }
    cap = manager.capability
    return {
        "protocol_version": cap.protocol_version,
        "subagents_enabled": cap.subagents_enabled,
        "task": cap.task,
        "mention": cap.mention,
        "child_tasks": cap.child_tasks,
    }


def list_agents() -> dict[str, Any]:
    """Return mentionable agents for @ autocomplete."""
    try:
        from ..tools.agent_invoke import list_mentionable_agents
    except ImportError:
        from tools.agent_invoke import list_mentionable_agents

    return {"agents": list_mentionable_agents()}


async def invoke_agent(params: dict[str, Any]) -> dict[str, Any]:
    """Handle ``agent/invoke`` (user @agent dispatch).

    params: {agent_id, prompt, parent_session_id?}
    """
    try:
        from ..tools.agent_invoke import invoke_mention
    except ImportError:
        from tools.agent_invoke import invoke_mention

    agent_id = params.get("agent_id", "")
    prompt = params.get("prompt", "")
    parent_session_id = params.get("parent_session_id", "")

    result = await invoke_mention(
        agent_id,
        prompt,
        parent_session_id=parent_session_id,
    )
    return _result_to_dict(result)


async def start_task(params: dict[str, Any]) -> dict[str, Any]:
    """Handle ``task/start`` (explicit child start from Desktop/CLI).

    params: {agent_id, prompt, context?, requested_budget?, requested_workspace?}
    """
    try:
        from ..core.subagents.manager import ChildSessionManager
        from ..core.subagents.registry_provider import get_manager
    except ImportError:
        from core.subagents.manager import ChildSessionManager
        from core.subagents.registry_provider import get_manager

    manager: ChildSessionManager = get_manager()

    agent_id = params.get("agent_id", "")
    prompt = params.get("prompt", "")
    parent_session_id = params.get("parent_session_id", "") or manager.primary_session_id()

    requested_budget = None
    if params.get("requested_budget"):
        rb = params["requested_budget"]
        requested_budget = BudgetSpec(
            max_steps=rb.get("max_steps", 12),
            max_tokens=rb.get("max_tokens", 8000),
            max_wall_time_seconds=rb.get("max_wall_time_seconds", 300),
            max_concurrent_children=rb.get("max_concurrent_children", 3),
        )

    requested_workspace = None
    if params.get("requested_workspace"):
        ws = params["requested_workspace"]
        requested_workspace = WorkspaceScope(
            mode=WorkspaceMode(ws.get("mode", "read_only")),
        )

    request = TaskRequest(
        parent_session_id=parent_session_id,
        agent_id=agent_id,
        prompt=prompt,
        trigger=TriggerKind.AUTOMATIC,
        output_schema=params.get("output_schema"),
        requested_budget=requested_budget,
        requested_workspace=requested_workspace,
    )

    result = await manager.dispatch(request)
    return _result_to_dict(result)


def _result_to_dict(result) -> dict[str, Any]:
    """Serialize a TaskResult for the JSON-RPC response."""
    return {
        "request_id": result.request_id,
        "child_session_id": result.child_session_id,
        "status": result.status.value,
        "summary": result.summary,
        "artifacts": [{"kind": a.kind, "ref": a.ref, "sha256": a.sha256} for a in result.artifacts],
        "evidence": [{"path": e.path, "line": e.line, "sha256": e.sha256} for e in result.evidence],
        "usage": {
            "steps": result.usage.steps,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
        },
        "error": None if result.error is None else {
            "code": result.error.code,
            "message": result.error.message,
        },
    }
