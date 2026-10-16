"""Phase E · E2 — AgentTask lifecycle (per-agent asyncio.Task).

Every agent in a session runs as one ``AgentTask``: a state machine driven
by the lifecycle rules of PHASE-E §4.2.  ``interrupt`` cancels the underlying
``asyncio.Task`` (EB3: real cancellation) and cascades to the tool process
trees via the runtime; ``resume`` restores from a checkpoint written by
``pause``/``interrupt`` (PHASE-B/D checkpointing) with a double-run guard.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

_logger = logging.getLogger(__name__)

from .eventbus import BusEvent, EventBus

RunTarget = Callable[[str], Awaitable[Any]]


class LifecycleState(StrEnum):
    IDLE = "idle"
    BOOTSTRAP = "bootstrap"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvalidTransition(RuntimeError):
    """Raised when a lifecycle transition is not in the allowed table."""


class ResumeError(RuntimeError):
    """Raised when an agent cannot resume (still running / no checkpoint)."""


#: Legal transition table (PHASE-E §4.2); anything else raises
#: ``InvalidTransition``.  ``interrupt`` may fire from RUNNING, PAUSED or
#: BOOTSTRAP (the §4.2 ``interrupt`` pseudocode migrates to CANCELLED from
#: a live task), so RUNNING -> CANCELLED is legal.  CANCELLED and DONE are
#: terminal.
_ALLOWED: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.IDLE: frozenset({LifecycleState.BOOTSTRAP}),
    LifecycleState.BOOTSTRAP: frozenset(
        {LifecycleState.RUNNING, LifecycleState.FAILED, LifecycleState.CANCELLED}
    ),
    LifecycleState.RUNNING: frozenset(
        {
            LifecycleState.DONE,
            LifecycleState.FAILED,
            LifecycleState.PAUSED,
            LifecycleState.CANCELLED,
        }
    ),
    LifecycleState.PAUSED: frozenset({LifecycleState.RUNNING, LifecycleState.CANCELLED}),
    LifecycleState.FAILED: frozenset({LifecycleState.RUNNING}),
    LifecycleState.DONE: frozenset(),
    LifecycleState.CANCELLED: frozenset(),
}


class AgentTask:
    """One agent's lifecycle: state machine + main asyncio task.

    The ``runtime`` is the AgentRuntime (E3) protocol surface: it supplies
    ``save_checkpoint``/``load_checkpoint`` and ``cancel_process_trees``.
    ``run_target`` executes the agent's actual work (E3/E6 plug the real
    run loop in); this class owns the state machine and cancellation.
    """

    def __init__(
        self,
        agent_id: str,
        bus: EventBus,
        runtime: Any,
        run_target: RunTarget,
    ) -> None:
        self.agent_id = agent_id
        self._bus = bus
        self._runtime = runtime
        self._run_target = run_target
        self.state = LifecycleState.IDLE
        self._state_cond = asyncio.Condition()
        self._main_task: asyncio.Task[Any] | None = None
        self._task: str = ""
        self._checkpoint: object | None = None
        self._last_error: BaseException | None = None
        self.parent_id = ""
        self._run_journal: Any | None = None

    # ------------------------------------------------------------------
    # lifecycle entry points
    # ------------------------------------------------------------------

    def _event_payload(self) -> dict[str, Any]:
        """Runtime event payload: the cumulative token/budget snapshot
        (PHASE-E §4.1: the E3 runtime writes 0 at spawn and the value is
        monotonic — snapshots travel with every lifecycle event)."""
        snapshot = getattr(self._runtime, "token_snapshot", None)
        if snapshot is None:
            return {}
        try:
            return dict(snapshot(self.agent_id))
        except Exception:  # noqa: BLE001 - snapshot failures never break events
            return {}

    async def spawn(self, task: str) -> None:
        """IDLE -> BOOTSTRAP -> RUNNING; starts the main task."""
        await self._set_state(LifecycleState.BOOTSTRAP)
        payload = self._event_payload()
        await self._bus.publish(
            BusEvent(
                method="event/agent_started",
                session_id="",
                agent_id=self.agent_id,
                payload=payload,
            )
        )
        self._journal("event/agent_started", payload)
        try:
            await self._set_state(LifecycleState.RUNNING)
        except InvalidTransition:
            # bootstrap failed: never leave a half-started agent running
            await self._set_state(LifecycleState.FAILED)
            raise
        self._task = task
        self._main_task = asyncio.create_task(self._run_main(task))

    async def pause(self) -> None:
        """RUNNING -> PAUSED: checkpoint first, refuse to pause on failure.

        Pausing stops the current execution (the checkpoint is what resume
        restores from); the cancelled main task must finish before the
        migration so a late completion can never bump the state machine.
        """
        await self._require_state(LifecycleState.RUNNING)
        checkpoint = await self._runtime.save_checkpoint(self.agent_id)
        if checkpoint is None:
            raise RuntimeError(
                f"checkpoint write failed for agent {self.agent_id}; refusing to pause"
            )
        main_task = self._main_task
        if main_task is not None and not main_task.done():
            main_task.cancel()
            await asyncio.gather(main_task, return_exceptions=True)
        await self._set_state(LifecycleState.PAUSED)
        await self._bus.publish(
            BusEvent(
                method="event/agent_paused",
                session_id="",
                agent_id=self.agent_id,
                payload=self._event_payload(),
            )
        )

    async def interrupt(self, *, cascade_tools: bool = True) -> None:
        """Cancel the agent: terminal CANCELLED state, real task cancel (EB3).

        Order: state migration first (``wait_state`` sees it immediately),
        then ``task.cancel()`` + ``gather``, then the cancelled event, then
        the optional tool-process-tree cascade.
        """
        await self._require_state(
            LifecycleState.RUNNING, LifecycleState.PAUSED, LifecycleState.BOOTSTRAP
        )
        # checkpoint before interrupt (PHASE-E §4.2: interrupt writes the
        # checkpoint first; on write failure the state moves to FAILED with
        # the reason recorded — never silently continue)
        checkpoint = await self._runtime.save_checkpoint(self.agent_id)
        if checkpoint is None:
            raise RuntimeError(
                f"checkpoint write failed for agent {self.agent_id}; "
                "refusing to interrupt"
            )
        await self._set_state(LifecycleState.CANCELLED)
        main_task = self._main_task
        if main_task is not None and not main_task.done():
            main_task.cancel()
            await asyncio.gather(main_task, return_exceptions=True)
        await self._bus.publish(
            BusEvent(
                method="event/agent_cancelled",
                session_id="",
                agent_id=self.agent_id,
                payload=self._event_payload(),
            )
        )
        if cascade_tools:
            await self._runtime.cancel_process_trees(self.agent_id)

    async def resume(self) -> None:
        """PAUSED/FAILED -> RUNNING from a checkpoint (double-run guarded)."""
        async with self._state_cond:
            if self._main_task is not None and not self._main_task.done():
                raise ResumeError(
                    f"previous task still running for agent {self.agent_id}; "
                    "cannot resume"
                )
            if self.state not in (LifecycleState.PAUSED, LifecycleState.FAILED):
                raise ResumeError(
                    "resume only from PAUSED/FAILED, got %s" % self.state
                )
            checkpoint = await self._runtime.load_checkpoint(self.agent_id)
            if checkpoint is None:
                raise ResumeError(f"no checkpoint for agent {self.agent_id}")
            self.state = LifecycleState.RUNNING
            self._state_cond.notify_all()
        self._main_task = asyncio.create_task(self._run_from(checkpoint))

    # ------------------------------------------------------------------
    # state access
    # ------------------------------------------------------------------

    async def wait_state(
        self, target: LifecycleState, *, timeout: float | None = None
    ) -> LifecycleState:
        """Wait until the state machine reaches *target*; timeout raises."""
        async with self._state_cond:
            async def _wait() -> None:
                while self.state != target:
                    await self._state_cond.wait()

            if timeout is None:
                await _wait()
            else:
                await asyncio.wait_for(_wait(), timeout=timeout)
            return self.state

    async def _require_state(self, *allowed: LifecycleState) -> None:
        if self.state not in allowed:
            raise InvalidTransition(
                f"agent {self.agent_id}: operation not allowed in state {self.state}"
            )

    async def _set_state(self, s: LifecycleState) -> None:
        async with self._state_cond:
            if s not in _ALLOWED[self.state]:
                raise InvalidTransition(
                    f"invalid lifecycle transition {self.state} -> {s}"
                )
            self.state = s
            self._state_cond.notify_all()

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    async def _run_main(self, task: str) -> Any:
        try:
            result = await self._run_target(task)
        except asyncio.CancelledError as exc:
            self._last_error = exc
            raise
        except Exception as exc:
            self._last_error = exc
            await self._set_state(LifecycleState.FAILED)
        else:
            await self._set_state(LifecycleState.DONE)
            done_payload = self._event_payload()
            await self._bus.publish(
                BusEvent(
                    method="event/agent_done",
                    session_id="",
                    agent_id=self.agent_id,
                    payload=done_payload,
                )
            )
            self._journal("event/agent_done", done_payload)
            return result

    def _journal(self, method: str, payload: dict[str, Any]) -> None:
        journal = getattr(self, "_run_journal", None)
        if journal is None:
            return
        journal.record(method, self.agent_id, payload, parent_id=str(getattr(self, "parent_id", "") or ""))

    async def _run_from(self, checkpoint: object) -> Any:
        """Resumed execution; the run target may consume the checkpoint."""
        self._checkpoint = checkpoint
        try:
            try:
                result = await self._run_target(self._task, checkpoint=checkpoint)
            except TypeError:
                # run targets with the plain (task,) signature (E2 tests,
                # legacy paths) do not consume the checkpoint
                result = await self._run_target(self._task)
        except asyncio.CancelledError as exc:
            self._last_error = exc
            raise
        except Exception as exc:
            self._last_error = exc
            await self._set_state(LifecycleState.FAILED)
        else:
            await self._set_state(LifecycleState.DONE)
            resumed = self._event_payload()
            await self._bus.publish(
                BusEvent(
                    method="event/agent_done",
                    session_id="",
                    agent_id=self.agent_id,
                    payload=resumed,
                )
            )
            self._journal("event/agent_done", resumed)
            return result
