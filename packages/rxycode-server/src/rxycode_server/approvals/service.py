"""Durable approval requests. A decision is one CAS update and never runs a tool."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.persistence.models import Approval, Outbox, Run, RunEvent


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


class ApprovalStale(Exception):
    """The approval was already decided, cancelled, or past its deadline."""

    def __init__(self, approval_id: str) -> None:
        super().__init__(approval_id)
        self.approval_id = approval_id
        self.http_status = 409
        self.code = "APPROVAL_STALE"


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    current = _aware(value)
    assert current is not None
    return current


def _lease_is_current(run: Run, worker_id: str, epoch: int, now: datetime) -> bool:
    if run.lease_owner != worker_id or int(run.lease_epoch) != int(epoch):
        return False
    if run.status not in {"leased", "running", "cancel_requested"}:
        return False
    until = _aware(run.lease_until)
    return until is not None and until >= now


def _append(db: Session, run: Run, event_type: str, payload: dict[str, Any]) -> None:
    retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id))
    seq = max(int(run.event_seq or 0), int(retained or 0)) + 1
    run.event_seq = seq
    event_id = uuid.uuid4().hex
    db.add(
        RunEvent(
            event_id=event_id,
            run_id=run.id,
            tenant_id=run.tenant_id,
            seq=seq,
            type=event_type,
            payload=payload,
            at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    db.add(Outbox(id=uuid.uuid4().hex, event_id=event_id, dispatch_status="pending", attempts=0))


def _lock_run(db: Session, tenant_id: str, run_id: str) -> Run:
    return db.execute(
        select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
    ).scalar_one()


def request_approval(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    tool: str,
    permission_scope: str,
    arguments: dict[str, Any],
    deadline: datetime,
    worker_id: str,
    epoch: int,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    """Persist the ask, emit approval.requested, and release the worker lease."""
    engine = _engine(database_url)
    approval_id = uuid.uuid4().hex
    stored_attempt = attempt_id or f"att_{uuid.uuid4().hex}"
    try:
        with Session(engine) as db:
            run = _lock_run(db, tenant_id, run_id)
            now = datetime.now(timezone.utc)
            if not _lease_is_current(run, worker_id, epoch, now):
                raise ApprovalStale(approval_id)
            db.add(
                Approval(
                    id=approval_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    call_id=call_id,
                    status="pending",
                    revision=0,
                    deadline=_aware(deadline),
                )
            )
            db.flush()
            _append(
                db,
                run,
                "approval.requested",
                {
                    "approval_id": approval_id,
                    "call_id": call_id,
                    "tool": tool,
                    "permission_scope": permission_scope,
                    "arguments": arguments,
                    "attempt_id": stored_attempt,
                    "revision": 0,
                },
            )
            run.status = "waiting_approval"
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
    finally:
        engine.dispose()
    return {
        "approval_id": approval_id,
        "status": "pending",
        "revision": 0,
        "attempt_id": stored_attempt,
    }


def _requested_payload(db: Session, approval_id: str) -> dict[str, Any]:
    events = db.scalars(
        select(RunEvent).where(RunEvent.type == "approval.requested").order_by(RunEvent.seq)
    ).all()
    for event in events:
        payload = event.payload or {}
        if payload.get("approval_id") == approval_id:
            return dict(payload)
    return {}


def list_pending(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return asks that are still pending at `now`, including the original scope."""
    current = _now(now)
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            rows = db.scalars(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.run_id == run_id,
                    Approval.status == "pending",
                )
            ).all()
            found: list[dict[str, Any]] = []
            for row in rows:
                deadline = _aware(row.deadline)
                if deadline is not None and deadline <= current:
                    continue
                payload = _requested_payload(db, row.id)
                found.append(
                    {
                        "approval_id": row.id,
                        "call_id": row.call_id,
                        "tool": payload.get("tool", ""),
                        "permission_scope": payload.get("permission_scope", ""),
                        "arguments": payload.get("arguments", {}),
                        "attempt_id": payload.get("attempt_id", ""),
                        "status": row.status,
                        "revision": int(row.revision or 0),
                        "deadline": deadline.isoformat() if deadline is not None else None,
                    }
                )
            return found
    finally:
        engine.dispose()


def get_approval(database_url: str, *, tenant_id: str, approval_id: str) -> dict[str, Any] | None:
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row = db.get(Approval, approval_id)
            if row is None or row.tenant_id != tenant_id:
                return None
            payload = _requested_payload(db, row.id)
            return {
                "approval_id": row.id,
                "run_id": row.run_id,
                "call_id": row.call_id,
                "status": row.status,
                "revision": int(row.revision or 0),
                "attempt_id": str(payload.get("attempt_id") or ""),
                "tool": payload.get("tool", ""),
                "permission_scope": payload.get("permission_scope", ""),
            }
    finally:
        engine.dispose()


def _reject_if_closed(row: Approval, expected_revision: int, now: datetime) -> None:
    if int(row.revision or 0) != int(expected_revision) or row.status != "pending":
        raise ApprovalStale(row.id)
    deadline = _aware(row.deadline)
    if deadline is not None and deadline <= now:
        row.status = "expired"
        row.revision = int(row.revision or 0) + 1
        raise ApprovalStale(row.id)


def decide_approval(
    database_url: str,
    *,
    tenant_id: str,
    approval_id: str,
    decision: str,
    expected_revision: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record one decision. This function does not execute a tool."""
    if decision not in {"approved", "rejected"}:
        raise ApprovalStale(approval_id)
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Approval)
                .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
                .with_for_update()
            ).scalar_one()
            current = datetime.now(timezone.utc) if now is None else _now(now)
            try:
                _reject_if_closed(row, expected_revision, current)
            except ApprovalStale:
                db.commit()
                raise
            row.status = decision
            row.revision = int(row.revision or 0) + 1
            run = _lock_run(db, tenant_id, row.run_id)
            _append(
                db,
                run,
                "approval.resolved",
                {
                    "approval_id": row.id,
                    "call_id": row.call_id,
                    "decision": decision,
                    "revision": int(row.revision),
                },
            )
            run.lease_owner = None
            run.lease_until = None
            run.status = "pending" if decision == "approved" else "cancelled"
            run.revision = int(run.revision or 0) + 1
            revision = int(row.revision)
            db.commit()
    finally:
        engine.dispose()
    return {"status": decision, "revision": revision, "http_status": 200}


def cancel_approval(
    database_url: str,
    *,
    tenant_id: str,
    approval_id: str,
    expected_revision: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Cancel a pending ask. A later approve is APPROVAL_STALE."""
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Approval)
                .where(Approval.id == approval_id, Approval.tenant_id == tenant_id)
                .with_for_update()
            ).scalar_one()
            current = datetime.now(timezone.utc) if now is None else _now(now)
            try:
                _reject_if_closed(row, expected_revision, current)
            except ApprovalStale:
                db.commit()
                raise
            row.status = "cancelled"
            row.revision = int(row.revision or 0) + 1
            run = _lock_run(db, tenant_id, row.run_id)
            _append(
                db,
                run,
                "approval.resolved",
                {
                    "approval_id": row.id,
                    "call_id": row.call_id,
                    "decision": "cancelled",
                    "revision": int(row.revision),
                },
            )
            run.status = "cancelled"
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
    finally:
        engine.dispose()
    return {"status": "cancelled", "http_status": 200}
