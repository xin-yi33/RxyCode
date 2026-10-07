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
    # 2026-10-01：路由到最新 7 次连接重试；旧的 5 次断言（== 5）已废弃不再引用。
    assert STREAM_TRANSPORT_RETRY_MAX == 7
    assert "_is_transport_retryable(exc)" in source
    assert "CircuitBreakerError" in inspect.getsource(_is_transport_retryable)


def test_default_config_routes_to_latest_retry_constant():
    """默认发货配置不得覆盖最新重试常量（2026-10-01 回归门禁）。

    废弃代码（2026-09-23 版）：config/settings.py 默认曾携带
    ``llm.transport_retries: 5``，经 cfg 优先逻辑静默把 7 次压回 5 次。
    现默认配置必须不含该 key，使 ``_transport_retry_max`` /
    ``_stream_transient_retry_max`` 兜底到常量。
    """
    from RxyCode.RxyCode1_1_0.config.settings import _default_config

    assert "transport_retries" not in (_default_config().get("llm") or {})

    # 路由验证（绕开重型 __init__，避免 pytest-timeout）：
    # _transport_retry_max 是 UsageTrackingLLM 的方法（连接建立重试），
    # _stream_transient_retry_max 是 AgentV2 的方法（_raw_stream 内层重试）。
    from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM

    llm = UsageTrackingLLM.__new__(UsageTrackingLLM)
    llm._cfg = {}
    llm._transport_retries = None
    assert UsageTrackingLLM._transport_retry_max(llm) == 7

    agent = AgentV2.__new__(AgentV2)
    agent._cfg = {}
    agent._cache_cfg = {}
    assert AgentV2._stream_transient_retry_max(agent) == 7
