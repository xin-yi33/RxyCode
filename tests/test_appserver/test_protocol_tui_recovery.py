from __future__ import annotations

from pydantic import BaseModel

from RxyCode.RxyCode1_1_0.appserver.tui import ProtocolTui


def test_protocol_tui_keeps_recovery_events_in_tool_order() -> None:
    emitted: list[BaseModel] = []
    tui = ProtocolTui("session-1", emitted.append, run_id="run-1")

    call_one = tui.write_tool_call("read_file", {"path": "missing.txt"}, "call-1")
    tui.write_tool_result("[error: missing]", "error", call_one)
    call_two = tui.write_tool_call("search", {"query": "missing"}, "call-2")
    tui.write_tool_result("found", "success", call_two)

    methods = [item.method for item in emitted]
    assert methods == [
        "event/tool_begin",
        "event/progress",
        "event/tool_end",
        "event/recovery_started",
        "event/recovery_analyzing",
        "event/recovery_attempt",
        "event/tool_begin",
        "event/progress",
        "event/tool_end",
        "event/recovery_resolved",
    ]
    recovery_events = [item for item in emitted if "recovery" in item.method]
    assert [item.seq for item in recovery_events] == [1, 2, 3, 4]
    assert recovery_events[0].session_id == "session-1"
    assert recovery_events[-1].display_summary == "已自动恢复"


def test_protocol_tui_exhausts_recovery_only_when_session_finishes() -> None:
    emitted: list[BaseModel] = []
    tui = ProtocolTui("session-2", emitted.append, run_id="run-2")
    tui.write_tool_call("read_file", {"path": "missing.txt"}, "call-1")
    tui.write_tool_result("[error: missing]", "error", "call-1")

    # A tool error is intermediate: no terminal error is emitted by TUI.
    assert not any(item.method == "event/recovery_exhausted" for item in emitted)
    tui.exhaust_active_recovery("模型未能找到可行的恢复路径")

    exhausted = [item for item in emitted if item.method == "event/recovery_exhausted"]
    assert len(exhausted) == 1
    assert exhausted[0].final_error == "模型未能找到可行的恢复路径"
def test_protocol_tui_redacts_and_bounds_recovery_and_tool_summaries() -> None:
    emitted: list[BaseModel] = []
    tui = ProtocolTui("session-safe", emitted.append, run_id="run-safe")
    tui.write_tool_call("read", {}, "call-safe")
    tui.write_tool_result("api_key=super-secret " + "x" * 6000, "error", "call-safe")
    tui.exhaust_active_recovery("authorization: Bearer super-secret")

    tool_end = next(item for item in emitted if item.method == "event/tool_end")
    exhausted = next(item for item in emitted if item.method == "event/recovery_exhausted")
    assert "super-secret" not in str(tool_end)
    assert "super-secret" not in str(exhausted)
    assert len(str(tool_end.summary)) < 5000


def test_tool_error_is_not_event_error() -> None:
    emitted: list[BaseModel] = []
    tui = ProtocolTui("session-biz", emitted.append, run_id="run-biz")
    tui.write_tool_call("bash", {"command": "false"}, "call-biz")
    tui.write_tool_result("[error: exit 1]", "error", "call-biz")
    assert any(item.method == "event/tool_end" for item in emitted)
    assert not any(item.method == "event/error" for item in emitted)
