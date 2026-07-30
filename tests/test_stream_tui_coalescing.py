"""StreamTUI coalescing + thinking gating (问题4/5/6 后端根源).

Paradigm ported from google-gemini/gemini-cli (Apache-2.0)
useGeminiStream: high-frequency stream chunks are accumulated and
flushed on a fixed tick instead of one SSE event per chunk.
"""

import asyncio

import pytest

pytestmark = pytest.mark.unit


def _make_tui(**kwargs):
    from RxyCode.RxyCode1_1_0.api_server import StreamTUI

    queue = asyncio.Queue()
    tui = StreamTUI(queue, **kwargs)
    return tui, queue


def _drain(queue):
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return events


# ---------------------------------------------------------------- B1 合并节拍


def test_reasoning_chunks_coalesce_into_single_event():
    tui, queue = _make_tui()
    tui.set_thinking_expanded(True)
    for i in range(100):
        tui.write_reasoning(f"r{i}")
    tui.flush_stream_buffers()

    events = _drain(queue)
    reasoning = [e for e in events if e["type"] == "reasoning"]
    # 100 个 chunk 绝不能变成 100 个事件；节拍内应合并为极少数事件。
    assert len(reasoning) <= 3
    joined = "".join(e["text"] for e in reasoning)
    assert "r0" in joined and "r99" in joined


def test_tokens_coalesce_and_preserve_order():
    tui, queue = _make_tui()
    for ch in "hello world":
        tui.stream_token(ch)
    tui.flush_stream_buffers()

    events = _drain(queue)
    tokens = [e for e in events if e["type"] == "token"]
    assert len(tokens) <= 3
    assert "".join(e["text"] for e in tokens) == "hello world"


def test_discrete_event_forces_flush_before_it():
    """tool_call 等离散事件必须先冲刷缓冲，保证顺序不乱。"""
    tui, queue = _make_tui()
    tui.stream_token("abc")
    tui.write_tool_call("run", {"x": 1})

    events = _drain(queue)
    types = [e["type"] for e in events]
    assert types.index("token") < types.index("tool_call")


# ---------------------------------------------------------------- B2 thinking 门控


def test_reasoning_suppressed_when_thinking_disabled():
    tui, queue = _make_tui()
    tui.set_thinking_expanded(False)
    tui.write_reasoning("internal chain of thought")
    tui.flush_stream_buffers()

    assert not [e for e in _drain(queue) if e["type"] == "reasoning"]


def test_reasoning_still_recorded_when_thinking_disabled():
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    queue = asyncio.Queue()
    recorder = StreamSessionRecorder([], run_id="r1", user_message="hi")
    tui = StreamTUI(queue, recorder=recorder)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("hidden reasoning")
    tui.flush_stream_buffers()

    assert "hidden reasoning" in recorder.thinking_content


def test_internal_progress_suppressed_when_thinking_disabled():
    tui, queue = _make_tui()
    tui.set_thinking_expanded(False)
    tui.write_progress("Thinking... (round 3)")
    tui.write_progress("[Code block: 120 lines]")
    tui.flush_stream_buffers()

    assert not [e for e in _drain(queue) if e["type"] == "progress"]


def test_short_status_progress_passes_when_thinking_disabled():
    """面向用户的短状态行（如图节点进度）不受 thinking 门控。"""
    tui, queue = _make_tui()
    tui.set_thinking_expanded(False)
    tui.write_progress("Decomposed into 1 sub-tasks")
    tui.flush_stream_buffers()

    progress = [e for e in _drain(queue) if e["type"] == "progress"]
    assert any("Decomposed into 1 sub-tasks" in e["text"] for e in progress)


def test_tokens_always_pass_regardless_of_thinking():
    tui, queue = _make_tui()
    tui.set_thinking_expanded(False)
    tui.stream_token("answer text")
    tui.flush_stream_buffers()

    tokens = [e for e in _drain(queue) if e["type"] == "token"]
    assert "".join(e["text"] for e in tokens) == "answer text"


# ---------------------------------------------------------------- B3 工具结果截断


def test_tool_result_truncated_on_sse_but_full_in_recorder():
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    queue = asyncio.Queue()
    recorder = StreamSessionRecorder([], run_id="r2", user_message="go")
    tui = StreamTUI(queue, recorder=recorder)

    call_id = tui.write_tool_call("big", {})
    big = "\n".join(f"line{i}" for i in range(500))
    tui.write_tool_result(big, "success", call_id=call_id)

    events = _drain(queue)
    result_ev = next(e for e in events if e["type"] == "tool_result")
    assert len(result_ev["result"]) < len(big)
    assert result_ev.get("truncated") is True
    # recorder 保留全量
    tools = [m for m in recorder.messages if m["role"] == "tool"]
    assert tools[0]["toolStdout"] == big


def test_small_tool_result_not_truncated():
    tui, queue = _make_tui()
    call_id = tui.write_tool_call("small", {})
    tui.write_tool_result("ok", "success", call_id=call_id)

    result_ev = next(e for e in _drain(queue) if e["type"] == "tool_result")
    assert result_ev["result"] == "ok"
    assert not result_ev.get("truncated")
