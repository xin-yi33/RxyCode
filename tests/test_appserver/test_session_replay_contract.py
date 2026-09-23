"""layer=unit FR-SS-B 卡 B：replay 只持久化 final/tool，不写 token delta。"""
from __future__ import annotations

from pathlib import Path

from appserver.server import AppServer, _REPLAY_EVENT_METHODS
from appserver.sessions import SessionStore
from appserver.task_store import DesktopTaskStore


def test_replay_methods_keep_final_and_tools_skip_deltas():
    assert "event/final" in _REPLAY_EVENT_METHODS
    assert "event/tool_begin" in _REPLAY_EVENT_METHODS
    assert "event/tool_end" in _REPLAY_EVENT_METHODS
    assert "event/error" in _REPLAY_EVENT_METHODS
    assert "event/message_delta" not in _REPLAY_EVENT_METHODS
    assert "event/reasoning_snapshot" not in _REPLAY_EVENT_METHODS


def test_persist_keeps_final_thinking_and_redacts_tool_secrets(tmp_path: Path):
    server = AppServer(stub=True)
    server._task_store = DesktopTaskStore(tmp_path / "tasks.json")
    server._sessions = SessionStore(task_store=server._task_store)
    record = server._sessions.create(tmp_path / "workspace", title="Replay")

    server._persist_notification(
        {
            "method": "event/message_delta",
            "params": {"session_id": record.session_id, "text": "do not persist"},
        }
    )
    server._persist_notification(
        {
            "method": "event/tool_begin",
            "params": {
                "session_id": record.session_id,
                "call_id": "c1",
                "tool_name": "read",
                "arguments": {"path": "a.ts"},
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/tool_end",
            "params": {
                "session_id": record.session_id,
                "call_id": "c1",
                "ok": True,
                "summary": "ok",
            },
        }
    )
    server._persist_notification(
        {
            "method": "event/final",
            "params": {
                "session_id": record.session_id,
                "text": "**done**",
                "thinking": "先读文件再改",
            },
        }
    )

    events, cursor, gap = server._task_store.events(record.session_id, 0)
    assert gap is False
    methods = [item["method"] for item in events]
    assert "event/message_delta" not in methods
    assert methods == ["event/tool_begin", "event/tool_end", "event/final"]
    assert cursor == 3
    final = events[-1]["params"]
    assert final["text"] == "**done**"
    assert final["thinking"] == "先读文件再改"
    assert events[0]["params"]["call_id"] == "c1"
