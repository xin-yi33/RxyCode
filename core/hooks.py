"""Async lifecycle hooks with bounded, isolated execution.

The registry is intentionally independent from the graph and tool runtime.
Callers emit before/after/error events and decide where audit results are
stored.  Hook failures never suppress later hooks; task cancellation still
propagates to the caller.
"""

from __future__ import annotations

import asyncio
import inspect
import itertools
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class HookPhase(str, Enum):
    """Supported lifecycle event phases."""

    BEFORE = "before"
    AFTER = "after"
    ERROR = "error"


class HookStatus(str, Enum):
    """Outcome of one hook invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class HookContext:
    """Immutable event context passed to each registered callback."""

    phase: HookPhase
    subject: str
    payload: Mapping[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class HookAuditResult:
    """Bounded audit record for one callback invocation."""

    hook_id: str
    hook_name: str
    phase: HookPhase
    subject: str
    status: HookStatus
    started_at: datetime
    duration_ms: float
    registration_order: int
    error_type: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly audit representation."""
        return {
            "hook_id": self.hook_id,
            "hook_name": self.hook_name,
            "phase": self.phase.value,
            "subject": self.subject,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "duration_ms": self.duration_ms,
            "registration_order": self.registration_order,
            "error_type": self.error_type,
            "error": self.error,
        }


# Short alias for callers that do not need to distinguish storage semantics.
HookResult = HookAuditResult


@dataclass(frozen=True, slots=True)
class _Registration:
    hook_id: str
    phase: HookPhase
    callback: Callable[[HookContext], Any]
    name: str
    timeout_seconds: float
    order: int


def _coerce_phase(value: HookPhase | str) -> HookPhase:
    if isinstance(value, HookPhase):
        return value
    try:
        return HookPhase(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(phase.value for phase in HookPhase)
        raise ValueError(f"Invalid hook phase {value!r}; expected one of: {choices}") from exc


def _validate_timeout(value: float, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a finite positive number")
    return float(value)


def _callback_name(callback: Callable[..., Any]) -> str:
    name = getattr(callback, "__name__", None)
    if isinstance(name, str) and name:
        return name
    return type(callback).__name__


class HookRegistry:
    """Ordered registry for synchronous and asynchronous lifecycle hooks."""

    def __init__(self, *, default_timeout_seconds: float = 5.0) -> None:
        self.default_timeout_seconds = _validate_timeout(
            default_timeout_seconds,
            "default_timeout_seconds",
        )
        self._registrations: dict[HookPhase, list[_Registration]] = {
            phase: [] for phase in HookPhase
        }
        self._orders = itertools.count()
        self._lock = threading.RLock()

    def register(
        self,
        phase: HookPhase | str,
        callback: Callable[[HookContext], Any],
        *,
        name: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        """Register a callback and return its opaque unregistration ID."""
        normalized_phase = _coerce_phase(phase)
        if not callable(callback):
            raise TypeError("hook callback must be callable")
        timeout = (
            self.default_timeout_seconds
            if timeout_seconds is None
            else _validate_timeout(timeout_seconds, "timeout_seconds")
        )
        hook_name = name.strip() if isinstance(name, str) else ""
        if not hook_name:
            hook_name = _callback_name(callback)

        with self._lock:
            registration = _Registration(
                hook_id=f"hook_{uuid4().hex}",
                phase=normalized_phase,
                callback=callback,
                name=hook_name,
                timeout_seconds=timeout,
                order=next(self._orders),
            )
            self._registrations[normalized_phase].append(registration)
            return registration.hook_id

    def unregister(self, hook_id: str) -> bool:
        """Remove a hook by ID; return whether a registration was removed."""
        if not isinstance(hook_id, str):
            return False
        with self._lock:
            for phase in HookPhase:
                registrations = self._registrations[phase]
                for index, registration in enumerate(registrations):
                    if registration.hook_id == hook_id:
                        del registrations[index]
                        return True
        return False

    async def emit(
        self,
        phase: HookPhase | str,
        subject: str,
        payload: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> list[HookAuditResult]:
        """Run matching hooks sequentially and return every audit outcome."""
        normalized_phase = _coerce_phase(phase)
        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("hook subject must be a non-empty string")
        if payload is not None and not isinstance(payload, Mapping):
            raise TypeError("hook payload must be a mapping")
        event_payload = dict(payload or {})
        event_payload.update(details)
        context = HookContext(
            phase=normalized_phase,
            subject=subject,
            payload=MappingProxyType(event_payload),
            occurred_at=datetime.now(timezone.utc),
        )

        with self._lock:
            registrations = tuple(self._registrations[normalized_phase])

        results: list[HookAuditResult] = []
        for registration in registrations:
            started_at = datetime.now(timezone.utc)
            started = time.perf_counter()
            status = HookStatus.SUCCEEDED
            error_type: str | None = None
            error: str | None = None
            try:
                await asyncio.wait_for(
                    self._invoke(registration.callback, context),
                    timeout=registration.timeout_seconds,
                )
            except TimeoutError:
                status = HookStatus.TIMED_OUT
                error_type = "TimeoutError"
                error = (
                    f"Hook exceeded {registration.timeout_seconds:g}s timeout"
                )
            except Exception as exc:
                status = HookStatus.FAILED
                error_type = type(exc).__name__
                error = str(exc)[:2000]

            results.append(
                HookAuditResult(
                    hook_id=registration.hook_id,
                    hook_name=registration.name,
                    phase=normalized_phase,
                    subject=subject,
                    status=status,
                    started_at=started_at,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    registration_order=registration.order,
                    error_type=error_type,
                    error=error,
                )
            )
        return results

    @staticmethod
    async def _invoke(
        callback: Callable[[HookContext], Any],
        context: HookContext,
    ) -> None:
        if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
            getattr(callback, "__call__", None)
        ):
            result = callback(context)
        else:
            # Threads cannot be forcibly stopped, but dispatching off-loop lets
            # wait_for release the lifecycle pipeline when the timeout expires.
            result = await asyncio.to_thread(callback, context)
        if inspect.isawaitable(result):
            await result
