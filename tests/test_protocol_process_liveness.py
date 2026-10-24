"""Typed process-liveness details remain additive and secret-tight."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protocol.notifications import ProcessLivenessDetails, ProgressUpdate


def _details(**overrides):
    values = {
        "kind": "process_liveness",
        "probe_id": "probe-1",
        "call_id": "call-1",
        "generation": 2,
        "pid": 4321,
        "seq": 3,
        "elapsed_seconds": 15.5,
        "observation_seconds": 5.0,
        "cpu_start_percent": 1.25,
        "cpu_end_percent": 2.5,
        "io_start_bytes": 100,
        "io_end_bytes": 2048,
        "process_count": 4,
        "action": "continue",
        "note": "CPU 与 IO 仍有活动，继续观察",
    }
    values.update(overrides)
    return values


def test_progress_carries_one_typed_liveness_result() -> None:
    update = ProgressUpdate(
        session_id="session-1",
        text="检查点 3：继续运行",
        details=_details(),
    )
    dumped = update.model_dump(mode="json")
    assert dumped["details"]["kind"] == "process_liveness"
    assert dumped["details"]["observation_seconds"] == 5.0
    assert dumped["details"]["action"] == "continue"
    assert "command" not in dumped["details"]
    assert "stdout" not in dumped["details"]


def test_progress_without_details_keeps_legacy_shape() -> None:
    update = ProgressUpdate(session_id="session-1", text="思考中...")
    assert update.details is None


def test_liveness_details_forbid_untyped_secret_bearing_fields() -> None:
    with pytest.raises(ValidationError):
        ProcessLivenessDetails.model_validate(
            _details(command="token=secret", stdout="raw output")
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "heartbeat"),
        ("action", "kill"),
        ("observation_seconds", -1),
        ("pid", 0),
        ("seq", 0),
        ("io_end_bytes", -1),
        ("elapsed_seconds", float("inf")),
        ("observation_seconds", float("nan")),
        ("cpu_end_percent", float("-inf")),
    ],
)
def test_liveness_details_reject_invalid_decisions(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ProcessLivenessDetails.model_validate(_details(**{field: value}))
