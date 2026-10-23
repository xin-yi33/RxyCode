"""WEB-W8 S3. Shared Harness pause point: checkpoint message codec and the
pause-aware whole-turn budget (core/harness_checkpoint.py).

Unit layer, no database and no sandbox. A parked turn restores the exact
message history it had; waiting time never counts as execution time; a
restored budget keeps what was already spent; extensions are bounded.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ChatMessage, HumanMessage, SystemMessage, ToolMessage

from RxyCode.RxyCode1_1_0.core.harness_checkpoint import (
    TurnBudget,
    decode_messages,
    encode_messages,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_w8_s3_checkpoint_round_trips_the_tool_loop_history() -> None:
    history = [
        SystemMessage(content="prefix"),
        HumanMessage(content=[{"type": "text", "text": "fix the test"}]),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {"command": "pytest -q"}, "id": "call_1", "type": "tool_call"}],
        ),
        ToolMessage(content="[approval pending]", tool_call_id="call_1", name="bash"),
        ToolMessage(content="3 passed", tool_call_id="call_2"),
    ]
    rows = encode_messages(history)
    restored = decode_messages(rows)
    assert [type(m) for m in restored] == [type(m) for m in history]
    assert restored[1].content == history[1].content
    assert restored[2].tool_calls[0]["id"] == "call_1"
    assert restored[2].tool_calls[0]["args"] == {"command": "pytest -q"}
    assert restored[3].tool_call_id == "call_1" and restored[3].name == "bash"
    assert restored[4].name is None
    assert encode_messages(restored) == rows


def test_w8_s3_checkpoint_fails_closed_on_unsupported_or_non_json() -> None:
    with pytest.raises(TypeError):
        encode_messages([ChatMessage(role="x", content="y")])
    with pytest.raises(TypeError):
        encode_messages([HumanMessage(content=[{"type": "text", "text": "x", "meta": object()}])])
    with pytest.raises(ValueError):
        decode_messages([{"kind": "function", "content": ""}])


def test_w8_s3_budget_excludes_parked_time() -> None:
    clock = _Clock()
    budget = TurnBudget(limit_seconds=60.0, clock=clock)
    budget.start()
    clock.now += 40.0
    budget.pause()
    clock.now += 500.0  # waiting for a human approval
    budget.resume()
    clock.now += 19.0
    assert budget.elapsed() == pytest.approx(59.0)
    assert not budget.exhausted()
    clock.now += 1.0
    assert budget.exhausted()


def test_w8_s3_restore_keeps_spent_time_and_does_not_count_the_gap() -> None:
    clock = _Clock()
    budget = TurnBudget(limit_seconds=100.0, clock=clock)
    budget.start()
    clock.now += 70.0
    checkpoint = budget.snapshot()
    assert checkpoint["consumed_seconds"] == pytest.approx(70.0)

    later = _Clock()
    later.now = 9_000_000.0  # restart, much later
    restored = TurnBudget.restore(checkpoint, clock=later)
    restored.start()
    assert restored.elapsed() == pytest.approx(70.0)
    later.now += 29.0
    assert not restored.exhausted()
    later.now += 1.0
    assert restored.exhausted()


def test_w8_s3_extensions_are_bounded_by_count_and_hard_cap() -> None:
    budget = TurnBudget(limit_seconds=100.0, max_extensions=2, hard_cap_seconds=220.0)
    assert budget.extend(60.0)
    assert budget.limit_seconds == pytest.approx(160.0)
    assert not budget.extend(61.0)  # would pass the hard cap
    assert budget.extend(60.0)
    assert not budget.extend(1.0)  # count exhausted
    assert budget.extensions_used == 2 and budget.limit_seconds == pytest.approx(220.0)
    assert not TurnBudget(limit_seconds=10.0).extend(5.0)
