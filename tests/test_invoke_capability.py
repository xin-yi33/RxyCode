"""GX14-B: capability hard boundary on the live tool-begin path."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.server import AppServer
from protocol.requests import AgentInvokeRequest, PromptRequest


def test_capability_optional_on_invoke_and_prompt() -> None:
    invoke = AgentInvokeRequest(root_session_id="r", agent_id="a", prompt="hi")
    assert invoke.capability is None
    invoke2 = AgentInvokeRequest(root_session_id="r", agent_id="a", prompt="hi", capability="edit_only")
    assert invoke2.capability == "edit_only"
    prompt = PromptRequest(session_id="s", text="x", capability="no_tools")
    assert prompt.capability == "no_tools"


@pytest.mark.asyncio
async def test_prompt_edit_only_denies_bash_on_tool_begin(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    async def no_worker(**kwargs):
        return None

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    monkeypatch.setattr(server, "_run_prompt", no_worker)
    session = server._sessions.create(tmp_path, title="gx14")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "session/prompt",
            "params": {
                "session_id": session.session_id,
                "text": "edit the file",
                "capability": "edit_only",
            },
        }
    )
    for task in list(server._prompt_tasks):
        await task
    sent.clear()
    server._persist_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/tool_begin",
            "params": {
                "session_id": session.session_id,
                "call_id": "call-bash",
                "tool_name": "bash",
                "arguments": {"command": "rm -rf /"},
            },
        }
    )
    await server._drain_emit_writes()
    errors = [
        item
        for item in sent
        if item.get("method") == "event/error"
        and (item.get("params") or {}).get("error_code") == "capability_denied"
    ]
    assert errors, sent
    assert server._execution.get("call-bash") is None


@pytest.mark.asyncio
async def test_invoke_no_tools_denies_any_tool(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    async def boom(*args, **kwargs):
        raise RuntimeError("no worker")

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    monkeypatch.setattr(server, "_host_for_session", boom)
    session = server._sessions.create(tmp_path, title="gx14")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "agent/invoke",
            "params": {
                "root_session_id": session.session_id,
                "agent_id": "helper",
                "prompt": "look around",
                "capability": "no_tools",
            },
        }
    )
    sent.clear()
    server._persist_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/tool_begin",
            "params": {
                "session_id": session.session_id,
                "call_id": "call-read",
                "tool_name": "read",
            },
        }
    )
    await server._drain_emit_writes()
    errors = [
        item
        for item in sent
        if item.get("method") == "event/error"
        and (item.get("params") or {}).get("error_code") == "capability_denied"
    ]
    assert errors, sent
    assert server._execution.get("call-read") is None


@pytest.mark.asyncio
async def test_edit_only_allows_write_tool_begin(tmp_path: Path, monkeypatch) -> None:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    async def no_worker(**kwargs):
        return None

    monkeypatch.setattr("appserver.server.write_message", capture)
    server = AppServer(stub=True)
    server._initialized = True
    monkeypatch.setattr(server, "_run_prompt", no_worker)
    session = server._sessions.create(tmp_path, title="gx14")
    await server._dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "session/prompt",
            "params": {
                "session_id": session.session_id,
                "text": "write it",
                "capability": "edit_only",
            },
        }
    )
    for task in list(server._prompt_tasks):
        await task
    server._persist_notification(
        {
            "jsonrpc": "2.0",
            "method": "event/tool_begin",
            "params": {
                "session_id": session.session_id,
                "call_id": "call-write",
                "tool_name": "write",
            },
        }
    )
    await server._drain_emit_writes()
    assert server._execution.get("call-write") is not None
    assert not any(
        (item.get("params") or {}).get("error_code") == "capability_denied" for item in sent
    )


def test_no_handlers_package() -> None:
    assert not (Path(__file__).resolve().parents[1] / "appserver" / "handlers").exists()
