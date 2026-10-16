"""Tenant token, task, concurrency, preview, and sandbox quotas.

The authenticated tenant and user are the only identity. Request headers are
ignored. A refusal records a quota.exceeded event, does not occupy a worker,
and does not call the model. Admitted runs add their cost to the durable
run.created event so the next admission sees it.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rxycode_server.persistence.models import Run, RunEvent

DEFAULT_LIMITS_TASKS = 100_000
DEFAULT_LIMITS_TOKENS = 10_000_000
DEFAULT_LIMITS_CONCURRENCY = 10_000
DEFAULT_LIMITS_FEE = 100_000


class WorkerFull(RuntimeError):
    """This user already holds the concurrency ceiling."""


class WorkerCapacity(Protocol):
    """The scheduler side of admission. Only an admitted Run occupies a worker."""

    workers: list[tuple[str, str, str]]

    def acquire(self, tenant_id: str, user_id: str, *, limit: int, ttl_seconds: float = 3600) -> str:
        """Occupy one worker, or refuse when the live count is at the ceiling."""

    def release(self, tenant_id: str, user_id: str) -> None:
        """Return the worker when the Run was not created."""


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


DEFAULT_LIMITS = Limits(
    tasks=DEFAULT_LIMITS_TASKS,
    tokens=DEFAULT_LIMITS_TOKENS,
    concurrency=DEFAULT_LIMITS_CONCURRENCY,
    preview_fee=DEFAULT_LIMITS_FEE,
    sandbox_fee=DEFAULT_LIMITS_FEE,
)


@dataclass
class _Usage:
    tasks: int = 0
    tokens: int = 0
    preview_fee: int = 0
    sandbox_fee: int = 0


@dataclass(frozen=True)
class QuotaDecision:
    """Structured admission result. http_status 429 is a quota refusal."""

    http_status: int
    body: dict[str, object]
    event: dict[str, object]


@dataclass(frozen=True)
class Reservation:
    """A worker is held until the Run row commits or the caller releases it."""

    tenant_id: str
    user_id: str
    tokens: int


class QuotaRefused(Exception):
    """create_run stopped before inserting a Run."""

    def __init__(self, decision: QuotaDecision) -> None:
        self.decision = decision
        super().__init__(str(decision.body.get("error", "quota.exceeded")))

    @property
    def http_status(self) -> int:
        return self.decision.http_status


class RunWorkers:
    """In-process worker slots used when the cloud scheduler is not injected."""

    def __init__(self) -> None:
        self.workers: list[tuple[str, str, str]] = []
        self._deadlines: dict[str, float] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    @property
    def live_ids(self) -> list[str]:
        return []

    def acquire(self, tenant_id: str, user_id: str, *, limit: int, ttl_seconds: float = 3600) -> str:
        self._reap()
        with self._lock:
            held = _held(self.workers, tenant_id, user_id)
            if limit < 1 or held >= limit:
                raise WorkerFull(f"{tenant_id}/{user_id} is at concurrency {limit}")
            worker_id = "worker-" + uuid.uuid4().hex[:8]
            self.workers.append((tenant_id, user_id, worker_id))
            self._deadlines[worker_id] = time.monotonic() + ttl_seconds
        timer = threading.Timer(ttl_seconds, self._reap)
        timer.daemon = True
        with self._lock:
            self._timers[worker_id] = timer
        timer.start()
        return worker_id

    def release(self, tenant_id: str, user_id: str) -> None:
        timer: threading.Timer | None = None
        with self._lock:
            for index in range(len(self.workers) - 1, -1, -1):
                owner, user, worker_id = self.workers[index]
                if owner == tenant_id and user == user_id:
                    del self.workers[index]
                    self._deadlines.pop(worker_id, None)
                    timer = self._timers.pop(worker_id, None)
                    break
        if timer is not None:
            timer.cancel()

    def _reap(self) -> None:
        now = time.monotonic()
        expired: list[threading.Timer | None] = []
        with self._lock:
            kept: list[tuple[str, str, str]] = []
            for owner, user, worker_id in self.workers:
                if self._deadlines.get(worker_id, now + 1) <= now:
                    expired.append(self._timers.pop(worker_id, None))
                    self._deadlines.pop(worker_id, None)
                else:
                    kept.append((owner, user, worker_id))
            self.workers[:] = kept
        for timer in expired:
            if timer is not None:
                timer.cancel()


def _held(workers: list[tuple[str, str, str]], tenant_id: str, user_id: str) -> int:
    return sum(1 for owner, user, _worker in workers if owner == tenant_id and user == user_id)


def _token_count(message: str) -> int:
    return len([part for part in message.split() if part])


class QuotaGate:
    """Admit a Run only when this user still has credentials, budget, and quota."""

    def __init__(
        self,
        *,
        limits: Limits,
        capacity: WorkerCapacity,
        worker_ttl: float = 3600,
    ) -> None:
        self._limits = limits
        self.capacity = capacity
        self._worker_ttl = worker_ttl
        self._events: dict[str, list[dict[str, object]]] = {}

    def events_for(self, tenant_id: str) -> list[dict[str, object]]:
        return list(self._events.get(tenant_id, []))

    def precheck(
        self,
        *,
        tenant_id: str,
        user_id: str,
        message: str,
        headers: dict[str, str] | None,
        credentials: str | None,
        budget: int | None,
        model: ModelClient | None,
    ) -> QuotaDecision | None:
        """Refuse before opening a database when the request itself cannot run."""
        del headers
        if model is not None and (credentials is None or credentials == ""):
            return self._refuse(tenant_id, user_id, "credentials")
        if model is not None and (budget is None or budget <= 0):
            return self._refuse(tenant_id, user_id, "budget")
        incoming = _token_count(message)
        if incoming > self._limits.tokens:
            return self._refuse(tenant_id, user_id, "token")
        return None

    def reserve(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        message: str,
    ) -> QuotaDecision | Reservation:
        """Reserve one worker, or return the refusal. The Run row is not inserted here."""
        usage = _usage(db, tenant_id)
        incoming = _token_count(message)
        limits = self._limits
        if usage.tasks >= limits.tasks:
            return self._refuse(tenant_id, user_id, "task")
        if usage.tokens + incoming > limits.tokens:
            return self._refuse(tenant_id, user_id, "token")
        if usage.preview_fee + 1 > limits.preview_fee:
            return self._refuse(tenant_id, user_id, "preview")
        if usage.sandbox_fee + 1 > limits.sandbox_fee:
            return self._refuse(tenant_id, user_id, "sandbox")
        try:
            self.capacity.acquire(
                tenant_id,
                user_id,
                limit=limits.concurrency,
                ttl_seconds=self._worker_ttl,
            )
        except Exception as exc:
            if isinstance(exc, WorkerFull) or exc.__class__.__name__ == "CapacityFull":
                return self._refuse(tenant_id, user_id, "concurrency")
            raise
        return Reservation(tenant_id=tenant_id, user_id=user_id, tokens=incoming)

    def release(self, tenant_id: str, user_id: str) -> None:
        self.capacity.release(tenant_id, user_id)

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


_installed: QuotaGate | None = None
_default: QuotaGate | None = None


def install_gate(gate: QuotaGate | None) -> None:
    """Install the process gate. None restores the high default ceilings."""
    global _installed
    _installed = gate


def active_gate() -> QuotaGate:
    """Return the installed gate, or a process-wide gate with high ceilings."""
    global _default
    if _installed is not None:
        return _installed
    if _default is None:
        _default = QuotaGate(limits=DEFAULT_LIMITS, capacity=RunWorkers())
    return _default


def _usage(db: Session, tenant_id: str) -> _Usage:
    task_count = db.scalar(select(func.count()).select_from(Run).where(Run.tenant_id == tenant_id))
    events = db.scalars(
        select(RunEvent).where(RunEvent.tenant_id == tenant_id, RunEvent.type == "run.created")
    ).all()
    usage = _Usage(tasks=int(task_count or 0))
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
        message = str(payload.get("message") or "")
        usage.tokens += int(quota.get("tokens") or _token_count(message))
        usage.preview_fee += int(quota.get("preview_fee") or 0)
        usage.sandbox_fee += int(quota.get("sandbox_fee") or 0)
    return usage
