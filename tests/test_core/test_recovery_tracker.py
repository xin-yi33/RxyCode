from __future__ import annotations

import asyncio

import pytest

from RxyCode.RxyCode1_1_0.recovery.error_recovery import retry_with_backoff
from RxyCode.RxyCode1_1_0.recovery.tracker import RecoveryKind, RecoveryState, RecoveryTracker


def test_recovery_tracker_emits_ordered_user_safe_lifecycle() -> None:
    events: list[dict[str, object]] = []
    tracker = RecoveryTracker(events.append)

    record = tracker.detect(
        source_call_id="call-1",
        recovery_kind=RecoveryKind.MODEL_RECOVERY,
        error_kind="tool_error",
        max_attempts=3,
    )
    assert tracker.state == RecoveryState.DETECTED
    tracker.analyze(record.recovery_id)
    tracker.attempt(
        record.recovery_id,
        attempt=1,
        strategy="corrected_arguments",
        replacement_call_id="call-2",
        display_summary="正在使用修正后的参数再次调用工具",
    )
    assert tracker.state == RecoveryState.RETRYING
    tracker.resolve(record.recovery_id, attempts=1, display_summary="工具调用已恢复")

    assert [event["kind"] for event in events] == [
        "started",
        "analyzing",
        "attempt",
        "resolved",
    ]
    assert [event["seq"] for event in events] == [1, 2, 3, 4]
    assert all(event["event_id"] for event in events)
    assert all(event["timestamp"] for event in events)
    assert tracker.state == RecoveryState.RECOVERED
    assert tracker.active is None


def test_recovery_tracker_exhausted_keeps_final_error_outcome() -> None:
    events: list[dict[str, object]] = []
    tracker = RecoveryTracker(events.append)
    record = tracker.detect(
        source_call_id="call-9",
        recovery_kind=RecoveryKind.TRANSPORT_RETRY,
        error_kind="timeout",
        max_attempts=2,
    )
    tracker.attempt(
        record.recovery_id,
        attempt=1,
        strategy="same_tool",
        display_summary="网络错误，正在重试原工具",
    )
    tracker.exhaust(
        record.recovery_id,
        attempts=2,
        final_error="工具响应超时，已达到重试上限",
    )

    assert tracker.state == RecoveryState.EXHAUSTED
    assert tracker.active is None
    assert events[-1]["kind"] == "exhausted"
    assert events[-1]["final_error"] == "工具响应超时，已达到重试上限"


@pytest.mark.asyncio
async def test_retry_with_backoff_notifies_only_transient_failures() -> None:
    transient_attempts = 0
    transient_notifications: list[tuple[int, str]] = []

    async def transient() -> str:
        nonlocal transient_attempts
        transient_attempts += 1
        if transient_attempts < 3:
            raise ConnectionError("temporary")
        return "ok"

    result = await retry_with_backoff(
        transient,
        max_attempts=3,
        wait_multiplier=0,
        on_retry=lambda attempt, exc: transient_notifications.append(
            (attempt, type(exc).__name__)
        ),
    )
    assert result == "ok"
    assert transient_notifications == [(1, "ConnectionError"), (2, "ConnectionError")]

    permanent_notifications: list[tuple[int, str]] = []

    async def permanent() -> str:
        raise ValueError("bad arguments")

    with pytest.raises(ValueError):
        await retry_with_backoff(
            permanent,
            max_attempts=3,
            wait_multiplier=0,
            on_retry=lambda attempt, exc: permanent_notifications.append(
                (attempt, type(exc).__name__)
            ),
        )
    assert permanent_notifications == []
