"""Create a durable Run, its first event, and the outbox row in one transaction."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import Outbox, Run, RunEvent


class RunConflict(Exception):
    """The idempotency key already belongs to a different payload."""


class RunAlreadyActive(Exception):
    """This session already has an active Run."""


@dataclass(frozen=True)
class RunAccepted:
    http_status: int
    run_id: str
    status: str
    events_url: str


def _digest(
    message: str,
    target_id: str,
    permission_profile: str,
    request_id: str,
    session_id: str,
) -> str:
    payload = json.dumps(
        {
            "message": message,
            "permission_profile": permission_profile,
            "request_id": request_id,
            "session_id": session_id,
            "target_id": target_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _accepted(run_id: str) -> RunAccepted:
    return RunAccepted(
        http_status=202,
        run_id=run_id,
        status="queued",
        events_url=f"/api/v1/runs/{run_id}/events",
    )


def create_run(
    database_url: str,
    *,
    tenant_id: str,
    session_id: str,
    message: str,
    target_id: str,
    permission_profile: str,
    request_id: str,
    claimed_tenant_id: str | None = None,
    user_id: str | None = None,
    headers: dict[str, str] | None = None,
    credentials: str | None = None,
    budget: int | None = None,
    model: object | None = None,
    quota: object | None = None,
) -> RunAccepted:
    """Insert run + event + outbox. The caller's tenant wins over any body claim."""
    from rxycode_server.quotas.service import QuotaDecision, QuotaRefused, active_gate

    del claimed_tenant_id
    user = user_id or tenant_id
    gate = quota if quota is not None else active_gate()
    early = gate.precheck(
        tenant_id=tenant_id,
        user_id=user,
        message=message,
        headers=headers,
        credentials=credentials,
        budget=budget,
        model=model,
    )
    if isinstance(early, QuotaDecision):
        raise QuotaRefused(early)
    digest = _digest(message, target_id, permission_profile, request_id, session_id)
    engine = create_engine(database_url, poolclass=NullPool)
    held_worker = ""
    try:
        with Session(engine) as db:
            existing = db.scalars(
                select(Run).where(Run.tenant_id == tenant_id, Run.request_id == request_id)
            ).one_or_none()
            if existing is not None:
                if existing.input_digest != digest:
                    raise RunConflict(request_id)
                return _accepted(existing.id)
            decision = gate.reserve(db, tenant_id=tenant_id, user_id=user, message=message)
            if isinstance(decision, QuotaDecision):
                raise QuotaRefused(decision)
            held_worker = decision.worker_id
            run_id = uuid.uuid4().hex
            event_id = uuid.uuid4().hex
            try:
                if model is not None:
                    model(message)
                db.add(
                    Run(
                        id=run_id,
                        tenant_id=tenant_id,
                        session_id=session_id,
                        status="pending",
                        revision=0,
                        lease_epoch=0,
                        request_id=request_id,
                        input_digest=digest,
                        target_id=target_id,
                        event_seq=1,
                    )
                )
                db.flush()
                db.add(
                    RunEvent(
                        event_id=event_id,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        seq=1,
                        type="run.created",
                        payload={
                            "message": message,
                            "permission_profile": permission_profile,
                            "request_id": request_id,
                            "session_id": session_id,
                            "target_id": target_id,
                            "quota": {
                                "tokens": decision.tokens,
                                "preview_fee": 1,
                                "sandbox_fee": 1,
                                "user_id": user,
                                "worker_id": decision.worker_id,
                            },
                        },
                        at=datetime.now(timezone.utc),
                    )
                )
                db.flush()
                db.add(
                    Outbox(
                        id=uuid.uuid4().hex,
                        event_id=event_id,
                        dispatch_status="pending",
                        attempts=0,
                    )
                )
                db.commit()
                held_worker = ""
            except IntegrityError as exc:
                db.rollback()
                detail = str(exc.orig)
                if "uq_runs_one_active_per_session" in detail:
                    raise RunAlreadyActive(session_id) from exc
                if "uq_runs_tenant_request" in detail:
                    winner = db.scalars(
                        select(Run).where(Run.tenant_id == tenant_id, Run.request_id == request_id)
                    ).one()
                    if winner.input_digest != digest:
                        raise RunConflict(request_id) from exc
                    return _accepted(winner.id)
                raise
    finally:
        if held_worker:
            gate.release_worker(held_worker)
        engine.dispose()
    return _accepted(run_id)


def complete_run(
    database_url: str,
    *,
    run_id: str,
    tenant_id: str,
    user_id: str,
    quota: object | None = None,
) -> str:
    """Mark a Run succeeded and return only that Run's worker slot."""
    from rxycode_server.quotas.service import active_gate

    del user_id
    gate = quota if quota is not None else active_gate()
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != tenant_id:
                raise RunConflict(run_id)
            if row.status not in {"succeeded", "failed", "cancelled"}:
                row.status = "succeeded"
                db.commit()
    finally:
        engine.dispose()
    release_worker_for_run(database_url, run_id, quota=gate)
    return "succeeded"


def release_worker_for_run(
    database_url: str,
    run_id: str,
    quota: object | None = None,
) -> None:
    """Return the slot stored on this Run. A missing id is already gone."""
    from rxycode_server.quotas.service import active_gate

    gate = quota if quota is not None else active_gate()
    engine = create_engine(database_url, poolclass=NullPool)
    worker_id = ""
    try:
        with Session(engine) as db:
            event = db.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq == 1)
            ).one_or_none()
            if event is None:
                return
            payload = event.payload if isinstance(event.payload, dict) else {}
            quota_payload = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
            worker_id = str(quota_payload.get("worker_id") or "")
    finally:
        engine.dispose()
    if worker_id:
        gate.release_worker(worker_id)


def load_run(database_url: str, run_id: str) -> dict[str, str]:
    """Read the accepted task back from the durable event, not from the digest."""
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            event = db.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq == 1)
            ).one()
    finally:
        engine.dispose()
    payload = event.payload
    return {
        "message": str(payload["message"]),
        "permission_profile": str(payload["permission_profile"]),
        "session_id": str(payload["session_id"]),
        "target_id": str(payload["target_id"]),
    }
