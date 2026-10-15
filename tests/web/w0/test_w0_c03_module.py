"""WEB-W0-C03. Protocol events round-trip through the shipped models."""
from __future__ import annotations

from pathlib import Path

from core.session import notification_to_sse_event
from protocol.notifications import FinalAnswer, RecoveryStarted

REPO = Path(__file__).resolve().parents[3]


def test_w0_c03_integration():
    """An existing final event keeps its type and schema version for the old client."""
    notice = FinalAnswer(
        session_id="ses-c03",
        run_id="run-c03",
        text="done",
        session_schema_version=4,
    )
    event = notification_to_sse_event(notice)
    assert event is not None
    assert event["type"] == "final"
    assert event["run_id"] == "run-c03"
    assert event["session_schema_version"] == 4
    restored = FinalAnswer.model_validate(notice.model_dump())
    assert restored.method == "event/final"
    assert restored.session_schema_version == 4

    started = RecoveryStarted(
        session_id="ses-c03",
        run_id="run-c03",
        recovery_id="rec-1",
        event_id="evt-1",
        seq=1,
        timestamp="2026-10-16T00:00:00Z",
        source_call_id="call-1",
        recovery_kind="transport_retry",
        error_kind="timeout",
        max_attempts=2,
    )
    again = RecoveryStarted.model_validate(started.model_dump())
    assert again.method == "event/recovery_started"
    assert again.recovery_kind == "transport_retry"
    assert again.seq == 1
    schema = (REPO / "protocol" / "schema.json").read_text(encoding="utf-8")
    assert "event/final" in schema
    assert "event/recovery_started" in schema
