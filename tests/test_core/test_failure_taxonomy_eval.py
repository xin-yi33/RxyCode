"""Eval/module fixture for Card B failure taxonomy."""

from __future__ import annotations

import json
from pathlib import Path

from RxyCode.RxyCode1_1_0.core.agent_v2 import FirstTokenTimeoutError, _is_transport_retryable
from RxyCode.RxyCode1_1_0.recovery.error_recovery import failure_surface

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "failure-taxonomy.json"


def test_failure_taxonomy_eval_fixture_matches_runtime():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = payload["required_after"]
    assert payload["kind"] == "trace-fixture"
    import httpx

    rate = httpx.HTTPStatusError(
        "rate",
        request=httpx.Request("POST", "http://x"),
        response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
    )
    assert failure_surface(exc=rate) == required["transient_surface"]
    assert failure_surface(tool_status="error") == required["business_surface"]
    assert failure_surface(exc=FirstTokenTimeoutError("x")) == required["hard_surface"]
    assert (
        _is_transport_retryable(FirstTokenTimeoutError("x"))
        is required["first_token_timeout_retryable"]
    )
