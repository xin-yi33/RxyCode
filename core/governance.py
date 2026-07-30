"""Governance primitives for model access and sensitive actions.

The module is deliberately independent from the agent graph.  It provides
small contracts that can be composed at the LLM and tool boundaries without
creating another registry or safety implementation.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .safety.audit import AuditLogger, get_audit_logger, sanitize_args
from .safety.policy import (
    RiskLevel,
    classify_tool_risk,
    is_dry_run,
    is_write_allowed,
)


# ---------------------------------------------------------------------------
# Provider/model-scoped token buckets
# ---------------------------------------------------------------------------


class RateLimitKey(BaseModel):
    """Canonical provider/model key used to isolate rate-limit state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str

    @field_validator("provider", "model", mode="before")
    @classmethod
    def _canonicalize(cls, value: Any) -> str:
        normalized = str(value).strip().casefold()
        if not normalized:
            raise ValueError("provider and model must be non-empty")
        return normalized


class RateLimitPolicy(BaseModel):
    """Refill budget for one provider/model pair.

    ``*_per_period`` controls refill speed.  Optional burst values control the
    maximum accumulated balance and default to the corresponding period
    budget.  A request always costs one request unit; callers declare their
    estimated token cost separately.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    requests_per_period: int = Field(default=60, gt=0)
    tokens_per_period: int = Field(default=120_000, gt=0)
    period_seconds: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    request_burst: int | None = Field(default=None, gt=0)
    token_burst: int | None = Field(default=None, gt=0)

    @property
    def request_capacity(self) -> int:
        return self.request_burst or self.requests_per_period

    @property
    def token_capacity(self) -> int:
        return self.token_burst or self.tokens_per_period

    @property
    def request_refill_rate(self) -> float:
        return self.requests_per_period / self.period_seconds

    @property
    def token_refill_rate(self) -> float:
        return self.tokens_per_period / self.period_seconds


class RateLimitGrant(BaseModel):
    """Receipt returned once both budgets were consumed atomically."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: RateLimitKey
    token_cost: int
    waited_seconds: float
    remaining_requests: float
    remaining_tokens: float


class RateLimitSnapshot(BaseModel):
    """Point-in-time balance for diagnostics and observability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: RateLimitKey
    remaining_requests: float
    remaining_tokens: float
    request_capacity: int
    token_capacity: int


class UnknownRateLimitKey(KeyError):
    """Raised when no explicit or default policy covers a model key."""

    def __init__(self, key: RateLimitKey) -> None:
        self.key = key
        super().__init__(
            f"no rate-limit policy registered for {key.provider}/{key.model}"
        )


class RateLimitCapacityError(ValueError):
    """Raised when one request can never fit in a configured bucket."""


class RateLimitTimeout(TimeoutError):
    """Raised when the budgets cannot be acquired before a caller deadline."""

    def __init__(
        self,
        key: RateLimitKey,
        timeout: float,
        required_wait: float,
    ) -> None:
        self.key = key
        self.timeout = timeout
        self.required_wait = required_wait
        super().__init__(
            "rate-limit wait timed out for "
            f"{key.provider}/{key.model} after {timeout:.3f}s "
            f"(next capacity in approximately {required_wait:.3f}s)"
        )


@dataclass
class _BucketState:
    policy: RateLimitPolicy
    requests: float
    tokens: float
    updated_at: float


class AsyncTokenBucketRateLimiter:
    """Dual token-bucket limiter keyed by provider and model.

    Accounting uses a short-lived ``threading.RLock`` rather than an
    ``asyncio.Lock`` so one shared agent can be used safely from multiple event
    loops.  The lock is never held while awaiting.  Cancellation propagates
    naturally from the configured async sleeper and cannot consume capacity.
    """

    def __init__(
        self,
        default_policy: RateLimitPolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._default_policy = default_policy
        self._clock = clock
        self._sleeper = sleeper
        self._policies: dict[RateLimitKey, RateLimitPolicy] = {}
        self._states: dict[RateLimitKey, _BucketState] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(provider: str, model: str) -> RateLimitKey:
        return RateLimitKey(provider=provider, model=model)

    def register(
        self,
        provider: str,
        model: str,
        policy: RateLimitPolicy,
    ) -> RateLimitKey:
        """Register a policy and reset that key to a full bucket."""

        if not isinstance(policy, RateLimitPolicy):
            policy = RateLimitPolicy.model_validate(policy)
        key = self._key(provider, model)
        with self._lock:
            self._policies[key] = policy
            self._states.pop(key, None)
        return key

    def unregister(self, provider: str, model: str) -> bool:
        """Remove an explicit policy and its accumulated bucket state."""

        key = self._key(provider, model)
        with self._lock:
            existed = key in self._policies
            self._policies.pop(key, None)
            self._states.pop(key, None)
        return existed

    def _policy_for(self, key: RateLimitKey) -> RateLimitPolicy:
        policy = self._policies.get(key, self._default_policy)
        if policy is None:
            raise UnknownRateLimitKey(key)
        return policy

    def _state_for(self, key: RateLimitKey, now: float) -> _BucketState:
        policy = self._policy_for(key)
        state = self._states.get(key)
        if state is None or state.policy != policy:
            state = _BucketState(
                policy=policy,
                requests=float(policy.request_capacity),
                tokens=float(policy.token_capacity),
                updated_at=now,
            )
            self._states[key] = state
        return state

    @staticmethod
    def _refill(state: _BucketState, now: float) -> None:
        elapsed = max(0.0, now - state.updated_at)
        if elapsed <= 0:
            return
        policy = state.policy
        state.requests = min(
            float(policy.request_capacity),
            state.requests + elapsed * policy.request_refill_rate,
        )
        state.tokens = min(
            float(policy.token_capacity),
            state.tokens + elapsed * policy.token_refill_rate,
        )
        state.updated_at = now

    @staticmethod
    def _required_wait(state: _BucketState, token_cost: int) -> float:
        request_shortfall = max(0.0, 1.0 - state.requests)
        token_shortfall = max(0.0, float(token_cost) - state.tokens)
        return max(
            request_shortfall / state.policy.request_refill_rate,
            token_shortfall / state.policy.token_refill_rate,
        )

    async def acquire(
        self,
        provider: str,
        model: str,
        *,
        token_cost: int = 0,
        timeout: float | None = None,
    ) -> RateLimitGrant:
        """Wait for and atomically consume request and token capacity.

        ``asyncio.CancelledError`` is intentionally not caught.  A timeout is
        reported as ``RateLimitTimeout`` and an impossible token request as
        ``RateLimitCapacityError``.
        """

        if isinstance(token_cost, bool) or not isinstance(token_cost, int):
            raise TypeError("token_cost must be an integer")
        if token_cost < 0:
            raise ValueError("token_cost must be non-negative")
        if timeout is not None and (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(float(timeout))
            or timeout < 0
        ):
            raise ValueError("timeout must be a finite non-negative number or None")

        key = self._key(provider, model)
        started_at = self._clock()
        while True:
            now = self._clock()
            with self._lock:
                state = self._state_for(key, now)
                if token_cost > state.policy.token_capacity:
                    raise RateLimitCapacityError(
                        f"token_cost {token_cost} exceeds bucket capacity "
                        f"{state.policy.token_capacity} for "
                        f"{key.provider}/{key.model}"
                    )
                self._refill(state, now)
                required_wait = self._required_wait(state, token_cost)
                if required_wait <= 0:
                    state.requests -= 1.0
                    state.tokens -= float(token_cost)
                    return RateLimitGrant(
                        key=key,
                        token_cost=token_cost,
                        waited_seconds=max(0.0, now - started_at),
                        remaining_requests=max(0.0, state.requests),
                        remaining_tokens=max(0.0, state.tokens),
                    )

            if timeout is not None:
                elapsed = max(0.0, now - started_at)
                remaining = float(timeout) - elapsed
                if remaining <= 0 or required_wait > remaining:
                    raise RateLimitTimeout(key, float(timeout), required_wait)
            await self._sleeper(required_wait)

    def reconcile(
        self,
        grant: RateLimitGrant,
        *,
        actual_token_cost: int,
    ) -> RateLimitSnapshot:
        """Reconcile a reservation against provider-reported total usage.

        Positive deltas become token debt and delay later requests; negative
        deltas refund unused output reservation up to the bucket capacity.
        The request unit is never refunded because an upstream attempt was
        already made.
        """
        if not isinstance(grant, RateLimitGrant):
            raise TypeError("grant must be a RateLimitGrant")
        if isinstance(actual_token_cost, bool) or not isinstance(
            actual_token_cost, int
        ):
            raise TypeError("actual_token_cost must be an integer")
        if actual_token_cost < 0:
            raise ValueError("actual_token_cost must be non-negative")

        now = self._clock()
        with self._lock:
            state = self._state_for(grant.key, now)
            self._refill(state, now)
            delta = actual_token_cost - grant.token_cost
            state.tokens = min(
                float(state.policy.token_capacity),
                state.tokens - float(delta),
            )
            return RateLimitSnapshot(
                key=grant.key,
                remaining_requests=max(0.0, state.requests),
                remaining_tokens=max(0.0, state.tokens),
                request_capacity=state.policy.request_capacity,
                token_capacity=state.policy.token_capacity,
            )

    def snapshot(self, provider: str, model: str) -> RateLimitSnapshot:
        """Return a refilled, non-consuming view of one bucket."""

        key = self._key(provider, model)
        now = self._clock()
        with self._lock:
            state = self._state_for(key, now)
            self._refill(state, now)
            return RateLimitSnapshot(
                key=key,
                remaining_requests=max(0.0, state.requests),
                remaining_tokens=max(0.0, state.tokens),
                request_capacity=state.policy.request_capacity,
                token_capacity=state.policy.token_capacity,
            )


# ---------------------------------------------------------------------------
# Role-aware model routing
# ---------------------------------------------------------------------------


class ModelRole(str, Enum):
    DEFAULT = "default"
    PLANNER = "planner"
    EXECUTOR = "executor"
    REFLECTION = "reflection"


class UnknownModelRole(ValueError):
    """Raised for roles outside the public routing contract."""


class ModelNotConfigured(LookupError):
    """Raised when neither a requested role nor the default is registered."""


class ModelSelection(BaseModel):
    """Observable routing result, including whether fallback was used."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    requested_role: ModelRole
    resolved_role: ModelRole
    used_default: bool
    model: Any
    provider: str | None = None
    model_name: str | None = None


@dataclass(frozen=True)
class _ModelRegistration:
    model: Any
    provider: str | None = None
    model_name: str | None = None


class ModelRouter:
    """Resolve declared agent roles to model instances.

    Known but unconfigured roles may fall back to ``default``.  Unknown role
    names always raise, preventing typos from silently changing model choice.
    """

    def __init__(self, default_model: Any = None) -> None:
        self._models: dict[ModelRole, _ModelRegistration] = {}
        self._lock = threading.RLock()
        if default_model is not None:
            self.register(ModelRole.DEFAULT, default_model)

    @staticmethod
    def _role(role: ModelRole | str) -> ModelRole:
        if isinstance(role, ModelRole):
            return role
        value = str(role).strip().casefold()
        try:
            return ModelRole(value)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in ModelRole)
            raise UnknownModelRole(
                f"unknown model role {value!r}; expected one of: {allowed}"
            ) from exc

    def register(
        self,
        role: ModelRole | str,
        model: Any,
        *,
        provider: str | None = None,
        model_name: str | None = None,
    ) -> None:
        resolved_role = self._role(role)
        if model is None:
            raise ValueError("model must not be None")
        registration = _ModelRegistration(
            model=model,
            provider=str(provider).strip() or None if provider is not None else None,
            model_name=(
                str(model_name).strip() or None if model_name is not None else None
            ),
        )
        with self._lock:
            self._models[resolved_role] = registration

    def unregister(self, role: ModelRole | str) -> bool:
        resolved_role = self._role(role)
        with self._lock:
            return self._models.pop(resolved_role, None) is not None

    def select(self, role: ModelRole | str) -> ModelSelection:
        requested = self._role(role)
        with self._lock:
            registration = self._models.get(requested)
            resolved = requested
            used_default = False
            if registration is None and requested is not ModelRole.DEFAULT:
                registration = self._models.get(ModelRole.DEFAULT)
                resolved = ModelRole.DEFAULT
                used_default = registration is not None
            if registration is None:
                raise ModelNotConfigured(
                    f"no model configured for role {requested.value!r} and no default"
                )
        return ModelSelection(
            requested_role=requested,
            resolved_role=resolved,
            used_default=used_default,
            model=registration.model,
            provider=registration.provider,
            model_name=registration.model_name,
        )

    def get(self, role: ModelRole | str) -> Any:
        """Return the model instance for a declared role."""

        return self.select(role).model

    @property
    def configured_roles(self) -> tuple[ModelRole, ...]:
        with self._lock:
            return tuple(role for role in ModelRole if role in self._models)


# ---------------------------------------------------------------------------
# Sensitive-action policy and audit contracts
# ---------------------------------------------------------------------------


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"
    DRY_RUN = "dry_run"


class PolicyDecision(BaseModel):
    """Immutable, redacted result of evaluating one sensitive action."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    action: str
    risk: RiskLevel
    outcome: PolicyOutcome
    reason: str
    approval: str
    args_summary: Any

    @property
    def requires_approval(self) -> bool:
        return self.outcome is PolicyOutcome.REQUIRE_APPROVAL


class PolicyAuditEvent(BaseModel):
    """Bounded, secret-redacted event suitable for structured telemetry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    action: str
    risk: RiskLevel
    outcome: PolicyOutcome
    reason: str
    approval: str
    executed: bool
    args: Any
    result: Any


class SensitiveActionPolicy:
    """Compose the existing safety classifiers into one decision interface."""

    _PATH_ARG_KEYS = (
        "filePath",
        "path",
        "file_path",
        "save_path",
        "target",
        "filename",
    )

    def decide(
        self,
        action: str,
        args: Any,
        config: dict | None = None,
        *,
        approval_source: str | None = None,
        mode: str | None = None,
        minimum_risk: RiskLevel | None = None,
    ) -> PolicyDecision:
        """Classify an action without performing it or requesting approval."""

        action = str(action).strip()
        if not action:
            raise ValueError("action must be non-empty")
        config = config if isinstance(config, dict) else {}
        safety = config.get("safety") or {}
        risk = classify_tool_risk(action, args)
        if minimum_risk is not None:
            risk = max(risk, RiskLevel(minimum_risk))
        summary = sanitize_args(args)

        def decision(
            outcome: PolicyOutcome,
            reason: str,
            approval: str,
        ) -> PolicyDecision:
            return PolicyDecision(
                action=action,
                risk=risk,
                outcome=outcome,
                reason=reason,
                approval=approval,
                args_summary=summary,
            )

        # Plan mode is a capability boundary, even when confirmation is off.
        if mode == "plan" and risk >= RiskLevel.WRITE:
            return decision(PolicyOutcome.DENY, "plan_mode_read_only", "rejected")

        # Match the existing safety gate's explicit legacy opt-out semantics.
        if not safety.get("enabled", False):
            return decision(PolicyOutcome.ALLOW, "safety_disabled", "safety_disabled")

        if risk >= RiskLevel.WRITE and isinstance(args, dict):
            for key in self._PATH_ARG_KEYS:
                path = args.get(key)
                if isinstance(path, str) and path and not is_write_allowed(path, config):
                    return decision(
                        PolicyOutcome.DENY,
                        "write_path_not_allowed",
                        "rejected",
                    )

        if risk >= RiskLevel.WRITE and is_dry_run(config):
            return decision(PolicyOutcome.DRY_RUN, "dry_run", "dry_run")

        if risk is RiskLevel.READ:
            return decision(PolicyOutcome.ALLOW, "read_only", "auto")

        if approval_source == "explicit_command":
            return decision(
                PolicyOutcome.ALLOW,
                "explicit_command",
                "explicit_command",
            )

        auto_levels = {
            str(level).strip().casefold()
            for level in (safety.get("auto_approve") or [])
        }
        if risk.name.casefold() in auto_levels:
            return decision(PolicyOutcome.ALLOW, "auto_approved_risk", "auto")

        return decision(
            PolicyOutcome.REQUIRE_APPROVAL,
            "approval_required",
            "required",
        )

    @staticmethod
    def resolve_approval(
        decision: PolicyDecision,
        *,
        approved: bool,
        approval: str | None = None,
    ) -> PolicyDecision:
        """Return a resolved copy of a pending decision."""

        if decision.outcome is not PolicyOutcome.REQUIRE_APPROVAL:
            raise ValueError("only a pending approval decision can be resolved")
        if approved:
            return decision.model_copy(
                update={
                    "outcome": PolicyOutcome.ALLOW,
                    "reason": "user_approved",
                    "approval": str(approval or "approved"),
                }
            )
        return decision.model_copy(
            update={
                "outcome": PolicyOutcome.DENY,
                "reason": "user_rejected",
                "approval": "rejected",
            }
        )

    @staticmethod
    def audit(
        decision: PolicyDecision,
        result: Any,
        *,
        executed: bool | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> PolicyAuditEvent:
        """Create a structured event and delegate persistence to AuditLogger."""

        sanitized_result = sanitize_args(result)
        if executed is None:
            executed = decision.outcome is PolicyOutcome.ALLOW
        event = PolicyAuditEvent(
            decision_id=decision.decision_id,
            action=decision.action,
            risk=decision.risk,
            outcome=decision.outcome,
            reason=decision.reason,
            approval=decision.approval,
            executed=executed,
            args=decision.args_summary,
            result=sanitized_result,
        )
        logger = audit_logger or get_audit_logger()
        logger.log(
            tool=decision.action,
            risk=decision.risk,
            args=decision.args_summary,
            approval=decision.approval,
            result=event.result,
        )
        return event


__all__ = [
    "AsyncTokenBucketRateLimiter",
    "ModelNotConfigured",
    "ModelRole",
    "ModelRouter",
    "ModelSelection",
    "PolicyAuditEvent",
    "PolicyDecision",
    "PolicyOutcome",
    "RateLimitCapacityError",
    "RateLimitGrant",
    "RateLimitKey",
    "RateLimitPolicy",
    "RateLimitSnapshot",
    "RateLimitTimeout",
    "SensitiveActionPolicy",
    "UnknownModelRole",
    "UnknownRateLimitKey",
]
