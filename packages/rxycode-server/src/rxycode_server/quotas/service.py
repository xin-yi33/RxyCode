"""Tenant token, task, concurrency, preview, and sandbox quotas.

The authenticated tenant and user are the only identity. Request headers are
ignored. A refusal records a quota.exceeded event, does not occupy a worker,
and does not call the model. Admitted runs add their cost to the durable
run.created event so the next admission sees it.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from rxycode_server.persistence.models import Run, RunEvent, UsageRecord

DEFAULT_LIMITS_TASKS = 100_000
DEFAULT_LIMITS_TOKENS = 10_000_000
DEFAULT_LIMITS_CONCURRENCY = 10_000
DEFAULT_LIMITS_FEE = 100_000


class WorkerFull(RuntimeError):
    """This user already holds the concurrency ceiling."""


class WorkerCapacity(Protocol):
    """The scheduler side of admission. Only an admitted Run occupies a worker."""

    workers: list[tuple[str, str, str]]

    def acquire(
        self,
        tenant_id: str,
        user_id: str,
        *,
        limit: int,
        held: int,
        ttl_seconds: float = 3600,
    ) -> str:
        """Refuse when the durable held count is already at the ceiling."""

    def release_worker(self, worker_id: str) -> None:
        """Return the exact worker reserved for one Run."""


class ModelClient(Protocol):
    """A model call. The gate invokes it only after admission succeeds."""

    def __call__(self, prompt: str) -> str:
        """Generate a reply for this prompt."""


@dataclass(frozen=True)
class Limits:
    """Server-side ceilings for one user inside one tenant.

    ``window_seconds`` (WEB-W9-B4): when set, tasks/tokens only count runs
    created inside the trailing window (daily accounting uses ``86400``);
    ``None`` keeps the original all-history accounting. In window mode token
    usage is the real ``usage_records.tokens`` sum for those runs, and the
    incoming message's estimate is added at reserve time.
    ``queue_max``: global cap on ``pending`` runs, checked before any worker
    slot is acquired; hitting it refuses with ``kind="queue"``.
    """

    tasks: int
    tokens: int
    concurrency: int
    preview_fee: int
    sandbox_fee: int
    window_seconds: int | None = None
    queue_max: int | None = None


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
    worker_id: str


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

    def acquire(
        self,
        tenant_id: str,
        user_id: str,
        *,
        limit: int,
        held: int,
        ttl_seconds: float = 3600,
    ) -> str:
        del tenant_id, user_id, ttl_seconds
        if limit < 1 or held >= limit:
            raise WorkerFull(f"concurrency ceiling {limit} already holds {held}")
        return "worker-" + uuid.uuid4().hex[:8]

    def release_worker(self, worker_id: str) -> None:
        timer: threading.Timer | None = None
        with self._lock:
            for index, (_owner, _user, current) in enumerate(self.workers):
                if current == worker_id:
                    del self.workers[index]
                    self._deadlines.pop(worker_id, None)
                    timer = self._timers.pop(worker_id, None)
                    break
        if timer is not None:
            timer.cancel()


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
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"{tenant_id}:{user_id}"},
        )
        usage = _usage(db, tenant_id, self._limits.window_seconds, user_id)
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
        if limits.queue_max is not None:
            pending = db.scalar(
                select(func.count()).select_from(Run).where(Run.status == "pending")
            )
            if int(pending or 0) >= limits.queue_max:
                return self._refuse(tenant_id, user_id, "queue")
        held = _active_slots(db, tenant_id, user_id, self._worker_ttl)
        try:
            worker_id = self.capacity.acquire(
                tenant_id,
                user_id,
                limit=limits.concurrency,
                held=held,
                ttl_seconds=self._worker_ttl,
            )
        except Exception as exc:
            if isinstance(exc, WorkerFull) or exc.__class__.__name__ == "CapacityFull":
                return self._refuse(tenant_id, user_id, "concurrency")
            raise
        return Reservation(
            tenant_id=tenant_id,
            user_id=user_id,
            tokens=incoming,
            worker_id=worker_id,
        )

    def release_worker(self, worker_id: str) -> None:
        self.capacity.release_worker(worker_id)

    def _refuse(self, tenant_id: str, user_id: str, kind: str) -> QuotaDecision:
        limit = {
            "credentials": 0,
            "budget": 0,
            "task": self._limits.tasks,
            "token": self._limits.tokens,
            "concurrency": self._limits.concurrency,
            "preview": self._limits.preview_fee,
            "sandbox": self._limits.sandbox_fee,
            "queue": self._limits.queue_max or 0,
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


_ACTIVE = {"pending", "running", "leased", "cancel_requested", "waiting_approval"}


def _active_slots(db: Session, tenant_id: str, user_id: str, ttl_seconds: float) -> int:
    """Count this user's runs that are still active and inside the TTL."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
    rows = db.execute(
        select(Run.status, RunEvent.payload, RunEvent.at)
        .join(RunEvent, (RunEvent.run_id == Run.id) & (RunEvent.seq == 1))
        .where(Run.tenant_id == tenant_id, RunEvent.type == "run.created")
    ).all()
    held = 0
    for status, payload, created_at in rows:
        if status not in _ACTIVE:
            continue
        quota = payload.get("quota") if isinstance(payload, dict) else {}
        owner = str((quota or {}).get("user_id") or "")
        if owner and owner != user_id:
            continue
        moment = created_at
        if isinstance(moment, datetime) and moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if isinstance(moment, datetime) and moment < cutoff:
            continue
        held += 1
    return held


def _owned(payload: object, user_id: str | None) -> bool:
    """Daily quota is this user's. Another user on the same tenant, including
    a super account, does not spend this user's tokens or tasks."""
    if not user_id:
        return True
    body = payload if isinstance(payload, dict) else {}
    quota = body.get("quota") if isinstance(body.get("quota"), dict) else {}
    return str(quota.get("user_id") or "") == user_id


def _usage(
    db: Session,
    tenant_id: str,
    window_seconds: int | None = None,
    user_id: str | None = None,
) -> _Usage:
    if window_seconds is not None:
        # WEB-W9-B4: only this user's runs inside the trailing window count.
        # Token usage is the real usage_records.tokens sum for those runs.
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        run_ids = db.scalars(
            select(Run.id)
            .join(RunEvent, (RunEvent.run_id == Run.id) & (RunEvent.seq == 1))
            .where(
                Run.tenant_id == tenant_id,
                Run.created_at.isnot(None),
                Run.created_at >= cutoff,
                RunEvent.type == "run.created",
                RunEvent.payload["quota"]["user_id"].astext == user_id,
            )
        ).all() if user_id else db.scalars(
            select(Run.id).where(
                Run.tenant_id == tenant_id,
                Run.created_at.isnot(None),
                Run.created_at >= cutoff,
            )
        ).all()
        usage = _Usage(tasks=len(run_ids))
        if run_ids:
            tokens = db.scalar(
                select(func.coalesce(func.sum(UsageRecord.tokens), 0)).where(
                    UsageRecord.run_id.in_(run_ids)
                )
            )
            usage.tokens = int(tokens or 0)
        return usage
    events = db.scalars(
        select(RunEvent).where(RunEvent.tenant_id == tenant_id, RunEvent.type == "run.created")
    ).all()
    if user_id is None:
        task_count = db.scalar(
            select(func.count()).select_from(Run).where(Run.tenant_id == tenant_id)
        )
        usage = _Usage(tasks=int(task_count or 0))
        owned_events = events
    else:
        usage = _Usage()
        owned_events = [event for event in events if _owned(event.payload, user_id)]
        usage.tasks = len(owned_events)
    for event in owned_events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
        message = str(payload.get("message") or "")
        usage.tokens += int(quota.get("tokens") or _token_count(message))
        usage.preview_fee += int(quota.get("preview_fee") or 0)
        usage.sandbox_fee += int(quota.get("sandbox_fee") or 0)
    return usage
