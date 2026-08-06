"""Budget, concurrency, and wall-clock guardrails for child sessions.

B11 · Multi-agent cost and runaway protection:
  - token, step, wall-clock-time, concurrent-child, and total-task budgets
  - limits frozen at creation time; consumed at every model/tool call
  - every limit breach yields an explainable terminal state
  - cancellation terminates model waits, tool waits, and descendant children
  - parent cancellation leaves no orphan process, lease, or task
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock

from protocol.subagents import BudgetSpec, UsageRecord


# ---------------------------------------------------------------------------
# Budget errors
# ---------------------------------------------------------------------------

class BudgetError(Exception):
    """Base class for budget violations."""

    CODE = "budget.error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code or self.CODE


class StepLimitExceeded(BudgetError):
    CODE = "budget.steps"


class TokenLimitExceeded(BudgetError):
    CODE = "budget.tokens"


class TimeLimitExceeded(BudgetError):
    CODE = "budget.time"


class ConcurrencyLimitExceeded(BudgetError):
    CODE = "budget.concurrency"


class TotalTaskLimitExceeded(BudgetError):
    CODE = "budget.total_tasks"


# ---------------------------------------------------------------------------
# BudgetGuard — per-child steps/tokens/wall-clock
# ---------------------------------------------------------------------------

@dataclass
class BudgetGuard:
    """Enforces per-child budget limits.

    Limits are frozen at creation. Each step and token consumption is
    checked against the frozen maximum. Wall-clock is monitored separately.
    """

    budget: BudgetSpec = field(default_factory=BudgetSpec)

    # Running counters
    steps_used: int = field(default=0, init=False)
    tokens_used: int = field(default=0, init=False)
    wall_start_ms: int = field(default=0, init=False)

    def __post_init__(self):
        self.wall_start_ms = int(time.time() * 1000)

    # -- consumption ---------------------------------------------------------

    def consume_step(self) -> None:
        """Consume one agentic iteration step."""
        self.steps_used += 1
        if self.steps_used > self.budget.max_steps:
            raise StepLimitExceeded(
                f"Step limit exceeded: {self.steps_used}/{self.budget.max_steps}",
                code=StepLimitExceeded.CODE,
            )

    def consume_tokens(self, count: int) -> None:
        """Consume tokens from the budget."""
        self.tokens_used += count
        if self.tokens_used > self.budget.max_tokens:
            raise TokenLimitExceeded(
                f"Token limit exceeded: {self.tokens_used}/{self.budget.max_tokens}",
                code=TokenLimitExceeded.CODE,
            )

    # -- queries -------------------------------------------------------------

    @property
    def remaining_steps(self) -> int:
        return max(0, self.budget.max_steps - self.steps_used)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.budget.max_tokens - self.tokens_used)

    @property
    def elapsed_wall_ms(self) -> int:
        return int(time.time() * 1000) - self.wall_start_ms

    def check_wall_clock(self) -> None:
        """Raise TimeLimitExceeded if the wall-clock budget is exhausted."""
        max_ms = self.budget.max_wall_time_seconds * 1000
        if max_ms > 0 and self.elapsed_wall_ms > max_ms:
            raise TimeLimitExceeded(
                f"Wall-clock limit exceeded: "
                f"{self.elapsed_wall_ms // 1000}s/{self.budget.max_wall_time_seconds}s",
                code=TimeLimitExceeded.CODE,
            )

    @property
    def is_exhausted(self) -> bool:
        if self.remaining_steps <= 0 or self.remaining_tokens <= 0:
            return True
        max_ms = self.budget.max_wall_time_seconds * 1000
        return max_ms > 0 and self.elapsed_wall_ms > max_ms

    def usage(self) -> UsageRecord:
        """Return the current usage record for terminal reporting."""
        return UsageRecord(
            steps=self.steps_used,
            input_tokens=self.tokens_used,
            output_tokens=0,
            wall_time_ms=self.elapsed_wall_ms,
        )


# ---------------------------------------------------------------------------
# ConcurrencyGuard — per-root concurrency and total task limits
# ---------------------------------------------------------------------------

@dataclass
class ConcurrencyGuard:
    """Tracks concurrent and total children per Primary root.

    Ensures no root exceeds its concurrency cap and no runaway tree
    spawns unbounded tasks.
    """

    max_concurrent_children: int = 3
    max_total_tasks: int = 64

    # root_session_id → set of active child session ids
    _active: dict[str, set[str]] = field(default_factory=dict)
    # root_session_id → total tasks started (including completed)
    _total: dict[str, int] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    def acquire(self, root_session_id: str, session_id: str) -> None:
        """Register a child as starting, enforcing concurrency/total limits.

        Raises ConcurrencyLimitExceeded or TotalTaskLimitExceeded.
        """
        with self._lock:
            active = self._active.setdefault(root_session_id, set())
            total = self._total.get(root_session_id, 0)

            if total + 1 > self.max_total_tasks:
                raise TotalTaskLimitExceeded(
                    f"Total task limit exceeded: {total}/{self.max_total_tasks}",
                    code=TotalTaskLimitExceeded.CODE,
                )

            if len(active) >= self.max_concurrent_children:
                raise ConcurrencyLimitExceeded(
                    f"Concurrency limit exceeded: "
                    f"{len(active)}/{self.max_concurrent_children} active",
                    code=ConcurrencyLimitExceeded.CODE,
                )

            active.add(session_id)
            self._total[root_session_id] = total + 1

    def release(self, root_session_id: str, session_id: str) -> None:
        """Release a child session slot."""
        with self._lock:
            active = self._active.get(root_session_id)
            if active is not None:
                active.discard(session_id)

    def active_count(self, root_session_id: str) -> int:
        return len(self._active.get(root_session_id, set()))

    def total_count(self, root_session_id: str) -> int:
        return self._total.get(root_session_id, 0)

    def release_all_for_root(self, root_session_id: str) -> int:
        """Release all active slots for a root; returns count released."""
        with self._lock:
            active = self._active.pop(root_session_id, set())
            return len(active)


# ---------------------------------------------------------------------------
# Cancellation scope
# ---------------------------------------------------------------------------

@dataclass
class CancellationScope:
    """Aggregates cancellation signals across a child subtree.

    Cancelling the scope propagates to the token; the runtime cancels
    model waits, tool waits, and descendant children that share the scope.
    """

    _cancelled: bool = field(default=False, init=False)

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def throw_if_cancelled(self) -> None:
        from .runtime import ChildCancelledError
        if self._cancelled:
            raise ChildCancelledError("Child session cancelled via scope")


def terminate_for_budget_error(exc: BudgetError) -> str:
    """Map a BudgetError to a terminal status string.

    Returns one of: 'timed_out' (time), 'failed' (steps/tokens), 'denied' (n/a).
    """
    if exc.code == TimeLimitExceeded.CODE:
        return "timed_out"
    if exc.code in (ConcurrencyLimitExceeded.CODE, TotalTaskLimitExceeded.CODE):
        return "failed"
    # steps / tokens
    return "failed"
