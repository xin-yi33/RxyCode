"""ProtocolTui thinking expand emits reasoning to the client."""

from __future__ import annotations

import time

from appserver.tui import ProtocolTui
from protocol.notifications import ProgressUpdate, ReasoningSnapshot


def test_write_turn_liveness_emits_reasoning_snapshot() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_turn_liveness("思考中...")
    assert len(emitted) == 1
    assert isinstance(emitted[0], ReasoningSnapshot)
    assert emitted[0].text == "思考中..."
    assert emitted[0].snapshot is False


def test_write_reasoning_silent_when_collapsed() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("hidden thought")
    # Body stays collapsed, but the first reasoning chunk must still produce a
    # liveness event so the 120s watchdog does not treat thinking as a stall.
    assert len(emitted) == 1
    assert isinstance(emitted[0], ProgressUpdate)
    assert "思考" in emitted[0].text
    tui.write_reasoning(" more")
    assert len(emitted) == 1


def test_write_reasoning_emits_when_expanded() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(True)
    tui.write_reasoning("visible thought")
    assert len(emitted) == 1
    assert isinstance(emitted[0], ReasoningSnapshot)
    assert emitted[0].text == "visible thought"
    assert emitted[0].snapshot is False


def test_expand_mid_run_pushes_accumulated_snapshot() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("part1")
    tui.write_reasoning(" part2")
    assert all(not isinstance(item, ReasoningSnapshot) for item in emitted)

    tui.set_thinking_expanded(True)
    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert len(snapshots) == 1
    assert snapshots[0].text == "part1 part2"
    assert snapshots[0].snapshot is True


def test_collapsed_reasoning_emits_sparse_liveness_without_text() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("first")
    assert len(emitted) == 1

    for _ in range(63):
        tui.write_reasoning("chunk")

    progress = [item for item in emitted if isinstance(item, ProgressUpdate)]
    assert len(progress) == 2
    assert "reasoning active" in progress[-1].text
    assert "first" not in progress[-1].text


def test_collapsed_reasoning_time_liveness_is_rate_limited(monkeypatch) -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    clock = iter((100.0, 100.0, 102.1, 102.2, 102.3))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))

    tui.write_reasoning("first")
    tui.write_reasoning("second")
    tui.write_reasoning("third")

    progress = [item for item in emitted if isinstance(item, ProgressUpdate)]
    assert len(progress) == 2
