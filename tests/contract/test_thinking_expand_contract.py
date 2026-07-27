"""Thinking expand / mid-run snapshot / SSE error mapping contracts (U3 + E8)."""

from __future__ import annotations

import asyncio
import itertools

import pytest

from RxyCode.RxyCode1_1_0.utils.user_facing_errors import to_user_facing_error


def _drain(queue):
    events = []
    while True:
        try:
            events.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            return events


@pytest.mark.asyncio
@pytest.mark.parametrize("expanded_before", (False, True))
async def test_thinking_toggle_expanded_state_matrix(expanded_before: bool, monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server

    class Agent:
        def __init__(self):
            self._last_thinking = "reasoning"
            self.flush_calls = 0

        def _flush_thinking(self, **_kwargs):
            self.flush_calls += 1

    agent = Agent()
    proxy = api_server.APIProxyTUI()
    proxy.set_thinking_expanded(expanded_before)
    previous = dict(api_server._state)
    api_server._state.update({"agent": agent, "tui_proxy": proxy})
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.utils.tui.get_tui", lambda: proxy)
    try:
        result = await api_server._execute_command(
            api_server.CommandRequest(command="/thinking")
        )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    assert result["action"] == "thinking_toggled"
    assert result["expanded"] is (not expanded_before)
    assert proxy.get_thinking_expanded() is (not expanded_before)
    assert agent.flush_calls == 0


@pytest.mark.asyncio
async def test_thinking_expand_mid_run_emits_recorder_snapshot(monkeypatch):
    """When /thinking turns ON during an active StreamTUI run, push accumulated thinking."""
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    queue = asyncio.Queue()
    recorder = StreamSessionRecorder([], run_id="run-expand", user_message="hi")
    stream_tui = StreamTUI(queue, recorder=recorder)
    stream_tui.set_thinking_expanded(False)

    stream_tui.write_reasoning("hidden chain of thought part1")
    stream_tui.write_reasoning(" part2")
    stream_tui.flush_stream_buffers()
    assert not [e for e in _drain(queue) if e["type"] == "reasoning"]
    assert "hidden chain of thought part1 part2" in recorder.thinking_content

    proxy = api_server.APIProxyTUI()
    proxy.set_thinking_expanded(False)
    previous = dict(api_server._state)
    api_server._state.update({"agent": object(), "tui_proxy": proxy})
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.utils.tui.get_tui", lambda: stream_tui)
    try:
        result = await api_server._execute_command(
            api_server.CommandRequest(command="/thinking")
        )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    assert result["action"] == "thinking_toggled"
    assert result["expanded"] is True
    assert stream_tui.get_thinking_expanded() is True

    events = _drain(queue)
    snapshots = [
        e for e in events
        if e.get("type") == "reasoning" and e.get("snapshot") is True
    ]
    assert len(snapshots) == 1
    assert "hidden chain of thought part1 part2" in snapshots[0]["text"]


@pytest.mark.asyncio
async def test_thinking_collapse_does_not_emit_snapshot(monkeypatch):
    from RxyCode.RxyCode1_1_0 import api_server
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    queue = asyncio.Queue()
    recorder = StreamSessionRecorder([], run_id="run-collapse", user_message="hi")
    stream_tui = StreamTUI(queue, recorder=recorder)
    stream_tui.set_thinking_expanded(True)
    stream_tui.write_reasoning("visible")
    stream_tui.flush_stream_buffers()
    _drain(queue)

    proxy = api_server.APIProxyTUI()
    proxy.set_thinking_expanded(True)
    previous = dict(api_server._state)
    api_server._state.update({"agent": object(), "tui_proxy": proxy})
    monkeypatch.setattr("RxyCode.RxyCode1_1_0.utils.tui.get_tui", lambda: stream_tui)
    try:
        result = await api_server._execute_command(
            api_server.CommandRequest(command="/thinking")
        )
    finally:
        api_server._state.clear()
        api_server._state.update(previous)

    assert result["expanded"] is False
    events = _drain(queue)
    assert not [e for e in events if e.get("snapshot")]


def test_stream_tui_expand_emits_snapshot_directly():
    """StreamTUI.set_thinking_expanded(True) itself pushes recorder snapshot."""
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    queue = asyncio.Queue()
    recorder = StreamSessionRecorder([], run_id="r-direct", user_message="go")
    tui = StreamTUI(queue, recorder=recorder)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("accumulated-only-in-recorder")
    tui.flush_stream_buffers()
    _drain(queue)

    tui.set_thinking_expanded(True)
    events = _drain(queue)
    snaps = [e for e in events if e.get("type") == "reasoning" and e.get("snapshot")]
    assert len(snaps) == 1
    assert snaps[0]["text"] == "accumulated-only-in-recorder"


_SSE_ERROR_TEMPLATES = (
    "[Build incomplete: {detail}]",
    "[evidence failed: Tool {tool} did not complete: {status}]",
    "TimeoutError: {detail}",
    "Cancelled",
    "Synthesizer {detail}",
)

_DETAILS = (
    "task failed",
    "deploy timeout",
    "missing manifest",
    "grounding failed",
    "invalid JSON",
)

_TOOLS = ("read", "bash", "write", "grep", "patch")
_STATUSES = ("failed", "cancelled", "timeout", "error")


@pytest.mark.parametrize(
    "raw",
    [
        tpl.format(detail=detail, tool=tool, status=status)
        for tpl, detail, tool, status in itertools.product(
            _SSE_ERROR_TEMPLATES,
            _DETAILS,
            _TOOLS,
            _STATUSES,
        )
    ],
)
def test_sse_error_payload_maps_to_user_facing(raw: str):
    friendly = to_user_facing_error(raw)
    assert friendly
    assert "synthesizer" not in friendly.lower()
    assert "manifest" not in friendly.lower()
