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


def _digest(message: str, target_id: str, permission_profile: str, request_id: str) -> str:
    payload = json.dumps(
        {
            "message": message,
            "permission_profile": permission_profile,
            "request_id": request_id,
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
) -> RunAccepted:
    """Insert run + event + outbox. The caller's tenant wins over any body claim."""
    del claimed_tenant_id
    digest = _digest(message, target_id, permission_profile, request_id)
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            existing = db.scalars(
                select(Run).where(Run.tenant_id == tenant_id, Run.request_id == request_id)
            ).one_or_none()
            if existing is not None:
                if existing.input_digest != digest:
                    raise RunConflict(request_id)
                return _accepted(existing.id)
            run_id = uuid.uuid4().hex
            event_id = uuid.uuid4().hex
            try:
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
                        payload={"request_id": request_id, "target_id": target_id},
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
        engine.dispose()
    return _accepted(run_id)
