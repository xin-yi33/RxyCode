"""
Tests for recovery/error_recovery.py error classification + tenacity backoff.

Covers:
- ErrorKind enum (TRANSIENT vs PERMANENT)
- classify_error(): httpx/openai exception -> ErrorKind mapping
  (HTTP status semantics adapted from config/model_manager.py:8-21)
- retry_with_backoff(): TRANSIENT retried with exponential jitter,
  PERMANENT fails immediately without retry
- Existing ErrorRecovery public interface stays compatible
"""
import httpx
import pytest
from unittest.mock import MagicMock


class TestErrorKind:
    def test_enum_values(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert ErrorKind.TRANSIENT.value == "transient"
        assert ErrorKind.PERMANENT.value == "permanent"


class TestClassifyError:
    def _classify(self, exc):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import classify_error
        return classify_error(exc)

    def test_httpx_timeout_is_transient(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert self._classify(httpx.TimeoutException("t")) == ErrorKind.TRANSIENT

    def test_httpx_connect_error_is_transient(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert self._classify(httpx.ConnectError("c")) == ErrorKind.TRANSIENT

    def test_http_429_is_transient(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(429, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("rate", request=resp.request, response=resp)
        assert self._classify(exc) == ErrorKind.TRANSIENT

    def test_http_500_is_transient(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(500, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("srv", request=resp.request, response=resp)
        assert self._classify(exc) == ErrorKind.TRANSIENT

    def test_http_503_is_transient(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("srv", request=resp.request, response=resp)
        assert self._classify(exc) == ErrorKind.TRANSIENT

    def test_http_400_is_permanent(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(400, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("bad", request=resp.request, response=resp)
        assert self._classify(exc) == ErrorKind.PERMANENT

    def test_http_401_is_permanent(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(401, request=httpx.Request("GET", "http://x"))
        exc = httpx.HTTPStatusError("auth", request=resp.request, response=resp)
        assert self._classify(exc) == ErrorKind.PERMANENT

    def test_openai_rate_limit_is_transient(self):
        pytest.importorskip("openai")
        import openai
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
        exc = openai.RateLimitError("rate", response=resp, body=None)
        assert self._classify(exc) == ErrorKind.TRANSIENT

    def test_openai_api_connection_error_is_transient(self):
        pytest.importorskip("openai")
        import openai
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        exc = openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
        assert self._classify(exc) == ErrorKind.TRANSIENT

    def test_openai_bad_request_is_permanent(self):
        pytest.importorskip("openai")
        import openai
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
        exc = openai.BadRequestError("bad", response=resp, body=None)
        assert self._classify(exc) == ErrorKind.PERMANENT

    def test_value_error_is_permanent(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert self._classify(ValueError("parse fail")) == ErrorKind.PERMANENT

    def test_json_decode_error_is_permanent(self):
        import json
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert self._classify(json.JSONDecodeError("x", "y", 0)) == ErrorKind.PERMANENT

    def test_unknown_exception_defaults_permanent(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind

        class Weird(Exception):
            pass

        assert self._classify(Weird("?")) == ErrorKind.PERMANENT

    def test_timeout_error_builtin_is_transient(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert self._classify(TimeoutError("t")) == ErrorKind.TRANSIENT

    def test_connection_error_builtin_is_transient(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorKind
        assert self._classify(ConnectionError("c")) == ErrorKind.TRANSIENT


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_transient_retried_then_succeeds(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import retry_with_backoff

        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("boom")
            return "ok"

        # compress waits for test speed
        result = await retry_with_backoff(flaky, wait_multiplier=0.01)
        assert result == "ok"
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_transient_gives_up_after_3_attempts(self):
        import httpx
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import retry_with_backoff

        calls = {"n": 0}

        async def always_fail():
            calls["n"] += 1
            raise httpx.ConnectError("boom")

        with pytest.raises(httpx.ConnectError):
            await retry_with_backoff(always_fail, wait_multiplier=0.01)
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_permanent_not_retried(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import retry_with_backoff

        calls = {"n": 0}

        async def bad():
            calls["n"] += 1
            raise ValueError("logic error")

        with pytest.raises(ValueError):
            await retry_with_backoff(bad, wait_multiplier=0.01)
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_success_first_try_single_call(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import retry_with_backoff

        calls = {"n": 0}

        async def good():
            calls["n"] += 1
            return 42

        result = await retry_with_backoff(good, wait_multiplier=0.01)
        assert result == 42
        assert calls["n"] == 1


class TestErrorRecoveryCompat:
    """Existing public interface must keep working."""

    def test_handle_error_still_works(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorRecovery
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree

        er = ErrorRecovery(max_retries=2)
        task = TaskNode(title="t", description="d")
        tree = TaskTree(goal_id=task.id)
        tree.nodes[task.id] = task

        assert er.handle_error(tree, task.id, "e1") == "retry"
        assert er.handle_error(tree, task.id, "e2") == "retry"
        assert er.handle_error(tree, task.id, "e3") == "cancel"

    def test_get_error_summary_still_works(self):
        from RxyCode.RxyCode1_1_0.recovery.error_recovery import ErrorRecovery
        from RxyCode.RxyCode1_1_0.core.state import TaskNode, TaskTree

        er = ErrorRecovery()
        task = TaskNode(title="t", description="d")
        tree = TaskTree(goal_id=task.id)
        tree.nodes[task.id] = task
        er.handle_error(tree, task.id, "some error")
        assert "some error" in er.get_error_summary(tree)
