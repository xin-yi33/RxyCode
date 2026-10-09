"""E-F5-E2E-05. Appserver event, todo/get, then the OpenTUI dock."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import RxyCode.RxyCode1_1_0.appserver.server as server_module
from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.config import settings
from RxyCode.RxyCode1_1_0.core.builtin_tool_registration import register_builtin_tools
from RxyCode.RxyCode1_1_0.core.session_runtime import bind_session, reset_session_binding
from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
from RxyCode.RxyCode1_1_0.tools.registry import ToolRegistry
from RxyCode.RxyCode1_1_0.tools.todo_events import bind_todo_sink
from tests.conftest import require_tool

REPO = Path(__file__).resolve().parents[2]
SESSION = "sess_e2e05"
EVENT_KEYS = {"event_id", "seq", "timestamp", "snapshot"}


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_dir", lambda: tmp_path)
    return tmp_path


def _todo_events(notes: list[dict]) -> list[dict]:
    return [note for note in notes if note.get("method") == "event/todo_updated"]


async def _todo_get(server: AppServer, request_id: int) -> dict:
    sent: list[dict] = []

    async def capture(message: dict) -> None:
        sent.append(message)

    previous = server_module.write_message
    server_module.write_message = capture
    try:
        server._initialized = True
        await server._dispatch(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "todo/get",
                "params": {"session_id": SESSION},
            }
        )
    finally:
        server_module.write_message = previous
    return next(item["result"] for item in sent if item.get("id") == request_id)


@pytest.mark.asyncio
async def test_e_f5_e2e_05_event_get_and_dock(data_dir):
    notes: list[dict] = []
    server = AppServer(stub=True)
    server._schedule_notification = lambda message: notes.append(message)
    registry = ToolRegistry()
    orchestrator = ToolOrchestrator(tool_registry=registry)
    register_builtin_tools(registry, orchestrator, rag_enabled=False)
    token = bind_session(SESSION)
    try:
        first = await orchestrator.execute_tool(
            "todo_write",
            {
                "todos": [
                    {"id": "t1", "content": "搭骨架", "status": "in_progress"},
                    {"id": "t2", "content": "装依赖", "status": "pending"},
                ],
                "merge": True,
            },
            mode="full_auto",
        )
        assert "搭骨架" in first
        events = _todo_events(notes)
        assert len(events) == 1
        assert set(events[0]["params"]) == EVENT_KEYS
        snapshot = events[0]["params"]["snapshot"]
        assert snapshot["session_id"] == SESSION
        assert snapshot["revision"] >= 1
        assert [item["id"] for item in snapshot["items"]] == ["t1", "t2"]

        current = await _todo_get(server, 1)
        assert current["revision"] == snapshot["revision"]
        assert current["items"] == snapshot["items"]

        rejected = await orchestrator.execute_tool(
            "todo_write",
            {
                "todos": [
                    {"id": "t1", "status": "in_progress"},
                    {"id": "t2", "status": "in_progress"},
                ],
                "merge": True,
            },
            mode="full_auto",
        )
        assert rejected.startswith("[todo_write rejected]")
        assert len(_todo_events(notes)) == 1
        after_reject = await _todo_get(server, 2)
        assert after_reject["revision"] == current["revision"]
        assert after_reject["items"] == current["items"]

        await orchestrator.execute_tool(
            "todo_write",
            {
                "todos": [
                    {"id": "t1", "status": "completed"},
                    {"id": "t2", "status": "completed"},
                ],
                "merge": True,
            },
            mode="full_auto",
        )
        events = _todo_events(notes)
        assert len(events) == 2
        assert set(events[1]["params"]) == EVENT_KEYS

        reconnect = AppServer(stub=True)
        boot = await _todo_get(reconnect, 3)
        assert boot["revision"] == events[1]["params"]["snapshot"]["revision"]
        assert boot["items"] == events[1]["params"]["snapshot"]["items"]

        record = data_dir / "recorded-todo-event.json"
        record.write_text(
            json.dumps(
                {
                    "bootstrap": current,
                    "first_event": events[0]["params"],
                    "completed_event": events[1]["params"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["FIX5_TODO_RECORDING"] = str(record)
        require_tool("bun", reason="FIX5 projection OpenTUI dock E2E")
        bun = shutil.which("bun")
        assert bun is not None
        proc = subprocess.run(
            [
                bun,
                "test",
                "src/todoDock.test.ts",
            ],
            cwd=str(REPO / "frontend" / "opentui-app"),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
        assert proc.returncode == 0, (
            f"bun test failed with exit code {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
        assert (data_dir / "recorded-todo-event.json.ok").read_text(encoding="utf-8") == "ok"
    finally:
        reset_session_binding(token)
        bind_todo_sink(None)
