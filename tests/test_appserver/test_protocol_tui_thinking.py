"""ProtocolTui thinking expand emits reasoning to the client."""

from __future__ import annotations

from appserver.tui import ProtocolTui
from protocol.notifications import ReasoningSnapshot


def test_write_reasoning_silent_when_collapsed() -> None:
    emitted: list[object] = []
    tui = ProtocolTui("s1", emitted.append)
    tui.set_thinking_expanded(False)
    tui.write_reasoning("hidden thought")
    assert emitted == []


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
    assert emitted == []

    tui.set_thinking_expanded(True)
    assert len(emitted) == 1
    assert isinstance(emitted[0], ReasoningSnapshot)
    assert emitted[0].text == "part1 part2"
    assert emitted[0].snapshot is True
