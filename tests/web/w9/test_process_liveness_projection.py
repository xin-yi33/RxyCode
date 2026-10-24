"""Process-liveness details project as evidence rows, never child text."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for _name in ("rxycode-worker", "rxycode-protocol"):
    _path = REPO / "packages" / _name / "src"
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from rxycode_worker import drain  # noqa: E402


DETAILS = {
    "kind": "process_liveness",
    "probe_id": "probe-1",
    "call_id": "call-1",
    "generation": 1,
    "pid": 42,
    "seq": 2,
    "elapsed_seconds": 10.0,
    "observation_seconds": 5.0,
    "cpu_start_percent": 3.0,
    "cpu_end_percent": 2.0,
    "io_start_bytes": 100,
    "io_end_bytes": 200,
    "process_count": 2,
    "action": "continue",
    "note": "任务仍有 IO 活动",
}


def test_projection_uses_only_fixed_liveness_fields() -> None:
    rows = drain._projection_rows(
        "event/progress",
        {
            "text": "检查点 2：继续运行",
            "details": {
                **DETAILS,
                "command": "cat secret",
                "stdout": "secret output",
            },
        },
        {},
        run_id="run-1",
    )
    assert rows == [
        (
            "process.liveness",
            {
                **DETAILS,
                "text": "检查点 2：继续运行",
            },
        )
    ]
    encoded = str(rows).lower()
    assert "command" not in encoded
    assert "stdout" not in encoded


def test_malformed_liveness_is_explicit_unknown() -> None:
    rows = drain._projection_rows(
        "event/progress",
        {"text": "检查点 3", "details": {"kind": "process_liveness", "action": "kill"}},
        {},
        run_id="run-1",
    )
    assert rows[0][0] == "process.liveness"
    assert rows[0][1]["action"] == "unknown"
    assert rows[0][1]["invalid"] is True


def test_plain_progress_keeps_legacy_status_projection() -> None:
    rows = drain._projection_rows(
        "event/progress",
        {"text": "Thinking... (round 2)", "intermediate": False},
        {},
        run_id="run-1",
    )
    assert rows == [
        (
            "assistant.delta",
            {
                "text": "Thinking... (round 2)",
                "intermediate": True,
                "channel": "status",
            },
        )
    ]
