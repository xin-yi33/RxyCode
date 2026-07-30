"""Governance primitives: rate limiting, model routing, and action policy."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from RxyCode.RxyCode1_1_0.core.safety.policy import RiskLevel


class _ManualTime:
    def __init__(self) -> None:
        self.now = 100.0

    def clock(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.now += delay
        await asyncio.sleep(0)


def _policy(**overrides):
    from RxyCode.RxyCode1_1_0.core.governance import RateLimitPolicy

    values = {
        "requests_per_period": 2,
        "tokens_per_period": 10,
        "period_seconds": 10.0,
    }
    values.update(overrides)
    return RateLimitPolicy(**values)


def test_rate_policy_rejects_invalid_budgets():
    from RxyCode.RxyCode1_1_0.core.governance import RateLimitPolicy

    with pytest.raises(ValidationError):
        RateLimitPolicy(requests_per_period=0)
    with pytest.raises(ValidationError):
        RateLimitPolicy(tokens_per_period=0)
    with pytest.raises(ValidationError):
        RateLimitPolicy(period_seconds=0)


@pytest.mark.asyncio
async def test_rate_limiter_atomically_consumes_request_and_token_budgets():
    from RxyCode.RxyCode1_1_0.core.governance import AsyncTokenBucketRateLimiter

    limiter = AsyncTokenBucketRateLimiter(default_policy=_policy())

    grant = await limiter.acquire("OpenAI", "GPT-4O", token_cost=4)
    snapshot = limiter.snapshot("openai", "gpt-4o")

    assert grant.key.provider == "openai"
    assert grant.key.model == "gpt-4o"
    assert grant.token_cost == 4
    assert grant.waited_seconds == pytest.approx(0.0, abs=0.001)
    assert snapshot.remaining_requests == pytest.approx(1.0, abs=0.01)
    assert snapshot.remaining_tokens == pytest.approx(6.0, abs=0.01)


@pytest.mark.asyncio
async def test_rate_limiter_reconciles_output_reservation_and_token_debt():
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        RateLimitTimeout,
    )

    limiter = AsyncTokenBucketRateLimiter(default_policy=_policy())
    grant = await limiter.acquire("p", "m", token_cost=8)

    refunded = limiter.reconcile(grant, actual_token_cost=3)

    assert refunded.remaining_tokens == pytest.approx(7.0, abs=0.01)

    second = await limiter.acquire("p", "m", token_cost=7)
    debt = limiter.reconcile(second, actual_token_cost=12)

    assert debt.remaining_tokens == 0
    with pytest.raises(RateLimitTimeout):
        await limiter.acquire("p", "m", token_cost=1, timeout=0)


@pytest.mark.asyncio
async def test_rate_limiter_isolates_provider_model_keys():
    from RxyCode.RxyCode1_1_0.core.governance import AsyncTokenBucketRateLimiter

    limiter = AsyncTokenBucketRateLimiter(default_policy=_policy())
    await limiter.acquire("openai", "planner", token_cost=10)

    other = await limiter.acquire("openai", "executor", token_cost=10)

    assert other.key.model == "executor"
    assert limiter.snapshot("openai", "planner").remaining_tokens < 0.01
    assert limiter.snapshot("openai", "executor").remaining_tokens < 0.01


@pytest.mark.asyncio
async def test_rate_limiter_refills_both_buckets_before_granting():
    from RxyCode.RxyCode1_1_0.core.governance import AsyncTokenBucketRateLimiter

    manual = _ManualTime()
    limiter = AsyncTokenBucketRateLimiter(
        default_policy=_policy(),
        clock=manual.clock,
        sleeper=manual.sleep,
    )
    await limiter.acquire("p", "m", token_cost=10)

    grant = await limiter.acquire("p", "m", token_cost=5, timeout=6.0)

    # Requests refill at 0.2/s and tokens at 1/s; tokens are the bottleneck.
    assert grant.waited_seconds == pytest.approx(5.0)
    assert grant.remaining_requests == pytest.approx(1.0)
    assert grant.remaining_tokens == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_rate_limiter_timeout_is_explicit_and_does_not_consume_budget():
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        RateLimitTimeout,
    )

    limiter = AsyncTokenBucketRateLimiter(default_policy=_policy())
    await limiter.acquire("p", "m", token_cost=10)

    with pytest.raises(RateLimitTimeout) as raised:
        await limiter.acquire("p", "m", token_cost=1, timeout=0.01)

    assert raised.value.key.provider == "p"
    assert raised.value.key.model == "m"
    assert raised.value.timeout == pytest.approx(0.01)
    assert limiter.snapshot("p", "m").remaining_requests == pytest.approx(1.0, abs=0.01)


@pytest.mark.asyncio
async def test_rate_limiter_wait_is_cooperatively_cancellable():
    from RxyCode.RxyCode1_1_0.core.governance import AsyncTokenBucketRateLimiter

    limiter = AsyncTokenBucketRateLimiter(
        default_policy=_policy(
            requests_per_period=1,
            tokens_per_period=1,
            period_seconds=1000.0,
        )
    )
    await limiter.acquire("p", "m", token_cost=1)
    waiter = asyncio.create_task(limiter.acquire("p", "m", token_cost=1))
    await asyncio.sleep(0)

    waiter.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert limiter.snapshot("p", "m").remaining_requests < 0.01


@pytest.mark.asyncio
async def test_rate_limiter_does_not_over_issue_under_concurrency():
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        RateLimitTimeout,
    )

    limiter = AsyncTokenBucketRateLimiter(
        default_policy=_policy(
            requests_per_period=1,
            tokens_per_period=1,
            period_seconds=1000.0,
        )
    )

    results = await asyncio.gather(
        *(limiter.acquire("p", "m", token_cost=1, timeout=0) for _ in range(8)),
        return_exceptions=True,
    )

    grants = [result for result in results if not isinstance(result, Exception)]
    timeouts = [result for result in results if isinstance(result, RateLimitTimeout)]
    assert len(grants) == 1
    assert len(timeouts) == 7


@pytest.mark.asyncio
async def test_rate_limiter_rejects_impossible_token_cost():
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        RateLimitCapacityError,
    )

    limiter = AsyncTokenBucketRateLimiter(default_policy=_policy(token_burst=4))

    with pytest.raises(RateLimitCapacityError, match="token_cost"):
        await limiter.acquire("p", "m", token_cost=5)


@pytest.mark.asyncio
async def test_rate_limiter_requires_policy_when_no_default_exists():
    from RxyCode.RxyCode1_1_0.core.governance import (
        AsyncTokenBucketRateLimiter,
        UnknownRateLimitKey,
    )

    limiter = AsyncTokenBucketRateLimiter()
    with pytest.raises(UnknownRateLimitKey):
        await limiter.acquire("p", "m")

    limiter.register("p", "m", _policy())
    assert (await limiter.acquire("p", "m")).key.model == "m"


def test_model_router_uses_role_specific_models_and_declared_default_fallback():
    from RxyCode.RxyCode1_1_0.core.governance import ModelRole, ModelRouter

    default = object()
    planner = object()
    router = ModelRouter(default_model=default)
    router.register(ModelRole.PLANNER, planner, provider="openai", model_name="planner-v1")

    planner_selection = router.select("planner")
    executor_selection = router.select("executor")

    assert planner_selection.model is planner
    assert planner_selection.resolved_role is ModelRole.PLANNER
    assert planner_selection.used_default is False
    assert planner_selection.provider == "openai"
    assert executor_selection.model is default
    assert executor_selection.resolved_role is ModelRole.DEFAULT
    assert executor_selection.used_default is True
    assert router.get(ModelRole.REFLECTION) is default


def test_model_router_never_silently_accepts_unknown_role():
    from RxyCode.RxyCode1_1_0.core.governance import (
        ModelRouter,
        UnknownModelRole,
    )

    router = ModelRouter(default_model=object())
    with pytest.raises(UnknownModelRole, match="critic"):
        router.get("critic")
    with pytest.raises(UnknownModelRole, match="critic"):
        router.register("critic", object())


def test_model_router_fails_when_role_and_default_are_unconfigured():
    from RxyCode.RxyCode1_1_0.core.governance import (
        ModelNotConfigured,
        ModelRouter,
    )

    with pytest.raises(ModelNotConfigured, match="planner"):
        ModelRouter().get("planner")


def test_sensitive_policy_composes_existing_risk_rules():
    from RxyCode.RxyCode1_1_0.core.governance import (
        PolicyOutcome,
        SensitiveActionPolicy,
    )

    policy = SensitiveActionPolicy()

    read = policy.decide("read", {"path": "README.md"}, {"safety": {"enabled": True}})
    write = policy.decide("write", {"path": "README.md"}, {"safety": {"enabled": True}})
    danger = policy.decide(
        "bash",
        {"command": "shutdown now", "api_key": "do-not-log"},
        {"safety": {"enabled": True}},
    )

    assert read.outcome is PolicyOutcome.ALLOW
    assert read.risk is RiskLevel.READ
    assert write.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert write.risk is RiskLevel.WRITE
    assert danger.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert danger.risk is RiskLevel.DANGER
    assert danger.args_summary["api_key"] == "***"


def test_sensitive_policy_risk_override_can_only_escalate():
    from RxyCode.RxyCode1_1_0.core.governance import (
        PolicyOutcome,
        SensitiveActionPolicy,
    )

    policy = SensitiveActionPolicy()
    enabled = {"safety": {"enabled": True}}

    escalated = policy.decide(
        "read",
        {"path": "README.md"},
        enabled,
        minimum_risk=RiskLevel.DANGER,
    )
    not_lowered = policy.decide(
        "bash",
        {"command": "shutdown now"},
        enabled,
        minimum_risk=RiskLevel.READ,
    )

    assert escalated.risk is RiskLevel.DANGER
    assert escalated.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert not_lowered.risk is RiskLevel.DANGER
    assert not_lowered.outcome is PolicyOutcome.REQUIRE_APPROVAL


def test_sensitive_policy_enforces_plan_boundary_and_write_paths(tmp_path):
    from RxyCode.RxyCode1_1_0.core.governance import (
        PolicyOutcome,
        SensitiveActionPolicy,
    )

    policy = SensitiveActionPolicy()
    enabled = {"safety": {"enabled": True}}

    plan_denial = policy.decide("write", {"path": "ok.txt"}, enabled, mode="plan")
    path_denial = policy.decide(
        "write",
        {"path": str(tmp_path / "outside.txt")},
        enabled,
    )

    assert plan_denial.outcome is PolicyOutcome.DENY
    assert plan_denial.reason == "plan_mode_read_only"
    assert path_denial.outcome is PolicyOutcome.DENY
    assert path_denial.reason == "write_path_not_allowed"


def test_sensitive_policy_supports_dry_run_auto_and_explicit_approval():
    from RxyCode.RxyCode1_1_0.core.governance import (
        PolicyOutcome,
        SensitiveActionPolicy,
    )

    policy = SensitiveActionPolicy()
    dry_run = policy.decide(
        "write",
        {"path": "output.txt"},
        {"safety": {"enabled": True, "dry_run": True}},
    )
    auto = policy.decide(
        "write",
        {"path": "output.txt"},
        {"safety": {"enabled": True, "auto_approve": ["write"]}},
    )
    explicit = policy.decide(
        "write",
        {"path": "output.txt"},
        {"safety": {"enabled": True}},
        approval_source="explicit_command",
    )

    assert dry_run.outcome is PolicyOutcome.DRY_RUN
    assert auto.outcome is PolicyOutcome.ALLOW
    assert auto.approval == "auto"
    assert explicit.outcome is PolicyOutcome.ALLOW
    assert explicit.approval == "explicit_command"


def test_sensitive_policy_resolves_pending_approval_without_mutating_decision():
    from RxyCode.RxyCode1_1_0.core.governance import (
        PolicyOutcome,
        SensitiveActionPolicy,
    )

    policy = SensitiveActionPolicy()
    pending = policy.decide(
        "write",
        {"path": "output.txt"},
        {"safety": {"enabled": True}},
    )

    approved = policy.resolve_approval(pending, approved=True, approval="approved")
    rejected = policy.resolve_approval(pending, approved=False)

    assert pending.outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert approved.outcome is PolicyOutcome.ALLOW
    assert approved.reason == "user_approved"
    assert rejected.outcome is PolicyOutcome.DENY
    assert rejected.approval == "rejected"


def test_policy_audit_event_is_bounded_redacted_and_delegates_to_existing_logger():
    from RxyCode.RxyCode1_1_0.core.governance import SensitiveActionPolicy

    policy = SensitiveActionPolicy()
    decision = policy.decide(
        "bash",
        {"command": "echo ok", "authorization": "Bearer secret"},
        {"safety": {"enabled": False}},
    )
    logger = MagicMock()

    event = policy.audit(
        decision,
        result={"token": "result-secret", "output": "x" * 500},
        audit_logger=logger,
    )

    assert event.args["authorization"] == "***"
    assert event.result["token"] == "***"
    assert len(event.result["output"]) <= 203
    logger.log.assert_called_once_with(
        tool="bash",
        risk=RiskLevel.WRITE,
        args=decision.args_summary,
        approval="safety_disabled",
        result=event.result,
    )
