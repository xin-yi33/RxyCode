"""Eval/module fixture for Card A stream clocks."""

from __future__ import annotations

import json
from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    STREAM_CONNECT_TIMEOUT_DEFAULT_SECONDS,
    STREAM_IDLE_TIMEOUT_CAP_SECONDS,
    STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "stream-clocks.json"


def test_stream_clock_eval_fixture_matches_runtime():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = payload["required_after"]
    assert payload["kind"] == "trace-fixture"
    assert STREAM_CONNECT_TIMEOUT_DEFAULT_SECONDS == required["connect_s"]
    assert STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS == required["idle_default_s"]
    assert STREAM_IDLE_TIMEOUT_CAP_SECONDS == required["idle_cap_s"]
    assert STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS != required["first_token_cap_s_forbidden"]
    assert STREAM_IDLE_TIMEOUT_CAP_SECONDS < required["sdk_default_s_forbidden"]
    assert required["stall_means"] == "worker_heartbeat_dead"
