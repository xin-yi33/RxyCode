"""Tenant token, task, concurrency, preview, and sandbox quotas.

The authenticated tenant and user are the only identity. Request headers are
ignored. A refusal records a quota.exceeded event and does not occupy a worker
or call the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class WorkerCapacity(Protocol):
    """The scheduler side of admission. Only an admitted Run occupies a worker."""

    def acquire(self, tenant_id: str, user_id: str) -> str:
        """Occupy one worker for this user."""

    def release(self, tenant_id: str, user_id: str) -> None:
        """Return the worker when admission cannot finish."""


class ModelClient(Protocol):
    """A model call. The gate invokes it only after admission succeeds."""

    def __call__(self, prompt: str) -> str:
        """Generate a reply for this prompt."""


@dataclass(frozen=True)
class Limits:
    """Server-side ceilings for one user inside one tenant."""

    tasks: int
    tokens: int
    concurrency: int
    preview_fee: int
    sandbox_fee: int


@dataclass
class _Usage:
    tasks: int = 0
    tokens: int = 0
    concurrency: int = 0
    preview_fee: int = 0
    sandbox_fee: int = 0


@dataclass(frozen=True)
class QuotaDecision:
    """Structured admission result. http_status 429 is a quota refusal."""

    http_status: int
    body: dict[str, object]
    event: dict[str, object]


class QuotaGate:
    """Admit a Run only when this user still has credentials, budget, and quota."""

    def __init__(self, *, limits: Limits, capacity: WorkerCapacity) -> None:
        self._limits = limits
        self.capacity = capacity
        self._usage: dict[tuple[str, str], _Usage] = {}
        self._events: dict[str, list[dict[str, object]]] = {}

    def seed_usage(
        self,
        *,
        tenant_id: str,
        user_id: str,
        tasks: int = 0,
        tokens: int = 0,
        concurrency: int = 0,
        preview_fee: int = 0,
        sandbox_fee: int = 0,
    ) -> None:
        """Record consumption that already happened on the server ledger."""
        self._usage[(tenant_id, user_id)] = _Usage(
            tasks=tasks,
            tokens=tokens,
            concurrency=concurrency,
            preview_fee=preview_fee,
            sandbox_fee=sandbox_fee,
        )

    def events_for(self, tenant_id: str) -> list[dict[str, object]]:
        return list(self._events.get(tenant_id, []))

    def create_run(
        self,
        *,
        database_url: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        message: str,
        target_id: str,
        permission_profile: str,
        request_id: str,
        headers: dict[str, str] | None,
        credentials: str | None,
        budget: int | None,
        model: ModelClient | None,
    ) -> QuotaDecision:
        """Refuse before any worker, model, or durable Run is created."""
        del headers
        usage = self._usage.get((tenant_id, user_id), _Usage())
        kind = self._refusal_kind(usage, credentials=credentials, budget=budget)
        if kind is not None:
            return self._refuse(tenant_id, user_id, kind)
        self.capacity.acquire(tenant_id, user_id)
        try:
            if model is not None:
                model(message)
            from rxycode_server.runs.service import create_run as persist_run

            accepted = persist_run(
                database_url,
                tenant_id=tenant_id,
                session_id=session_id,
                message=message,
                target_id=target_id,
                permission_profile=permission_profile,
                request_id=request_id,
            )
        except Exception:
            self.capacity.release(tenant_id, user_id)
            raise
        return QuotaDecision(
            http_status=accepted.http_status,
            body={"status": accepted.status, "run_id": accepted.run_id},
            event={"type": "run.accepted", "tenant_id": tenant_id, "user_id": user_id},
        )

    def _refusal_kind(
        self,
        usage: _Usage,
        *,
        credentials: str | None,
        budget: int | None,
    ) -> str | None:
        if credentials is None or credentials == "":
            return "credentials"
        if budget is None or budget <= 0:
            return "budget"
        limits = self._limits
        if usage.tasks >= limits.tasks:
            return "task"
        if usage.tokens >= limits.tokens:
            return "token"
        if usage.concurrency >= limits.concurrency:
            return "concurrency"
        if usage.preview_fee >= limits.preview_fee:
            return "preview"
        if usage.sandbox_fee >= limits.sandbox_fee:
            return "sandbox"
        return None

    def _refuse(self, tenant_id: str, user_id: str, kind: str) -> QuotaDecision:
        limit = {
            "credentials": 0,
            "budget": 0,
            "task": self._limits.tasks,
            "token": self._limits.tokens,
            "concurrency": self._limits.concurrency,
            "preview": self._limits.preview_fee,
            "sandbox": self._limits.sandbox_fee,
        }[kind]
        event: dict[str, object] = {
            "type": "quota.exceeded",
            "kind": kind,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "limit": limit,
        }
        self._events.setdefault(tenant_id, []).append(event)
        body: dict[str, object] = {
            "error": "quota.exceeded",
            "kind": kind,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "limit": limit,
        }
        return QuotaDecision(http_status=429, body=body, event=event)
