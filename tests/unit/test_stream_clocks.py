"""Unit clocks for Card A: connect / idle / HTTP timeout, no SDK 600."""

from __future__ import annotations

import httpx
import pytest

from RxyCode.RxyCode1_1_0.core.agent_v2 import (
    STREAM_CONNECT_TIMEOUT_DEFAULT_SECONDS,
    STREAM_IDLE_TIMEOUT_CAP_SECONDS,
    STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS,
    _provider_http_timeout,
    _resolve_connect_timeout,
    _resolve_first_token_timeout,
    _resolve_stream_clocks,
    _resolve_stream_idle_timeout,
)


def test_defaults_are_thinking_friendly():
    assert STREAM_CONNECT_TIMEOUT_DEFAULT_SECONDS == 20.0
    assert STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS == 180.0
    assert STREAM_IDLE_TIMEOUT_CAP_SECONDS == 300.0
    assert STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS > 30.0
    assert STREAM_IDLE_TIMEOUT_CAP_SECONDS < 600.0


def test_http_timeout_never_uses_sdk_600():
    timeout = _provider_http_timeout(20.0, 180.0)
    assert isinstance(timeout, httpx.Timeout)
    assert float(timeout.connect) == 20.0
    assert float(timeout.read) == 180.0
    assert float(timeout.read) != 600.0


def test_resolve_stream_clocks_default():
    connect, idle, first, http_timeout = _resolve_stream_clocks({})
    assert connect == 20.0
    assert idle == 180.0
    assert first == 180.0
    assert float(http_timeout.read) == 180.0


def test_explicit_short_timeout_shrinks_idle_for_tests():
    connect, idle, first, http_timeout = _resolve_stream_clocks({"timeout": 1.0})
    assert connect == 1.0
    assert idle == 1.0
    assert first == 1.0
    assert float(http_timeout.read) == 1.0


def test_first_token_follows_idle_when_idle_overridden():
    connect, idle, first, http_timeout = _resolve_stream_clocks(
        {"timeout": 90, "stream_idle_timeout": 240}
    )
    assert connect == 20.0
    assert idle == 240.0
    assert first == 240.0
    assert float(http_timeout.read) == 240.0


def test_stream_idle_override_independent_of_legacy_ninety():
    assert _resolve_stream_idle_timeout(90, 240) == 240.0
    assert _resolve_first_token_timeout(None, 45) == 45.0
    assert _resolve_connect_timeout(None, 8) == 8.0


@pytest.mark.unit
def test_keepalive_is_alive_not_useful():
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2

    agent = object.__new__(AgentV2)
    empty = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="", reasoning_content="", tool_calls=None)
            )
        ]
    )
    assert agent._stream_chunk_is_useful(empty) is False
    assert agent._stream_chunk_is_alive(empty) is True


def test_force_close_walks_openai_httpx_client():
    from types import SimpleNamespace

    from RxyCode.RxyCode1_1_0.core.agent_v2 import _force_close_provider_stream

    closed: list[str] = []
    httpx_client = SimpleNamespace(close=lambda: closed.append("httpx"))
    openai_client = SimpleNamespace(_client=httpx_client, close=lambda: closed.append("openai"))
    assert _force_close_provider_stream(openai_client) is True
    assert "openai" in closed
    assert "httpx" in closed


def test_force_close_none_is_false():
    from RxyCode.RxyCode1_1_0.core.agent_v2 import _force_close_provider_stream

    assert _force_close_provider_stream(None) is False


def test_force_close_schedules_async_aclose_on_stream_loop():
    import asyncio
    import threading

    from RxyCode.RxyCode1_1_0.core.agent_v2 import (
        TOOL_ARGUMENT_STREAM_IDLE_SECONDS,
        STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS,
        _force_close_provider_stream,
    )

    assert TOOL_ARGUMENT_STREAM_IDLE_SECONDS <= STREAM_IDLE_TIMEOUT_DEFAULT_SECONDS

    closed: list[str] = []

    class Httpxish:
        async def aclose(self):
            closed.append("aclose")

    async def run() -> None:
        loop = asyncio.get_running_loop()
        started = threading.Event()

        def from_timer() -> None:
            started.wait(1)
            _force_close_provider_stream(Httpxish(), loop=loop)

        worker = threading.Thread(target=from_timer)
        worker.start()
        started.set()
        worker.join(2)
        await asyncio.sleep(0.05)
        assert closed == ["aclose"]

    asyncio.run(run())
