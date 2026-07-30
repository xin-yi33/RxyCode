"""
Tests for recovery/circuit_breaker.py — pybreaker-based circuit breaker.

Covers:
- Circuit opens after fail_max consecutive failures
- While open, calls fail fast (CircuitBreakerError) without invoking the LLM
- Breaker resets after reset_timeout window (half-open -> closed on success)
- UsageTrackingLLM integration: ainvoke wrapped, fast-path friendly message
- Config switch recovery.circuit_breaker_enabled (default true)

Adapted from pybreaker (https://github.com/danielfm/pybreaker).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_failing_llm(exc=None):
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=exc or ConnectionError("provider down"))
    return llm


def _make_ok_llm(content="ok"):
    llm = MagicMock()
    resp = MagicMock()
    resp.content = content
    resp.usage_metadata = None
    resp.response_metadata = {}
    llm.ainvoke = AsyncMock(return_value=resp)
    return llm


class TestCircuitBreakerBasics:
    @pytest.mark.asyncio
    async def test_opens_after_fail_max(self):
        import pybreaker
        from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import LLMCircuitBreaker

        cb = LLMCircuitBreaker(fail_max=5, reset_timeout=60)
        inner = _make_failing_llm()

        for _ in range(5):
            with pytest.raises(ConnectionError):
                await cb.call(inner.ainvoke, [])
        assert cb.breaker.current_state == pybreaker.STATE_OPEN

    @pytest.mark.asyncio
    async def test_fast_fail_when_open(self):
        import pybreaker
        from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import LLMCircuitBreaker

        cb = LLMCircuitBreaker(fail_max=5, reset_timeout=60)
        inner = _make_failing_llm()
        for _ in range(5):
            with pytest.raises(ConnectionError):
                await cb.call(inner.ainvoke, [])
        assert cb.breaker.current_state == pybreaker.STATE_OPEN

        calls_before = inner.ainvoke.await_count
        with pytest.raises(pybreaker.CircuitBreakerError):
            await cb.call(inner.ainvoke, [])
        # LLM not invoked again — fast fail
        assert inner.ainvoke.await_count == calls_before

    @pytest.mark.asyncio
    async def test_recovers_after_reset_timeout(self):
        import pybreaker
        from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import LLMCircuitBreaker

        cb = LLMCircuitBreaker(fail_max=2, reset_timeout=60)
        inner = _make_failing_llm()
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(inner.ainvoke, [])
        assert cb.breaker.current_state == pybreaker.STATE_OPEN

        # Simulate the reset window elapsing
        from datetime import timedelta
        cb.breaker._state_storage.opened_at = (
            cb.breaker._state_storage.opened_at - timedelta(seconds=61)
        )

        ok_inner = _make_ok_llm()
        result = await cb.call(ok_inner.ainvoke, [])
        assert result.content == "ok"
        assert cb.breaker.current_state == pybreaker.STATE_CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        import pybreaker
        from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import LLMCircuitBreaker

        cb = LLMCircuitBreaker(fail_max=3, reset_timeout=60)
        inner = _make_failing_llm()
        ok = _make_ok_llm()
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(inner.ainvoke, [])
        await cb.call(ok.ainvoke, [])
        # fail count reset — two more failures should NOT open (need 3)
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(inner.ainvoke, [])
        assert cb.breaker.current_state == pybreaker.STATE_CLOSED


class TestUsageTrackingLLMIntegration:
    def _make_wrapper(self, inner):
        from RxyCode.RxyCode1_1_0.core.agent_v2 import UsageTrackingLLM
        return UsageTrackingLLM(inner)

    @pytest.mark.asyncio
    async def test_ainvoke_passes_through_when_closed(self):
        from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

        inner = _make_ok_llm("hello")
        wrapper = self._make_wrapper(inner)
        with patch.object(cb_mod, "circuit_breaker_enabled", return_value=True):
            resp = await wrapper.ainvoke([])
        assert resp.content == "hello"
        cb_mod.reset_breakers()

    @pytest.mark.asyncio
    async def test_open_circuit_returns_unavailable_message(self):
        from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

        cb_mod.reset_breakers()
        inner = _make_failing_llm()
        wrapper = self._make_wrapper(inner)
        with patch.object(cb_mod, "circuit_breaker_enabled", return_value=True):
            # Trip the breaker (default fail_max=5)
            for _ in range(5):
                with pytest.raises(ConnectionError):
                    await wrapper.ainvoke([])

            resp = await wrapper.ainvoke([])
            text = getattr(resp, "content", str(resp))
            assert "暂时不可用" in text or "unavailable" in text.lower()
        cb_mod.reset_breakers()

    @pytest.mark.asyncio
    async def test_disabled_breaker_passes_exceptions_through(self):
        from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

        inner = _make_failing_llm()
        wrapper = self._make_wrapper(inner)
        # Isolate the breaker-passthrough contract from the transient transport
        # retry: ConnectionError is retryable, so with the default budget each
        # ainvoke would hit the provider 4x. Disable retries so "propagate raw"
        # means exactly one inner call per logical invocation.
        wrapper._transport_retries = 0
        with patch.object(cb_mod, "circuit_breaker_enabled", return_value=False):
            # With breaker disabled, errors propagate raw every time
            for _ in range(7):
                with pytest.raises(ConnectionError):
                    await wrapper.ainvoke([])
            assert inner.ainvoke.await_count == 7


@pytest.mark.asyncio
async def test_raw_stream_opens_breaker_and_stops_calling_provider():
    import pybreaker

    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        RateLimitPolicy,
    )
    from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod

    create = MagicMock(side_effect=ConnectionError("raw provider down"))
    agent = AgentV2.__new__(AgentV2)
    agent._llm = SimpleNamespace()
    agent._openai_client = MagicMock(
        return_value=SimpleNamespace(create=create)
    )
    limiter = AsyncTokenBucketRateLimiter(
        default_policy=RateLimitPolicy(
            requests_per_period=10,
            tokens_per_period=20,
            period_seconds=1000,
            request_burst=10,
            token_burst=20,
        ),
        clock=lambda: 0.0,
    )
    reconcile = MagicMock(wraps=limiter.reconcile)
    limiter.reconcile = reconcile
    agent._rate_limiter = limiter
    agent._rate_reserved_output_tokens = 10
    agent._rate_limit_timeout = 0
    agent.model_config = {
        "base_url": "https://api.openai.com/v1",
        "model_name": "raw-test-model",
        "temperature": 0,
        "max_tokens": 32,
    }
    breaker = cb_mod.LLMCircuitBreaker(fail_max=5, reset_timeout=60)

    async def consume_raw_stream():
        return [chunk async for chunk in AgentV2._raw_stream(agent, [])]

    with (
        patch.object(cb_mod, "circuit_breaker_enabled", return_value=True),
        patch.object(cb_mod, "get_default_breaker", return_value=breaker),
    ):
        for _ in range(5):
            with pytest.raises(ConnectionError, match="raw provider down"):
                await consume_raw_stream()

        with pytest.raises(pybreaker.CircuitBreakerError):
            await consume_raw_stream()

    assert create.call_count == 5
    provider = agent._provider_name(agent.model_config)
    snapshot = limiter.snapshot(provider, "raw-test-model")
    assert snapshot.remaining_requests == 4
    assert snapshot.remaining_tokens == 20
    assert reconcile.call_count == 6


def test_service_unavailable_message_is_a_failed_terminal_result():
    from RxyCode.RxyCode1_1_0.log.log_helpers import classify_agent_result
    from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import (
        SERVICE_UNAVAILABLE_MESSAGE,
    )

    status, detail = classify_agent_result(SERVICE_UNAVAILABLE_MESSAGE)

    assert status == "failed"
    assert detail == SERVICE_UNAVAILABLE_MESSAGE


@pytest.mark.asyncio
async def test_service_unavailable_does_not_complete_checkpoint_and_is_model_error(
    isolated_runtime,
):
    from RxyCode.RxyCode1_1_0.core.agent_v2 import AgentV2
    from RxyCode.RxyCode1_1_0.core.checkpoints import CheckpointStore
    from RxyCode.RxyCode1_1_0.log.monitor import run_monitor
    from RxyCode.RxyCode1_1_0.recovery.circuit_breaker import (
        SERVICE_UNAVAILABLE_MESSAGE,
    )

    store = CheckpointStore(isolated_runtime.data_dir / "checkpoints")
    agent = AgentV2.__new__(AgentV2)
    agent._session_id = "breaker-session"
    agent._tool_tracer = None
    agent._hooks = None
    agent._checkpoint_store = store
    agent._attempt_store = store
    agent._tool_journal = None
    agent._run_impl = AsyncMock(return_value=SERVICE_UNAVAILABLE_MESSAGE)

    result = await agent._run_observed(
        "continue after provider recovery",
        "build",
        "breaker-run",
    )

    checkpoint_id = store.checkpoint_id(
        "breaker-session",
        "continue after provider recovery",
        "build",
    )
    checkpoint = store.load(checkpoint_id)
    assert result == SERVICE_UNAVAILABLE_MESSAGE
    assert checkpoint is not None
    assert checkpoint["completed"] is False
    assert agent._last_failure_attribution == {"model_error": 1}
    snapshot = run_monitor.snapshot()
    assert snapshot["status_counts"] == {"failed": 1}
    assert snapshot["failure_attribution"] == {"model_error": 1}


class TestConfigSwitch:
    def test_default_enabled(self):
        from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod
        with patch.object(cb_mod, "load_config", return_value={}):
            assert cb_mod.circuit_breaker_enabled() is True

    def test_explicitly_disabled(self):
        from RxyCode.RxyCode1_1_0.recovery import circuit_breaker as cb_mod
        with patch.object(
            cb_mod, "load_config",
            return_value={"recovery": {"circuit_breaker_enabled": False}},
        ):
            assert cb_mod.circuit_breaker_enabled() is False
