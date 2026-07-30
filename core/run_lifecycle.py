"""Serial, cancellable lifecycle for operations sharing one agent instance."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


class RunLifecycle:
    """Serialize async runs and expose one thread-safe cancellation handle.

    ``asyncio.Lock`` instances can become tied to a TestClient/event loop when
    they contend.  The API is intentionally exercised from multiple loops, so
    this lifecycle uses a process-local gate with cancellable async polling.
    The protected operation still runs on its caller's event loop.
    """

    def __init__(self, *, poll_interval: float = 0.01) -> None:
        self._gate = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_task: asyncio.Task | None = None
        self._active_loop: asyncio.AbstractEventLoop | None = None
        self._active_kind: str | None = None
        self._poll_interval = poll_interval

    @property
    def busy(self) -> bool:
        with self._state_lock:
            return self._active_task is not None

    @property
    def active_kind(self) -> str | None:
        with self._state_lock:
            return self._active_kind

    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        kind: str = "operation",
    ) -> T:
        """Wait for the shared slot, then run ``operation`` as the active task."""
        while not self._gate.acquire(blocking=False):
            await asyncio.sleep(self._poll_interval)

        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        with self._state_lock:
            self._active_task = task
            self._active_loop = loop
            self._active_kind = kind
        try:
            return await operation()
        finally:
            with self._state_lock:
                if self._active_task is task:
                    self._active_task = None
                    self._active_loop = None
                    self._active_kind = None
            self._gate.release()

    def cancel(self) -> bool:
        """Cancel the active operation from this or another event-loop thread."""
        with self._state_lock:
            task = self._active_task
            loop = self._active_loop
        if task is None or task.done() or loop is None or loop.is_closed():
            return False

        def cancel_task() -> None:
            if not task.done():
                task.cancel()

        if loop.is_running():
            loop.call_soon_threadsafe(cancel_task)
            return True
        return False

