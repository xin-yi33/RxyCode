"""B11 · Budget, steps, depth, concurrency, and cancellation tests."""

from __future__ import annotations

import time
import pytest

from protocol.subagents import BudgetSpec
from core.subagents.budget import (
    BudgetError,
    BudgetGuard,
    CancellationScope,
    ConcurrencyGuard,
    ConcurrencyLimitExceeded,
    StepLimitExceeded,
    TimeLimitExceeded,
    TokenLimitExceeded,
    TotalTaskLimitExceeded,
    terminate_for_budget_error,
)


# ============================================================================
# BudgetGuard — steps / tokens / wall clock
# ============================================================================

class TestBudgetGuard:
    """Per-child step/token/wall-clock limits."""

    def test_initial_budget(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=5, max_tokens=1000))
        assert guard.remaining_steps == 5
        assert guard.remaining_tokens == 1000
        assert not guard.is_exhausted

    def test_step_consumption(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=2))
        guard.consume_step()
        assert guard.steps_used == 1
        guard.consume_step()
        with pytest.raises(StepLimitExceeded):
            guard.consume_step()

    def test_token_consumption(self):
        guard = BudgetGuard(budget=BudgetSpec(max_tokens=100))
        guard.consume_tokens(60)
        assert guard.remaining_tokens == 40
        with pytest.raises(TokenLimitExceeded):
            guard.consume_tokens(50)  # 60 + 50 = 110 > 100

    def test_wall_clock_check(self):
        guard = BudgetGuard(budget=BudgetSpec(max_wall_time_seconds=0))  # no limit
        guard.check_wall_clock()  # Does not raise

    def test_wall_clock_raises_when_limited(self):
        guard = BudgetGuard(budget=BudgetSpec(max_wall_time_seconds=1))
        time.sleep(1.1)
        with pytest.raises(TimeLimitExceeded):
            guard.check_wall_clock()

    def test_is_exhausted_by_steps(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=1))
        guard.consume_step()
        assert guard.is_exhausted

    def test_is_exhausted_by_tokens(self):
        guard = BudgetGuard(budget=BudgetSpec(max_tokens=5))
        with pytest.raises(TokenLimitExceeded):
            guard.consume_tokens(6)
        assert guard.is_exhausted

    def test_usage_record(self):
        guard = BudgetGuard(budget=BudgetSpec(max_steps=10, max_tokens=500))
        guard.consume_step()
        guard.consume_tokens(30)
        usage = guard.usage()
        assert usage.steps == 1
        assert usage.input_tokens == 30
        assert usage.wall_time_ms >= 0

    def test_budget_error_codes(self):
        assert StepLimitExceeded.CODE == "budget.steps"
        assert TokenLimitExceeded.CODE == "budget.tokens"
        assert TimeLimitExceeded.CODE == "budget.time"
        assert ConcurrencyLimitExceeded.CODE == "budget.concurrency"
        assert TotalTaskLimitExceeded.CODE == "budget.total_tasks"

    def test_terminate_mapping(self):
        assert terminate_for_budget_error(TimeLimitExceeded("t")) == "timed_out"
        assert terminate_for_budget_error(StepLimitExceeded("s")) == "failed"
        assert terminate_for_budget_error(ConcurrencyLimitExceeded("c")) == "failed"


# ============================================================================
# ConcurrencyGuard
# ============================================================================

class TestConcurrencyGuard:
    """Concurrent child and total task limits per root."""

    def test_acquire_up_to_limit(self):
        guard = ConcurrencyGuard(max_concurrent_children=2)
        guard.acquire("root", "c1")
        guard.acquire("root", "c2")
        assert guard.active_count("root") == 2

    def test_concurrency_limit_exceeded(self):
        guard = ConcurrencyGuard(max_concurrent_children=2)
        guard.acquire("root", "c1")
        guard.acquire("root", "c2")
        with pytest.raises(ConcurrencyLimitExceeded):
            guard.acquire("root", "c3")

    def test_release_frees_slot(self):
        guard = ConcurrencyGuard(max_concurrent_children=1)
        guard.acquire("root", "c1")
        guard.release("root", "c1")
        guard.acquire("root", "c2")  # slot freed
        assert guard.active_count("root") == 1

    def test_total_task_limit(self):
        guard = ConcurrencyGuard(max_concurrent_children=3, max_total_tasks=2)
        guard.acquire("root", "c1")
        guard.release("root", "c1")
        guard.acquire("root", "c2")
        guard.release("root", "c2")
        with pytest.raises(TotalTaskLimitExceeded):
            guard.acquire("root", "c3")

    def test_roots_are_independent(self):
        guard = ConcurrencyGuard(max_concurrent_children=1)
        guard.acquire("root_a", "c1")
        guard.acquire("root_b", "c2")  # Different root — OK
        assert guard.active_count("root_a") == 1
        assert guard.active_count("root_b") == 1

    def test_release_all_for_root(self):
        guard = ConcurrencyGuard(max_concurrent_children=5)
        guard.acquire("root", "c1")
        guard.acquire("root", "c2")
        released = guard.release_all_for_root("root")
        assert released == 2
        assert guard.active_count("root") == 0


# ============================================================================
# Cancellation scope
# ============================================================================

class TestCancellationScope:
    """Cancellation propagates through the scope."""

    def test_default_not_cancelled(self):
        scope = CancellationScope()
        assert not scope.is_cancelled()
        scope.throw_if_cancelled()  # Does not raise

    def test_cancel(self):
        scope = CancellationScope()
        scope.cancel()
        assert scope.is_cancelled()

    def test_cancel_raises_on_throw(self):
        from core.subagents.runtime import ChildCancelledError
        scope = CancellationScope()
        scope.cancel()
        with pytest.raises(ChildCancelledError):
            scope.throw_if_cancelled()


# ============================================================================
# Budget integration with depth semantics
# ============================================================================

class TestBudgetIntegration:
    """Budget guardrails yield explainable terminal states."""

    def test_zero_wall_clock_is_unlimited(self):
        """max_wall_time_seconds=0 means no time limit."""
        guard = BudgetGuard(budget=BudgetSpec(max_wall_time_seconds=0))
        time.sleep(0.05)
        assert not guard.is_exhausted

    def test_steps_can_reach_explainable_state(self):
        """A step breach is an explainable BudgetError, not a crash."""
        guard = BudgetGuard(budget=BudgetSpec(max_steps=1))
        guard.consume_step()
        with pytest.raises(BudgetError) as exc_info:
            guard.consume_step()
        assert exc_info.value.code == "budget.steps"
        assert terminate_for_budget_error(exc_info.value) == "failed"

    def test_timeout_yields_timed_out_status(self):
        """A time breach maps to the timed_out terminal state."""
        guard = BudgetGuard(budget=BudgetSpec(max_wall_time_seconds=1))
        time.sleep(1.1)
        with pytest.raises(BudgetError) as exc_info:
            guard.check_wall_clock()
        assert exc_info.value.code == "budget.time"
        assert terminate_for_budget_error(exc_info.value) == "timed_out"

    def test_budget_usage_queryable(self):
        """Budget usage is queryable for events and TaskResult."""
        guard = BudgetGuard(budget=BudgetSpec(max_steps=10, max_tokens=8000))
        guard.consume_step()
        guard.consume_step()
        guard.consume_tokens(150)
        assert guard.usage().steps == 2
        assert guard.usage().input_tokens == 150
