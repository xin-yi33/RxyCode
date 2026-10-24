"""HTTP/SSE StreamTUI forwards one complete process-liveness row."""

from __future__ import annotations

import asyncio

from protocol.notifications import ProcessLivenessDetails


DETAILS = {
    "kind": "process_liveness",
    "probe_id": "probe-http",
    "call_id": "call-http",
    "generation": 4,
    "pid": 321,
    "seq": 1,
    "elapsed_seconds": 20.0,
    "observation_seconds": 5.0,
    "cpu_start_percent": 8.0,
    "cpu_end_percent": 7.5,
    "io_start_bytes": 10_000,
    "io_end_bytes": 12_000,
    "process_count": 2,
    "action": "stop",
    "note": "模型判定任务已完成",
}


def test_stream_tui_emits_details_without_recording_thought() -> None:
    from RxyCode.RxyCode1_1_0.api_server import StreamSessionRecorder, StreamTUI

    async def run() -> None:
        queue = asyncio.Queue()
        history = []
        recorder = StreamSessionRecorder(
            history,
            run_id="run-liveness",
            user_message="run",
        )
        tui = StreamTUI(queue, recorder=recorder)
        tui.write_progress("检查点 1：建议停止", details=DETAILS)
        event = queue.get_nowait()
        assert event["type"] == "progress"
        assert event["text"] == "检查点 1：建议停止"
        assert event["details"] == ProcessLivenessDetails.model_validate(
            DETAILS
        ).model_dump(mode="json")
        assert event["intermediate"] is True
        assert recorder.thinking_content == ""

    asyncio.run(run())


def test_api_proxy_accepts_the_same_optional_details() -> None:
    from RxyCode.RxyCode1_1_0.api_server import APIProxyTUI

    proxy = APIProxyTUI()
    proxy.write_progress("检查点 1：继续运行", details=DETAILS)
    assert "检查点 1：继续运行" in proxy.get_and_clear()[0]
