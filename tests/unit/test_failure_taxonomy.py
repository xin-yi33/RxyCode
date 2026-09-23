"""Card B: three-class failure surfaces (retry / tool_result / event/error)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    FirstTokenTimeoutError,
    StreamConnectTimeoutError,
    StreamIdleTimeoutError,
    _is_transport_retryable,
)
from RxyCode.RxyCode1_1_0.recovery.error_recovery import (
    ErrorKind,
    classify_error,
    classify_tool_status,
    failure_surface,
    should_emit_event_error,
)


def test_429_is_retry_surface_not_event_error_until_exhausted():
    resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    exc = httpx.HTTPStatusError("rate", request=resp.request, response=resp)
    assert classify_error(exc) == ErrorKind.TRANSIENT
    assert failure_surface(exc=exc) == "event/retry"
    assert should_emit_event_error(exc, retries_exhausted=False) is False
    assert should_emit_event_error(exc, retries_exhausted=True) is True
    assert _is_transport_retryable(exc) is True


def test_auth_is_hard_event_error():
    resp = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    exc = httpx.HTTPStatusError("auth", request=resp.request, response=resp)
    assert classify_error(exc) == ErrorKind.PERMANENT
    assert failure_surface(exc=exc) == "event/error"
    assert should_emit_event_error(exc) is True
    assert _is_transport_retryable(exc) is False


def test_fired_idle_clock_hard_first_token_retryable():
    # 2026-09-23 策略变更（用户报告：网络不好时模型超时，不确定有没有
    # retry）：FirstTokenTimeoutError 改为可重试——首包时钟触发时还未发出
    # 任何内容，重试不产生重复（_raw_stream 重试分支另有 not got_useful
    # 双保险）。StreamIdleTimeoutError 仍禁止重试（流中段重试会重复已发
    # 内容）。classify_error / failure_surface 的外层分类不变。
    ttft = FirstTokenTimeoutError("no first event")
    idle = StreamIdleTimeoutError("stream died")
    assert classify_error(ttft) == ErrorKind.PERMANENT
    assert classify_error(idle) == ErrorKind.PERMANENT
    assert failure_surface(exc=ttft) == "event/error"
    assert _is_transport_retryable(ttft) is True  # 2026-09-23: 曾断言 False
    assert _is_transport_retryable(idle) is False
    # 普通 TimeoutError 伪装不成可重试（无论是本身还是经 __cause__ 链）。
    wrapped = RuntimeError("sdk")
    wrapped.__cause__ = TimeoutError("inner")
    assert _is_transport_retryable(wrapped) is False
    clock = FirstTokenTimeoutError("ttft")
    clock.__cause__ = TimeoutError("wait_for")
    # 精确类型的首包时钟无论 __cause__ 如何都可重试。
    assert _is_transport_retryable(clock) is True


def test_tool_error_is_tool_result_never_event_error():
    assert classify_tool_status("error") == ErrorKind.BUSINESS
    assert failure_surface(tool_status="error") == "tool_result"
    assert should_emit_event_error(tool_status="error") is False
    assert failure_surface(tool_status="success") == "none"


def test_generic_timeout_is_not_transport_retry():
    assert classify_error(TimeoutError("slow")) == ErrorKind.PERMANENT
    assert _is_transport_retryable(TimeoutError("slow")) is False
    assert _is_transport_retryable(httpx.ConnectError("boom")) is True
    assert _is_transport_retryable(httpx.ConnectTimeout("handshake")) is True
    assert _is_transport_retryable(httpx.ReadTimeout("idle")) is False
    assert _is_transport_retryable(StreamConnectTimeoutError("handshake")) is True


class _HangOnceStreamLLM:
    """First astream() hangs forever (first-token clock fires); second yields."""

    def __init__(self):
        self.calls = 0

    def astream(self, messages, **kwargs):
        self.calls += 1
        call_no = self.calls

        async def _gen():
            if call_no == 1:
                await asyncio.sleep(60)  # 永不产出，逼首包时钟触发
                yield "unreachable"
            else:
                yield "chunk-1"

        return _gen()


async def test_open_stream_retries_first_token_timeout_then_succeeds():
    """2026-09-23: 首包超时走既有 transport 重试循环（用户报告：网络不好时
    模型超时，不确定有没有 retry）。第一次挂起触发首包时钟，第二次成功。"""
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    inner = _HangOnceStreamLLM()
    tracked = UsageTrackingLLM(inner, first_token_timeout=0.2)
    first, _rest = await tracked._open_stream_with_retry([], {})
    assert first == "chunk-1"
    assert inner.calls == 2
