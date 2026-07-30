"""Circuit breaker for LLM calls.

Adapted from pybreaker (https://github.com/danielfm/pybreaker):
``CircuitBreaker(fail_max=5, reset_timeout=60)`` — after 5 consecutive
failures the breaker opens for 60s; while open, calls fail fast with
``pybreaker.CircuitBreakerError`` instead of cascading into the provider.

The breaker is attached at the UsageTrackingLLM call layer
(core/agent_v2.py) so every LLM entry point (fast path, graph nodes,
sub-agents) shares one breaker per process.

Config switch: ``recovery.circuit_breaker_enabled`` (default true).
While the breaker is open the fast path returns a "服务暂时不可用"
message instead of raising, so the user gets an honest hint rather than
a stack of cascading failures.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, TypeVar

import pybreaker

_logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Machine-classifiable message returned while the breaker is open (fast path).
SERVICE_UNAVAILABLE_MESSAGE = (
    "[model unavailable] 服务暂时不可用，请稍后重试。"
    "(LLM service temporarily unavailable)"
)


def load_config() -> dict:
    """Deferred import so tests can patch this symbol directly."""
    from RxyCode.RxyCode1_1_0.config.settings import load_config as _load

    return _load()


def circuit_breaker_enabled() -> bool:
    """Read the ``recovery.circuit_breaker_enabled`` switch (default true)."""
    try:
        cfg = load_config() or {}
        return bool(cfg.get("recovery", {}).get("circuit_breaker_enabled", True))
    except Exception:
        return True


class LLMCircuitBreaker:
    """Async circuit breaker around pybreaker (fail_max / reset_timeout).

    Uses pybreaker's public state API (``before_call`` / ``on_success`` /
    ``on_failure``) rather than ``call_async``, because pybreaker's
    ``call_async`` is built on tornado.gen and does not interoperate with
    a running asyncio event loop.
    """

    def __init__(self, fail_max: int = 5, reset_timeout: int = 60, name: str = "llm"):
        self.breaker = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name=name,
        )

    async def call(self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Await ``fn(*args, **kwargs)`` through the breaker.

        Raises ``pybreaker.CircuitBreakerError`` when the breaker is open;
        otherwise re-raises the wrapped call's own exception after counting
        it towards fail_max.

        Implementation note: pybreaker's failure/success bookkeeping lives
        in the synchronous ``state.call`` path (``_handle_error`` increments
        the counter before ``on_failure``). We therefore run the async call
        first, then record the outcome through a tiny synchronous
        ``breaker.call`` so all counter/state transitions stay inside
        pybreaker's public ``CircuitBreaker.call``.
        """
        # Fast-fail check. We deliberately do NOT use
        # ``CircuitOpenState.before_call`` here: after the reset timeout it
        # would *synchronously* invoke the (async) fn to test the waters,
        # producing an un-awaited coroutine. Instead, replicate the timeout
        # check and drive the open -> half-open transition ourselves.
        if self.breaker.current_state == pybreaker.STATE_OPEN:
            from datetime import datetime, timedelta
            from pybreaker import UTC

            opened_at = self.breaker._state_storage.opened_at
            timeout = timedelta(seconds=self.breaker.reset_timeout)
            if opened_at and datetime.now(UTC) < opened_at + timeout:
                raise pybreaker.CircuitBreakerError(
                    "Timeout not elapsed yet, circuit breaker still open"
                )
            self.breaker.half_open()

        captured: dict[str, Any] = {}
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            captured["exc"] = exc
        else:
            captured["result"] = result

        def _record():
            if "exc" in captured:
                raise captured["exc"]
            return captured["result"]

        try:
            return self.breaker.call(_record)
        except Exception as exc:
            # CircuitBreakerError from threshold crossing should surface as
            # the original error for the caller's current attempt.
            if "exc" in captured and exc is not captured["exc"]:
                raise captured["exc"]
            raise


#: Process-wide shared breaker for the primary LLM.
_default_breaker: LLMCircuitBreaker | None = None


def get_default_breaker() -> LLMCircuitBreaker:
    """Return (and lazily create) the shared LLM circuit breaker."""
    global _default_breaker
    if _default_breaker is None:
        _default_breaker = LLMCircuitBreaker(fail_max=5, reset_timeout=60)
    return _default_breaker


def reset_breakers() -> None:
    """Reset the shared breaker (test hook / manual recovery)."""
    global _default_breaker
    if _default_breaker is not None:
        try:
            _default_breaker.breaker.close()
        except Exception:
            pass
    _default_breaker = None
