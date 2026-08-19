"""GX14-B: agent/invoke + session/prompt capability hard boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.server import AppServer
from appserver.tool_registry_capability import CapabilityDenied, ToolRegistryCapability, allow_tool
from protocol.requests import AgentInvokeRequest, PromptRequest


def test_capability_optional_on_invoke_and_prompt() -> None:
    invoke = AgentInvokeRequest(root_session_id="r", agent_id="a", prompt="hi")
    assert invoke.capability is None
    invoke2 = AgentInvokeRequest(root_session_id="r", agent_id="a", prompt="hi", capability="edit_only")
    assert invoke2.capability == "edit_only"
    prompt = PromptRequest(session_id="s", text="x", capability="no_tools")
    assert prompt.capability == "no_tools"


def test_registry_rejects_edit_only_and_no_tools() -> None:
    allow_tool("full", "bash")
    allow_tool("edit_only", "edit")
    allow_tool("edit_only", "write")
    with pytest.raises(CapabilityDenied, match="edit_only"):
        allow_tool("edit_only", "bash")
    with pytest.raises(CapabilityDenied, match="edit_only"):
        allow_tool("edit_only", "delete")
    with pytest.raises(CapabilityDenied, match="edit_only"):
        allow_tool("edit_only", "git")
    with pytest.raises(CapabilityDenied, match="no_tools"):
        allow_tool("no_tools", "read")


def test_session_store_and_appserver_check(tmp_path: Path) -> None:
    server = AppServer(stub=True)
    session = server._sessions.create(tmp_path, title="gx14")
    server._tool_capability.set_session(session.session_id, "edit_only")
    server._tool_capability.check(session.session_id, "write")
    with pytest.raises(CapabilityDenied):
        server._tool_capability.check(session.session_id, "bash")
    server._tool_capability.set_session(session.session_id, "no_tools")
    with pytest.raises(CapabilityDenied):
        server._tool_capability.check(session.session_id, "edit")
    # capability first vs plan mode: registry raises protocol error, not plan blocked text
    with pytest.raises(CapabilityDenied) as exc:
        server._tool_capability.check(session.session_id, "write")
    assert "plan mode" not in str(exc.value)


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
    assert ToolRegistryCapability().get("missing") == "full"
