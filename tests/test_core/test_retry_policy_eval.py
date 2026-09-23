"""Eval/module fixture for Card D retry policy."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    STREAM_TRANSPORT_RETRY_MAX,
    FirstTokenTimeoutError,
    StreamConnectTimeoutError,
    _is_transport_retryable,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "evals" / "baselines" / "retry-policy.json"


def test_retry_policy_eval_fixture_matches_runtime():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    required = payload["required_after"]
    assert STREAM_TRANSPORT_RETRY_MAX == required["transport_retry_max"]
    assert (
        _is_transport_retryable(StreamConnectTimeoutError("handshake"))
        is required["connect_timeout_retryable"]
    )
    assert (
        _is_transport_retryable(httpx.ReadTimeout("idle"))
        is required["read_timeout_retryable"]
    )
    assert (
        _is_transport_retryable(FirstTokenTimeoutError("ttft"))
        is required["first_token_timeout_retryable"]
    )
