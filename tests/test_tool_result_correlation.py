"""Parallel tool results retain the call that produced them."""

import asyncio

import pytest


@pytest.mark.asyncio
async def test_orchestrator_emits_one_complete_api_proxy_lifecycle():
    from langchain_core.tools import StructuredTool

    from RxyCode.RxyCode1_1_0.api_server import APIProxyTUI
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator

    complete_result = "result:" + ("x" * 1200)
    complete_args = {"value": "y" * 600}
    tool = StructuredTool.from_function(
        func=lambda value: complete_result,
        name="complete_tool",
        description="Return an untruncated result.",
    )
    orchestrator = ToolOrchestrator()
    orchestrator.register("complete_tool", tool)
    proxy = APIProxyTUI()
    token = orchestrator.bind_event_tui(proxy)
    try:
        result = await orchestrator.execute_tool(
            "complete_tool",
            complete_args,
            config={"safety": {"enabled": False}},
            call_id="model-call-42",
        )
    finally:
        orchestrator.reset_event_tui(token)

    assert result == complete_result
    assert proxy._tool_calls == [{
        "id": "model-call-42",
        "name": "complete_tool",
        "args": complete_args,
        "result": complete_result,
        "status": "success",
    }]


def test_api_proxy_correlates_interleaved_tool_results_by_call_id():
    from RxyCode.RxyCode1_1_0.api_server import APIProxyTUI

    proxy = APIProxyTUI()
    first_id = proxy.write_tool_call("first", {"value": 1})
    second_id = proxy.write_tool_call("second", {"value": 2})

    proxy.write_tool_result("first-result", "success", call_id=first_id)
    proxy.write_tool_result("second-result", "error", call_id=second_id)

    assert proxy._tool_calls[0]["result"] == "first-result"
    assert proxy._tool_calls[0]["status"] == "success"
    assert proxy._tool_calls[1]["result"] == "second-result"
    assert proxy._tool_calls[1]["status"] == "error"


def test_stream_recorder_and_sse_correlate_interleaved_tool_results():
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    queue = asyncio.Queue()
    history = []
    recorder = StreamSessionRecorder(history, run_id="parallel-run", user_message="go")
    tui = StreamTUI(queue, recorder=recorder)

    first_id = tui.write_tool_call("first", {"value": 1})
    second_id = tui.write_tool_call("second", {"value": 2})
    tui.write_tool_result("first-result", "success", call_id=first_id)
    tui.write_tool_result("second-result", "error", call_id=second_id)

    tools = {message["id"]: message for message in recorder.messages if message["role"] == "tool"}
    assert tools[first_id]["toolStdout"] == "first-result"
    assert tools[first_id]["toolStatus"] == "success"
    assert tools[second_id]["toolStdout"] == "second-result"
    assert tools[second_id]["toolStatus"] == "error"

    events = [queue.get_nowait() for _ in range(4)]
    assert [event["message_id"] for event in events] == [
        first_id,
        second_id,
        first_id,
        second_id,
    ]
