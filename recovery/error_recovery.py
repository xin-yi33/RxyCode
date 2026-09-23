"""ErrorRecovery: exception handling, classification and retry logic.

Handles runtime errors during execution (not validation failures —
those go through Validator → RePlanner).

Strategy:
- Classify errors as TRANSIENT (network blip / 429 / timeout / 5xx) vs
  PERMANENT (logic / parse / validation / 4xx) via ``classify_error``.
- TRANSIENT failures are retried with tenacity exponential backoff +
  jitter (``retry_with_backoff``); PERMANENT failures are not retried.
- Task-level retry up to max_retries times (``ErrorRecovery.handle_error``).
- On final failure, mark task CANCELLED and continue.
- Log all errors to the task's error_history.

Adapted from:
- tenacity docs (https://tenacity.readthedocs.io) — AsyncRetrying /
  wait_exponential_jitter / stop_after_attempt / retry_if_exception_type
- HTTP status-code semantics from config/model_manager.py:8-21
  (429/5xx transient, 4xx permanent)
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Awaitable, Callable, TypeVar

from RxyCode.RxyCode1_1_0.core.state import TaskStatus, TaskTree


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class ErrorKind(str, Enum):
    """Whether an error is worth retrying, feeding the model, or ending the turn."""

    TRANSIENT = "transient"    # network blip / rate limit / timeout / 5xx
    BUSINESS = "business"      # tool/result failure; continue the turn
    PERMANENT = "permanent"    # logic / parse / validation / 4xx / fired clocks


def _http_status_of(exc: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from an exception."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
        if isinstance(status, int):
            return status
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def classify_error(exc: BaseException) -> ErrorKind:
    """Map an exception to TRANSIENT, BUSINESS, or PERMANENT.

    Transient (worth retrying, not ``event/error`` until exhausted):
    - connection errors, HTTP 429/5xx, short connect handshake timeouts
    - not generic read/idle timeouts (those clocks already consumed the budget)

    Business (tool card may be yellow; the turn continues):
    - not used for raw exceptions; see ``classify_tool_status``

    Permanent (fail fast / ``event/error``):
    - HTTP 4xx other than 429
    - fired stream clocks (``FirstTokenTimeoutError`` / ``StreamIdleTimeoutError``)
    - generic ``TimeoutError`` / HTTP read timeouts / ``APITimeoutError``
    - parse & validation errors
    - unknown errors
    """
    # Fired stream clocks are TimeoutError subclasses but are not transport
    # blips. Short connect handshake failures stay retryable; once idle /
    # first-token types escape, the turn is over.
    exc_name = type(exc).__name__
    if exc_name in {
        "FirstTokenTimeoutError",
        "StreamIdleTimeoutError",
        "CircuitBreakerError",
    }:
        return ErrorKind.PERMANENT
    if exc_name == "StreamConnectTimeoutError":
        return ErrorKind.TRANSIENT

    # --- builtin signals -----------------------------------------------
    if isinstance(exc, ConnectionError):
        return ErrorKind.TRANSIENT
    if isinstance(exc, TimeoutError):
        return ErrorKind.PERMANENT

    # --- httpx transport-level errors ----------------------------------
    try:
        import httpx
        if isinstance(exc, httpx.ReadTimeout):
            return ErrorKind.PERMANENT
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout,
                            httpx.PoolTimeout, httpx.WriteTimeout,
                            httpx.NetworkError, httpx.RemoteProtocolError)):
            return ErrorKind.TRANSIENT
        if isinstance(exc, httpx.TimeoutException):
            return ErrorKind.PERMANENT
    except ImportError:  # pragma: no cover - httpx is a hard dependency
        pass

    # --- openai SDK errors ---------------------------------------------
    try:
        import openai
        if isinstance(exc, openai.APITimeoutError):
            return ErrorKind.PERMANENT
        if isinstance(exc, (openai.APIConnectionError, openai.RateLimitError,
                            openai.InternalServerError)):
            return ErrorKind.TRANSIENT
        if isinstance(exc, openai.APIStatusError):
            status = _http_status_of(exc)
            if status is not None:
                if status == 429 or 500 <= status < 600:
                    return ErrorKind.TRANSIENT
                return ErrorKind.PERMANENT
    except ImportError:  # pragma: no cover - openai is a hard dependency
        pass

    # --- generic HTTP status semantics (model_manager.py:8-21) ---------
    status = _http_status_of(exc)
    if status is not None:
        if status == 429 or 500 <= status < 600:
            return ErrorKind.TRANSIENT
        if 400 <= status < 500:
            return ErrorKind.PERMANENT

    # --- parse / logic / validation errors ------------------------------
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError,
                        json.JSONDecodeError)):
        return ErrorKind.PERMANENT

    # Unknown: conservative default — do not retry blindly.
    return ErrorKind.PERMANENT


def classify_tool_status(status: str | None) -> ErrorKind:
    """Tool card outcomes are BUSINESS unless the user cancelled."""
    normalized = str(status or "").strip().lower()
    if normalized in {"success", "ok", ""}:
        return ErrorKind.BUSINESS
    if normalized in {"cancelled", "canceled"}:
        return ErrorKind.PERMANENT
    return ErrorKind.BUSINESS


def failure_surface(
    *,
    exc: BaseException | None = None,
    tool_status: str | None = None,
) -> str:
    """Where this failure may appear: event/retry, tool_result, or event/error."""
    if tool_status is not None:
        kind = classify_tool_status(tool_status)
        if str(tool_status).strip().lower() in {"success", "ok", ""}:
            return "none"
        if kind == ErrorKind.BUSINESS:
            return "tool_result"
        return "event/error"
    if exc is None:
        return "none"
    kind = classify_error(exc)
    if kind == ErrorKind.TRANSIENT:
        return "event/retry"
    if kind == ErrorKind.BUSINESS:
        return "tool_result"
    return "event/error"


def should_emit_event_error(
    exc: BaseException | None = None,
    *,
    tool_status: str | None = None,
    retries_exhausted: bool = True,
) -> bool:
    """``event/error`` ends the turn. Transient failures stay quiet until exhausted."""
    surface = failure_surface(exc=exc, tool_status=tool_status)
    if surface == "tool_result" or surface == "none":
        return False
    if surface == "event/retry" and not retries_exhausted:
        return False
    return surface == "event/error" or (
        surface == "event/retry" and retries_exhausted
    )


# ---------------------------------------------------------------------------
# tenacity-backed retry helper
# ---------------------------------------------------------------------------

T = TypeVar("T")


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    wait_multiplier: float = 1.0,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Run ``fn`` retrying TRANSIENT errors with exponential backoff + jitter.

    Adapted from tenacity: ``wait_exponential_jitter(initial=2, max=30)``
    scaled by ``wait_multiplier`` (tests pass 0.01 to keep them fast) and
    ``stop_after_attempt(max_attempts)``. PERMANENT errors propagate
    immediately without consuming retry attempts.
    """
    from tenacity import (
        AsyncRetrying,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential_jitter,
    )

    def _is_transient(exc: BaseException) -> bool:
        return classify_error(exc) == ErrorKind.TRANSIENT

    initial = max(0.0, 2.0 * wait_multiplier)
    max_wait = max(initial, 30.0 * wait_multiplier)

    def _before_sleep(state: object) -> None:
        if on_retry is None:
            return
        attempt_number = int(getattr(state, "attempt_number", 1))
        outcome = getattr(state, "outcome", None)
        exception = outcome.exception() if outcome is not None else None
        if isinstance(exception, BaseException):
            on_retry(attempt_number, exception)

    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_is_transient),
        wait=wait_exponential_jitter(initial=initial, max=max_wait),
        stop=stop_after_attempt(max_attempts),
        before_sleep=_before_sleep,
        reraise=True,
    ):
        with attempt:
            return await fn()
    raise RuntimeError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Task-level error recovery (public interface kept compatible)
# ---------------------------------------------------------------------------

class ErrorRecovery:
    """Handles execution errors with retry logic."""

    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries

    def handle_error(self, tree: TaskTree, task_id: str, error: str) -> str:
        """Handle an execution error.

        Returns:
            "retry" if the task should be retried,
            "cancel" if max retries exceeded,
            "skip" if task not found.
        """
        task = tree.nodes.get(task_id)
        if not task:
            return "skip"

        task.error_history.append(error or "")
        task.touch()

        if task.retry_count < self._max_retries:
            task.retry_count += 1
            task.status = TaskStatus.PENDING  # reset to pending for retry
            return "retry"
        else:
            task.status = TaskStatus.CANCELLED
            return "cancel"

    def get_error_summary(self, tree: TaskTree) -> str:
        """Get a summary of all errors in the tree."""
        parts = []
        for node in tree.nodes.values():
            if node.error_history:
                parts.append(f"[{node.title}] {len(node.error_history)} errors:")
                for err in node.error_history[-3:]:  # last 3 errors
                    parts.append(f"  - {err[:200]}")
        return "\n".join(parts) if parts else "(no errors)"
