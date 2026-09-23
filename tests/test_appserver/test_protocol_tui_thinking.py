"""ProtocolTui thinking expand emits reasoning to the client."""

from __future__ import annotations

import time

from appserver.tui import ProtocolTui
from protocol.notifications import ReasoningSnapshot


def test_write_turn_liveness_emits_reasoning_snapshot() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_turn_liveness("思考中...")
    assert len(emitted) == 1
    assert isinstance(emitted[0], ReasoningSnapshot)
    assert emitted[0].text == "思考中..."
    assert emitted[0].snapshot is False


def test_write_reasoning_always_emits_chain() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("hidden thought")
    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert snapshots and snapshots[0].text == "hidden thought"
    tui.write_reasoning(" more")
    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert [item.text for item in snapshots] == ["hidden thought", " more"]


def test_write_reasoning_emits_when_expanded() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(True)
    tui.write_reasoning("visible thought")
    assert len(emitted) == 1
    assert isinstance(emitted[0], ReasoningSnapshot)
    assert emitted[0].text == "visible thought"
    assert emitted[0].snapshot is False


def test_expand_mid_run_still_has_live_chain() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("part1")
    tui.write_reasoning(" part2")
    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert [item.text for item in snapshots] == ["part1", " part2"]

    tui.set_thinking_expanded(True)
    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert snapshots[-1].text == "part1 part2"
    assert snapshots[-1].snapshot is True


def test_collapsed_reasoning_still_streams_chain_chunks() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("first")
    for _ in range(63):
        tui.write_reasoning("chunk")
    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert snapshots[0].text == "first"
    assert len(snapshots) >= 64


def test_collapsed_reasoning_time_liveness_is_rate_limited(monkeypatch) -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    clock = iter((100.0, 100.0, 102.1, 102.2, 102.3))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))

    tui.write_reasoning("first")
    tui.write_reasoning("second")
    tui.write_reasoning("third")

    snapshots = [item for item in emitted if isinstance(item, ReasoningSnapshot)]
    assert [item.text for item in snapshots] == ["first", "second", "third"]
