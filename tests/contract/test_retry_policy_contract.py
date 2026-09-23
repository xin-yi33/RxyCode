"""Contract: Card D retry hangs on short clocks only."""

from __future__ import annotations

import inspect

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    AgentV2,
    STREAM_TRANSPORT_RETRY_MAX,
    _is_transport_retryable,
)


def test_raw_stream_does_not_retry_first_token_clock():
    source = inspect.getsource(AgentV2._raw_stream)
    assert "first_token_retries_left" not in source
    assert "StreamConnectTimeoutError" in source
    assert "_stream_transient_retry_max" in source
    assert STREAM_TRANSPORT_RETRY_MAX == 5
    assert "_is_transport_retryable(exc)" in source
    assert "CircuitBreakerError" in inspect.getsource(_is_transport_retryable)
