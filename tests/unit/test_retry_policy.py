"""Card D: retry only short connect/429 clocks, never idle.

2026-09-23 策略变更（用户报告：网络不好时模型超时，不确定有没有 retry）：
首包时钟（FirstTokenTimeoutError）改为可重试——触发时尚未发出任何内容，
重试不产生重复；空闲时钟仍禁止（流中段重试会重复已发内容）。
"""

from __future__ import annotations

import httpx

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    STREAM_TRANSPORT_RETRY_MAX,
    FirstTokenTimeoutError,
    StreamConnectTimeoutError,
    StreamIdleTimeoutError,
    _is_transport_retryable,
)
from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind, classify_error


def test_model_and_tool_retry_share_opencode_clock():
    from RxyCode.RxyCode1_1_0.recovery.error_recovery import (
        MODEL_RETRY_ATTEMPTS,
        MODEL_RETRY_MAX,
        opencode_retry_delay_seconds,
    )

    assert MODEL_RETRY_MAX == STREAM_TRANSPORT_RETRY_MAX == 5
    assert MODEL_RETRY_ATTEMPTS == 6
    assert opencode_retry_delay_seconds(1, random_unit=lambda: 0) == 2.0
    assert opencode_retry_delay_seconds(2, random_unit=lambda: 0) == 4.0
    assert opencode_retry_delay_seconds(3, random_unit=lambda: 0) == 8.0
    assert opencode_retry_delay_seconds(4, random_unit=lambda: 0) == 16.0
    assert opencode_retry_delay_seconds(5, random_unit=lambda: 0) == 30.0
    assert opencode_retry_delay_seconds(1, random_unit=lambda: 1) == 2.5
    assert opencode_retry_delay_seconds(1, multiplier=0.01, random_unit=lambda: 0) == 0.02


def test_short_connect_is_retryable_idle_is_not():
    assert STREAM_TRANSPORT_RETRY_MAX == 5
    assert classify_error(StreamConnectTimeoutError("handshake")) == ErrorKind.TRANSIENT
    assert _is_transport_retryable(StreamConnectTimeoutError("handshake")) is True
    assert _is_transport_retryable(httpx.ConnectTimeout("handshake")) is True
    assert _is_transport_retryable(httpx.ConnectError("reset")) is True
    req = httpx.Request("POST", "http://x")
    rate = httpx.HTTPStatusError(
        "rate", request=req, response=httpx.Response(429, request=req)
    )
    assert _is_transport_retryable(rate) is True


def test_long_clocks_are_not_retryable():
    assert classify_error(TimeoutError("slow")) == ErrorKind.PERMANENT
    assert _is_transport_retryable(TimeoutError("slow")) is False
    assert _is_transport_retryable(httpx.ReadTimeout("idle")) is False
    # 2026-09-23: 首包时钟可重试（见模块 docstring）；曾断言 False。
    assert _is_transport_retryable(FirstTokenTimeoutError("ttft")) is True
    assert _is_transport_retryable(StreamIdleTimeoutError("idle")) is False
    clock = FirstTokenTimeoutError("ttft")
    clock.__cause__ = TimeoutError("wait_for")
    # 精确类型首包时钟无论 __cause__ 如何都可重试。
    assert _is_transport_retryable(clock) is True
    from pybreaker import CircuitBreakerError

    wrapped = CircuitBreakerError("still open")
    wrapped.__cause__ = ConnectionError("raw provider down")
    assert _is_transport_retryable(wrapped) is False
    assert classify_error(wrapped) == ErrorKind.PERMANENT
