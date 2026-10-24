"""Web reducer keeps each process-liveness result visible and deduplicated."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REDUCER = REPO / "apps" / "web" / "src" / "features" / "runs" / "eventReducer.ts"


def _reduce(events: list[dict]) -> dict:
    from tests.support.pgurl import bun_path

    bun = bun_path()
    assert bun, "bun is required for the shipped reducer contract"
    with tempfile.TemporaryDirectory(prefix="rxy-liveness-reducer-") as temp:
        driver = Path(temp) / "driver.ts"
        driver.write_text(
            "import { reduceEvents } from "
            + json.dumps(REDUCER.as_posix())
            + "\nconst events = "
            + json.dumps(events)
            + "\nconsole.log(JSON.stringify(reduceEvents(events, 'running', 0, 'run-1')))\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [bun, str(driver)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def _payload(*, seq: int = 1, probe_id: str = "probe-1", action: str = "continue") -> dict:
    return {
        "kind": "process_liveness",
        "probe_id": probe_id,
        "call_id": "call-1",
        "generation": 1,
        "pid": 123,
        "seq": seq,
        "elapsed_seconds": 15.0,
        "observation_seconds": 5.0,
        "cpu_start_percent": 4.0,
        "cpu_end_percent": 3.5,
        "io_start_bytes": 1024,
        "io_end_bytes": 4096,
        "process_count": 2,
        "action": action,
        "note": "模型判定继续",
        "text": "检查点结果：继续运行",
    }


def test_liveness_is_visible_evidence_not_thought_or_processing_placeholder() -> None:
    reduced = _reduce(
        [
            {"seq": 1, "type": "process.liveness", "payload": _payload()},
        ]
    )
    timeline = reduced["view"]["timeline"]
    assert timeline == [
        {
            "kind": "liveness",
            "seq": 1,
            "probeId": "probe-1",
            "probeSeq": 1,
            "callId": "call-1",
            "generation": 1,
            "pid": 123,
            "elapsedSeconds": 15.0,
            "observationSeconds": 5.0,
            "cpuStartPercent": 4.0,
            "cpuEndPercent": 3.5,
            "ioStartBytes": 1024,
            "ioEndBytes": 4096,
            "processCount": 2,
            "action": "continue",
            "note": "模型判定继续",
            "text": "检查点结果：继续运行",
            "invalid": False,
        }
    ]
    assert reduced["view"]["activity"] == ""
    assert reduced["intermediate"] == []


def test_replay_dedupes_by_probe_and_probe_seq() -> None:
    reduced = _reduce(
        [
            {"seq": 1, "type": "process.liveness", "payload": _payload(seq=1)},
            {"seq": 2, "type": "process.liveness", "payload": _payload(seq=1)},
            {"seq": 3, "type": "process.liveness", "payload": _payload(seq=2, action="stop")},
        ]
    )
    rows = [item for item in reduced["view"]["timeline"] if item["kind"] == "liveness"]
    assert [item["probeSeq"] for item in rows] == [1, 2]


def test_malformed_projection_is_unknown_and_not_hidden() -> None:
    reduced = _reduce(
        [
            {
                "seq": 1,
                "type": "process.liveness",
                "payload": {
                    "invalid": True,
                    "action": "unknown",
                    "note": "进程判活结果格式无效",
                    "text": "进程判活结果无法解析",
                },
            }
        ]
    )
    row = reduced["view"]["timeline"][0]
    assert row["kind"] == "liveness"
    assert row["action"] == "unknown"
    assert row["text"] == "进程判活结果无法解析"


def test_liveness_never_leaks_into_thought_or_final_answer() -> None:
    reduced = _reduce(
        [
            {"seq": 1, "type": "process.liveness", "payload": _payload()},
            {
                "seq": 2,
                "type": "assistant.final",
                "payload": {"text": "任务完成"},
            },
        ]
    )
    timeline = reduced["view"]["timeline"]
    assert [item["kind"] for item in timeline] == ["liveness", "final"]
    assert timeline[-1]["text"] == "任务完成"
    assert reduced["answer"] == "任务完成"
    assert reduced["intermediate"] == []
    assert not any(item["kind"] == "thinking" for item in timeline)
