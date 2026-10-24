"""ProtocolTui forwards process-liveness details without text coalescing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from appserver.tui import ProtocolTui
from protocol.notifications import ProcessLivenessDetails, ProgressUpdate


DETAILS = {
    "kind": "process_liveness",
    "probe_id": "probe-1",
    "call_id": "call-1",
    "generation": 1,
    "pid": 99,
    "seq": 2,
    "elapsed_seconds": 12.0,
    "observation_seconds": 5.0,
    "cpu_start_percent": 0.5,
    "cpu_end_percent": 0.25,
    "io_start_bytes": 4096,
    "io_end_bytes": 8192,
    "process_count": 3,
    "action": "unknown",
    "note": "证据不足，交由模型判定",
}


class _MustNotCoalesce:
    async def push(self, *_args, **_kwargs) -> None:
        raise AssertionError("typed liveness results must bypass text coalescing")

    def push_sync(self, *_args, **_kwargs) -> bool:
        raise AssertionError("typed liveness results must bypass text coalescing")

    def flush_submit_sync(self) -> None:
        return None


def test_protocol_tui_emits_typed_liveness_progress() -> None:
    emitted = []
    tui = ProtocolTui("session-1", emitted.append)
    tui.set_coalescer(_MustNotCoalesce())

    tui.write_progress("检查点 2：无法判定", details=DETAILS)

    assert len(emitted) == 1
    event = emitted[0]
    assert isinstance(event, ProgressUpdate)
    assert event.details == ProcessLivenessDetails.model_validate(DETAILS)
    assert event.text == "检查点 2：无法判定"


def test_protocol_tui_keeps_plain_progress_compatible() -> None:
    emitted = []
    tui = ProtocolTui("session-1", emitted.append)
    tui.write_progress("Analyzing your request...")
    assert emitted == [
        ProgressUpdate(session_id="session-1", text="Analyzing your request...")
    ]


def test_protocol_tui_does_not_turn_untyped_details_into_liveness() -> None:
    emitted = []
    tui = ProtocolTui("session-1", emitted.append)
    with pytest.raises(ValidationError):
        tui.write_progress("not evidence", details={**DETAILS, "command": "secret"})
    assert emitted == []
