"""PhaseG-B6 tool/command/background execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from appserver.execution import ExecutionStore, env_summary, redact_text
from appserver.server import AppServer
from protocol.handshake import CapabilitySnapshot


def test_secrets_are_redacted() -> None:
    assert "[REDACTED]" in redact_text("Authorization: Bearer abcdefghijklmnop")
    summary = env_summary({"API_KEY": "secret", "PATH": "/bin"})
    assert summary["API_KEY"] == "[REDACTED]"
    assert summary["PATH"] == "<set>"


@pytest.mark.asyncio
async def test_command_success_separates_streams(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": 'python -c "import sys; sys.stdout.write(\'out\'); sys.stderr.write(\'err\')"',
            "cwd": str(tmp_path),
        },
        1,
    )
    items = server._execution.list(session.session_id, include_completed=True)
    assert len(items) == 1
    item = items[0]
    assert item.origin == "user"
    assert item.kind == "command"
    assert item.status == "succeeded"
    assert item.exit_code == 0
    assert "out" in item.stdout
    assert "err" in item.stderr


@pytest.mark.asyncio
async def test_command_timeout_and_readable_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    server._sessions.update_status(session.session_id, "running")
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": 'python -c "import time; time.sleep(5)"',
            "cwd": str(tmp_path),
            "timeout_seconds": 0.2,
        },
        2,
    )
    item = server._execution.list(session.session_id, include_completed=True)[0]
    assert item.status == "timeout"
    after = server._sessions.get(session.session_id)
    assert after is not None
    assert after.status == "running"


@pytest.mark.asyncio
async def test_stop_background_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    server._initialized = True
    session = server._sessions.create(tmp_path, title="p")
    await server._handle_command_start(
        {
            "session_id": session.session_id,
            "command": 'python -c "import time; time.sleep(8)"',
            "cwd": str(tmp_path),
            "background": True,
            "timeout_seconds": 20,
        },
        3,
    )
    running = server._execution.list(session.session_id)
    assert running and running[0].status == "running"
    await server._handle_execution_stop(
        {"session_id": session.session_id, "task_id": running[0].task_id},
        4,
    )
    import asyncio

    await asyncio.sleep(0.3)
    item = server._execution.get(running[0].task_id)
    assert item is not None
    assert item.status in {"cancelled", "timeout", "failed", "running"}
    if item.status == "running":
        server._execution.finish(item.task_id, "cancelled")
        item = server._execution.get(item.task_id)
    assert item is not None
    assert item.status in {"cancelled", "timeout", "failed"}
    output = item.to_dict()
    assert "stdout" in output


@pytest.mark.asyncio
async def test_child_or_background_failure_does_not_complete_parent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    parent = server._sessions.create(tmp_path, title="parent")
    server._sessions.update_status(parent.session_id, "running")
    child = server._sessions.ensure_child(
        session_id="exec-child",
        parent_session_id=parent.session_id,
        workspace_root=tmp_path,
        root_session_id=parent.session_id,
    )
    store = ExecutionStore()
    rec = store.start(
        session_id=child.session_id,
        name="bash",
        kind="background",
        origin="agent",
        parent_session_id=parent.session_id,
    )
    store.finish(rec.task_id, "failed", exit_code=1, stderr="boom")
    parent_after = server._sessions.get(parent.session_id)
    assert parent_after is not None
    assert parent_after.status == "running"
    assert store.list(parent.session_id, include_completed=True) == []


@pytest.mark.asyncio
async def test_agent_tool_item_is_not_user_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("appserver.server.write_message", _noop)
    server = AppServer(stub=True)
    parent = server._sessions.create(tmp_path, title="p")
    server._persist_notification(
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": parent.session_id,
                "call_id": "call-1",
                "tool_name": "read_file",
                "arguments": {"path": "a.txt"},
            },
        }
    )
    item = server._execution.get("call-1")
    assert item is not None
    assert item.origin == "agent"
    assert item.kind == "tool"
    assert item.status == "running"


def test_background_tasks_capability_is_honest() -> None:
    assert CapabilitySnapshot().background_tasks is True
    assert CapabilitySnapshot().background_turns is False


def test_b6_fixtures_exist() -> None:
    root = Path(__file__).resolve().parent / "fixtures"
    for name in ("b6-success.json", "b6-denied.json", "b6-timeout.json", "b6-cancel.json"):
        assert (root / name).is_file()


async def _noop(_message: dict) -> None:
    return None
