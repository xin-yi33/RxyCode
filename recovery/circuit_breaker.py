"""Circuit breaker for LLM calls.

Adapted from pybreaker (https://github.com/danielfm/pybreaker):
``CircuitBreaker(fail_max=5, reset_timeout=60)`` — after 5 consecutive
failures the breaker opens for 60s; while open, calls fail fast with
``pybreaker.CircuitBreakerError`` instead of cascading into the provider.

The breaker is attached at the UsageTrackingLLM call layer
(core/agent_v2.py). Historically every LLM entry point shared one
breaker per process. Phase F keys breakers: the single-agent path
still uses key ``"default"`` (same instance as before); each
AgentRuntime can hold its own key so one agent opening the breaker
does not sit out every other agent.

Config switch: ``recovery.circuit_breaker_enabled`` (default true).
While the breaker is open the fast path returns a "服务暂时不可用"
message instead of raising, so the user gets an honest hint rather than
a stack of cascading failures.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, TypeVar

import pybreaker

_logger = logging.getLogger(__name__)

# 本机时钟（握手/首包/空闲）不是模型宕机，也不是 429。
# 算进熔断会让一轮内部重试就把整个窗口停死。
# 废弃代码（2026-09-22）：任何异常都计一次失败，满 5 次后本窗口不再连接模型。
_LOCAL_DEADLINE_NAMES = frozenset(
    {
        "FirstTokenTimeoutError",
        "StreamIdleTimeoutError",
        "StreamConnectTimeoutError",
        "TimeoutError",
        "CancelledError",
    }
)
_LOCAL_DEADLINE_TEXT = (
    "provider connect handshake exceeded",
    "provider produced no first response",
    "provider stopped producing stream events",
)


def _is_local_deadline(exc: BaseException) -> bool:
    if type(exc).__name__ in _LOCAL_DEADLINE_NAMES:
        return True
    text = str(exc).lower()
    return any(piece in text for piece in _LOCAL_DEADLINE_TEXT)


class _OpenedClock(pybreaker.CircuitBreakerListener):
    """Wall clock for the open state. datetime comparison must not stick forever."""

    def __init__(self) -> None:
        self.mono: float | None = None
        self.reopen_streak: int = 0

    def state_change(self, cb, old_state, new_state) -> None:
        new_name = getattr(new_state, "name", "")
        old_name = getattr(old_state, "name", "")
        if new_name == pybreaker.STATE_OPEN:
            self.mono = time.monotonic()
            if old_name == pybreaker.STATE_HALF_OPEN:
                # The half-open probe failed again: keep backing off.
                self.reopen_streak += 1
            else:
                self.reopen_streak = 0
            _logger.warning(
                "circuit_breaker opened name=%s reopen_streak=%d",
                getattr(cb, "name", ""),
                self.reopen_streak,
            )
        elif new_name == pybreaker.STATE_CLOSED:
            self.mono = None
            self.reopen_streak = 0
            _logger.info(
                "circuit_breaker closed name=%s", getattr(cb, "name", "")
            )


T = TypeVar("T")

#: Machine-classifiable message returned while the breaker is open (fast path).
#: 废弃标注（2026-09-23）：生产路径已改用 `service_unavailable_detail()`
#: （带失败次数和冷却时间）。本常量仅被测试引用（`test_circuit_breaker.py`
#: 里验证 classify_agent_result 对旧格式消息的兼容）。彻底删除时需同步移除
#: 那两条测试。
SERVICE_UNAVAILABLE_MESSAGE = (
    "[model unavailable] 服务暂时不可用，请稍后重试。"
    "(LLM service temporarily unavailable)"
)


def service_unavailable_detail(breaker: "LLMCircuitBreaker") -> str:
    """2026-09-23：熔断打开时返回带具体信息的用户可读消息。

    此前只返回一句「服务暂时不可用」，用户不知道发生了什么、要等多久、
    能不能自动恢复。现在带上：连续失败次数、冷却剩余秒数、下一步建议。
    """
    fail_count = getattr(breaker.breaker, "fail_counter", 0) or 0
    cooldown = breaker._current_cooldown()
    mono = breaker._opened_clock.mono
    remaining = 0
    if mono is not None:
        import time as _time
        remaining = max(0, int(cooldown - (_time.monotonic() - mono)))
    parts = [
        f"[model unavailable] 模型服务连接失败（已连续失败 {fail_count} 次）。",
    ]
    if remaining > 0:
        parts.append(f"冷却中，约 {remaining} 秒后自动重试。")
    else:
        parts.append("冷却已结束，下一次请求会自动尝试重连。")
    parts.append("如果持续失败，请检查网络连接或切换模型。")
    return " ".join(parts)


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

    def __init__(
        self,
        fail_max: int = 5,
        reset_timeout: int = 60,
        name: str = "llm",
        max_reset_timeout: int = 300,
    ):
        self._opened_clock = _OpenedClock()
        self._base_reset_timeout = float(reset_timeout)
        self._max_reset_timeout = float(max_reset_timeout)
        self.breaker = pybreaker.CircuitBreaker(
            fail_max=fail_max,
            reset_timeout=reset_timeout,
            name=name,
            exclude=[_is_local_deadline],
            listeners=[self._opened_clock],
        )

    def _current_cooldown(self) -> float:
        """Cooldown for the current open episode.

        A failed half-open probe re-opens the breaker; without backoff that
        re-interrupts the user every ``reset_timeout`` seconds for as long
        as the provider is down. Each consecutive re-trip doubles the wait,
        capped at ``max_reset_timeout``. Closing resets the streak.
        """
        streak = self._opened_clock.reopen_streak
        return min(
            self._base_reset_timeout * (2.0 ** max(streak, 0)),
            self._max_reset_timeout,
        )

    def _is_cooled(self) -> bool:
        """True when the current open episode has outlived its cooldown."""
        if self._opened_clock.mono is not None:
            if (time.monotonic() - self._opened_clock.mono) >= self._current_cooldown():
                return True
        opened_at = self.breaker._state_storage.opened_at
        if opened_at:
            from datetime import datetime, timedelta
            from pybreaker import UTC

            return datetime.now(UTC) >= opened_at + timedelta(
                seconds=self._current_cooldown()
            )
        return False

    def is_blocking(self) -> bool:
        """True when calls should fast-fail right now.

        Self-healing: an open breaker whose cooldown has elapsed is no
        longer blocking — it is moved to half-open here so the next real
        call becomes the probe. Read-only callers (prewarm / keep-alive
        guards) use this so a cooled breaker never wedges the window
        until process restart.
        """
        try:
            if self.breaker.current_state != pybreaker.STATE_OPEN:
                return False
            if self._is_cooled():
                self.breaker.half_open()
                return False
            return True
        except Exception:
            return False

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
            if not self._is_cooled():
                raise pybreaker.CircuitBreakerError(
                    "model calls paused, circuit breaker still open"
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
            out = self.breaker.call(_record)
        except Exception as exc:
            # CircuitBreakerError from threshold crossing should surface as
            # the original error for the caller's current attempt.
            if "exc" in captured and exc is not captured["exc"]:
                raise captured["exc"] from exc
            raise
        if "exc" in captured:
            # Permanent observability (replaces the 2026-09-22 ad-hoc
            # debug probes): every counted failure names its exception so
            # the next "window stuck on cooldown" report is diagnosable
            # from rxycode.log instead of guesswork.
            exc = captured["exc"]
            detail = str(exc).replace("\n", " ")[:200]
            _logger.warning(
                "circuit_breaker failure counted name=%s type=%s detail=%s",
                getattr(self.breaker, "name", ""),
                type(exc).__name__,
                detail,
            )
        return out


#: Keyed breakers. Single-agent path uses ``"default"``.
_BREAKERS: dict[str, LLMCircuitBreaker] = {}

#: Backward-compat alias for tests that read/write the default slot.
_default_breaker: LLMCircuitBreaker | None = None


def get_breaker(key: str = "default") -> LLMCircuitBreaker:
    """Return (and lazily create) the breaker for ``key``."""
    global _default_breaker
    breaker = _BREAKERS.get(key)
    if breaker is None:
        breaker = LLMCircuitBreaker(fail_max=5, reset_timeout=60, name=key)
        _BREAKERS[key] = breaker
        if key == "default":
            _default_breaker = breaker
    return breaker


def get_default_breaker() -> LLMCircuitBreaker:
    """Return the single-agent breaker (key ``default``)."""
    global _default_breaker
    if _default_breaker is not None:
        _BREAKERS.setdefault("default", _default_breaker)
        return _default_breaker
    return get_breaker("default")


def breaker_is_open() -> bool:
    """True when the single-agent breaker should fast-fail right now.

    Goes through ``LLMCircuitBreaker.is_blocking``: a cooled breaker is
    moved to half-open and reported as not blocking, so guards that share
    this check can never wedge the window open until process restart.
    """
    try:
        return get_default_breaker().is_blocking()
    except Exception:
        return False


def release_after_verification_failure() -> None:
    """A missing write is not a dead model.

    The evidence gate can finish a turn with "no verified WRITE" after the
    provider already answered. Those turns still counted stream failures
    into the process-wide breaker, and the next message then raised
    ``CircuitBreakerError: model calls paused`` until the process restarted.
    Closing here lets the following user message call the model again.
    """
    try:
        breaker = get_default_breaker()
    except Exception:
        return
    try:
        breaker.breaker.close()
    except Exception:
        return
    breaker._opened_clock.mono = None
    breaker._opened_clock.reopen_streak = 0


def reset_all_breakers() -> None:
    """Close and drop every keyed breaker. Tests only."""
    global _default_breaker
    for breaker in list(_BREAKERS.values()):
        try:
            breaker.breaker.close()
        except Exception:
            pass
    _BREAKERS.clear()
    _default_breaker = None


def reset_breakers() -> None:
    """Reset the shared breaker (test hook / manual recovery)."""
    reset_all_breakers()
