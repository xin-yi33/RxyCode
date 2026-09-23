"""layer=e2e FR-SS-B 卡 B：session/events 还原 thought / tool / final，不把 delta 当 transcript。"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from RxyCode.RxyCode1_1_0.appserver.server import AppServer
from RxyCode.RxyCode1_1_0.appserver.sessions import SessionStore
from RxyCode.RxyCode1_1_0.appserver.task_store import DesktopTaskStore

pytestmark = pytest.mark.e2e
REPO = Path(__file__).resolve().parents[3]


def test_e2e_card_b_session_events_restore_thought_tool_final(tmp_path):
    server = AppServer(stub=True)
    server._initialized = True
    server._task_store = DesktopTaskStore(tmp_path / "tasks.json")
    server._sessions = SessionStore(task_store=server._task_store)
    rec = server._sessions.create(tmp_path / "ws", title="Replay")
    server._sessions.note_user_prompt(rec.session_id, "修登录")
    server._task_store.append_event(
        rec.session_id,
        {
            "method": "session/prompt",
            "params": {"session_id": rec.session_id, "text": "修登录", "role": "user"},
        },
    )
    server._persist_notification(
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": rec.session_id,
                "call_id": "c1",
                "tool_name": "read",
                "arguments": {"path": "login.ts"},
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/tool_end",
            "params": {
                "session_id": rec.session_id,
                "call_id": "c1",
                "ok": True,
                "summary": "read ok",
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": rec.session_id,
                "call_id": "c2",
                "tool_name": "bash",
                "arguments": {"command": "ls"},
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": rec.session_id,
                "call_id": "e1",
                "tool_name": "bash",
                "arguments": {"command": "bad"},
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/tool_end",
            "params": {
                "session_id": rec.session_id,
                "call_id": "e1",
                "ok": False,
                "summary": "fail",
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/final",
            "params": {
                "session_id": rec.session_id,
                "text": "**已修好**",
                "thinking": "先读文件再改验证码",
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/message_delta",
            "params": {"session_id": rec.session_id, "text": "should-not-store"},
        }
    )

    responses: list[object] = []
    server._respond = AsyncMock(side_effect=lambda _rid, payload: responses.append(payload))
    asyncio.run(
        server._handle_session_events({"session_id": rec.session_id, "cursor": 0}, 1)
    )
    events = responses[-1]["events"]
    methods = [item["method"] for item in events]
    assert "session/prompt" in methods
    assert "event/tool_begin" in methods
    assert "event/tool_end" in methods
    assert "event/final" in methods
    assert "event/message_delta" not in methods
    final = next(item for item in events if item["method"] == "event/final")
    assert final["params"]["text"] == "**已修好**"
    assert final["params"]["thinking"] == "先读文件再改验证码"
    begin = next(item for item in events if item["method"] == "event/tool_begin")
    ends = [item for item in events if item["method"] == "event/tool_end"]
    assert begin["params"]["call_id"] == "c1"
    assert {item["params"]["call_id"] for item in ends} == {"c1", "e1"}
    mapper_src = (REPO / "frontend/opentui-app/src/dialog/sessionEventsToMessages.ts").read_text(
        encoding="utf-8"
    )
    assert "normalizeLoadedMessages" in mapper_src
    assert 'toolStatus === "running"' in mapper_src
    dialog = (REPO / "frontend/opentui-app/src/dialog/useSettingsDialogs.tsx").read_text(
        encoding="utf-8"
    )
    assert "normalizeLoadedMessages" in dialog

    mapped = _map_session_events(events)
    roles = [row["role"] for row in mapped]
    assert roles[:1] == ["user"]
    assert "thinking" in roles
    assert "assistant" in roles
    tools = [row for row in mapped if row["role"] == "tool"]
    statuses = {row["toolCallId"]: row["toolStatus"] for row in tools}
    assert statuses["c1"] == "success"
    assert statuses["c2"] == "cancelled"
    assert statuses["e1"] == "error"
    assert all(row["toolStatus"] != "running" for row in tools)
    assert any("login.ts" in str(row.get("toolArgs") or "") for row in tools)
    thought = next(row for row in mapped if row["role"] == "thinking")
    assert thought["content"] == "先读文件再改验证码"
    assistant = next(row for row in mapped if row["role"] == "assistant")
    assert assistant["content"] == "**已修好**"
    assert assistant["done"] is True


def _bun_executable() -> str:
    found = shutil.which("bun") or shutil.which("bun.cmd") or shutil.which("bun.exe")
    assert found, "bun executable not found"
    nested = Path(found).parent / "node_modules" / "bun" / "bin" / "bun.exe"
    if nested.is_file():
        return str(nested)
    return found


def _map_session_events(events: list[object]) -> list[dict]:
    frontend = REPO / "frontend" / "opentui-app"
    script = (
        'import { sessionEventsToMessages } from "./src/dialog/sessionEventsToMessages.ts";'
        "const events = JSON.parse(await Bun.stdin.text());"
        "process.stdout.write(JSON.stringify(sessionEventsToMessages(events)));"
    )
    proc = subprocess.run(
        [_bun_executable(), "-e", script],
        cwd=str(frontend),
        input=json.dumps(events, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads(proc.stdout)
    assert isinstance(payload, list)
    return payload
