"""Durable approval requests. A decision is one CAS update and never runs a tool."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.events.store import append_event_in, append_run_status
from rxycode_server.persistence.models import Approval, Run, RunEvent


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
    append_event_in(db, run, event_type, payload)


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
    approval_id: str | None = None,
    command: str = "",
    workdir: str = "",
    source_call_id: str = "",
    sandbox_id: str = "",
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the ask with the Harness checkpoint, emit approval.requested,
    and release the worker lease."""
    engine = _engine(database_url)
    approval_id = approval_id or uuid.uuid4().hex
    stored_attempt = attempt_id or f"att_{uuid.uuid4().hex}"
    try:
        with Session(engine) as db:
            run = _lock_run(db, tenant_id, run_id)
            now = datetime.now(timezone.utc)
            # ``cancel_requested`` IS a current lease for settle purposes,
            # but it must never be parked: a cancellation landing just
            # before the ask would otherwise be overwritten by
            # waiting_approval, and approving that ask requeues a run the
            # user already killed (audit W8-r2).
            if not _lease_is_current(run, worker_id, epoch, now) or (
                run.status == "cancel_requested"
            ):
                raise ApprovalStale(approval_id)
            db.add(
                Approval(
                    id=approval_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    call_id=call_id,
                    kind="approval",
                    status="pending",
                    revision=0,
                    deadline=_aware(deadline),
                    checkpoint=dict(checkpoint) if checkpoint is not None else None,
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
                    "command": command,
                    "workdir": workdir,
                    "source_call_id": str(source_call_id or ""),
                    # Which confined namespace asked — a later claimant uses
                    # it to prove that supervisor is dead before replaying
                    # the approved call (audit W8-r2).
                    "sandbox_id": str(sandbox_id or ""),
                    "revision": 0,
                },
            )
            run.status = "waiting_approval"
            append_run_status(db, run, "waiting_approval", epoch)
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


def request_question(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    question_id: str,
    question: str,
    header: str,
    options: list[dict[str, str]],
    deadline: datetime,
    worker_id: str,
    epoch: int,
    checkpoint: dict[str, Any],
    sandbox_id: str = "",
) -> dict[str, Any]:
    """Park the run on one user question: store the checkpoint and the
    question, emit question.requested, release the lease. Questions are not
    side effects, so no journal entry is written for them."""
    engine = _engine(database_url)
    approval_id = uuid.uuid4().hex
    try:
        with Session(engine) as db:
            run = _lock_run(db, tenant_id, run_id)
            now = datetime.now(timezone.utc)
            if not _lease_is_current(run, worker_id, epoch, now) or (
                run.status == "cancel_requested"
            ):
                raise ApprovalStale(question_id)
            db.add(
                Approval(
                    id=approval_id,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    call_id=question_id,
                    kind="question",
                    status="pending",
                    revision=0,
                    deadline=_aware(deadline),
                    checkpoint=dict(checkpoint),
                )
            )
            db.flush()
            _append(
                db,
                run,
                "question.requested",
                {
                    "approval_id": approval_id,
                    "question_id": question_id,
                    "question": question,
                    "prompt": question,
                    "header": header,
                    "options": [dict(option) for option in options],
                    "input_type": "choice" if options else "text",
                    "sandbox_id": str(sandbox_id or ""),
                    "revision": 0,
                },
            )
            run.status = "waiting_approval"
            append_run_status(db, run, "waiting_approval", epoch)
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
    finally:
        engine.dispose()
    return {"approval_id": approval_id, "question_id": question_id, "status": "pending"}


def _question_row(db: Session, tenant_id: str, run_id: str, question_id: str) -> Approval | None:
    return db.execute(
        select(Approval)
        .where(
            Approval.tenant_id == tenant_id,
            Approval.run_id == run_id,
            Approval.kind == "question",
            Approval.call_id == question_id,
        )
        .with_for_update()
    ).scalar_one_or_none()


def _question_payload(db: Session, approval_id: str) -> dict[str, Any]:
    events = db.scalars(
        select(RunEvent).where(RunEvent.type == "question.requested").order_by(RunEvent.seq)
    ).all()
    for event in events:
        payload = event.payload or {}
        if payload.get("approval_id") == approval_id:
            return dict(payload)
    return {}


def pending_question(
    database_url: str, *, tenant_id: str, run_id: str, question_id: str
) -> dict[str, Any] | None:
    """The durable question still awaiting an answer, or None."""
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.run_id == run_id,
                    Approval.kind == "question",
                    Approval.call_id == question_id,
                )
            ).scalar_one_or_none()
            if row is None or row.status != "pending":
                return None
            payload = _question_payload(db, row.id)
            return {
                "approval_id": row.id,
                "question_id": question_id,
                "options": list(payload.get("options") or []),
            }
    finally:
        engine.dispose()


def list_pending_questions_durable(
    database_url: str, *, tenant_id: str, run_id: str
) -> list[dict[str, str]]:
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            rows = db.scalars(
                select(Approval).where(
                    Approval.tenant_id == tenant_id,
                    Approval.run_id == run_id,
                    Approval.kind == "question",
                    Approval.status == "pending",
                )
            ).all()
            found = []
            for row in rows:
                payload = _question_payload(db, row.id)
                found.append(
                    {
                        "question_id": str(row.call_id),
                        "prompt": str(payload.get("question") or ""),
                        "header": str(payload.get("header") or ""),
                        "options": list(payload.get("options") or []),
                    }
                )
            return found
    finally:
        engine.dispose()


def answer_question(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    question_id: str,
    answer: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Record the user's answer and make the run claimable again. The answer
    is validated against the offered option values, exactly as the in-process
    question broker does. This never runs a tool."""
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row = _question_row(db, tenant_id, run_id, question_id)
            if row is None:
                raise ApprovalStale(question_id)
            current = datetime.now(timezone.utc) if now is None else _now(now)
            if row.status != "pending":
                raise ApprovalStale(question_id)
            deadline = _aware(row.deadline)
            if deadline is not None and deadline <= current:
                raise ApprovalStale(question_id)
            run = _lock_run(db, tenant_id, run_id)
            if run.status != "waiting_approval":
                raise ApprovalStale(question_id)
            payload = _question_payload(db, row.id)
            values = {str(o.get("value", o.get("label", ""))) for o in payload.get("options") or []}
            if values and answer not in values:
                raise ValueError("answer is not one of the offered option values")
            row.status = "answered"
            row.answer = answer
            row.revision = int(row.revision or 0) + 1
            _append(
                db,
                run,
                "question.resolved",
                {
                    "approval_id": row.id,
                    "question_id": question_id,
                    "answer": answer,
                    "revision": int(row.revision),
                },
            )
            run.status = "pending"
            append_run_status(db, run, "pending")
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
            return {"status": "answered", "revision": int(row.revision)}
    finally:
        engine.dispose()


def consume_answered_question(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    approval_id: str,
    worker_id: str,
    epoch: int,
) -> dict[str, Any] | None:
    """Hand the answer to exactly one claimant. ``answered`` becomes
    ``consumed`` in the same transaction the lease is checked, so a second
    claim can never resume the same parked turn twice."""
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Approval)
                .where(
                    Approval.id == approval_id,
                    Approval.tenant_id == tenant_id,
                    Approval.run_id == run_id,
                    Approval.kind == "question",
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None or row.status != "answered":
                return None
            run = _lock_run(db, tenant_id, run_id)
            if not _lease_is_current(run, worker_id, epoch, datetime.now(timezone.utc)):
                return None
            row.status = "consumed"
            row.revision = int(row.revision or 0) + 1
            db.commit()
            return {"approval_id": row.id, "question_id": str(row.call_id), "answer": str(row.answer or "")}
    finally:
        engine.dispose()


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
                    Approval.kind == "approval",
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
                "kind": str(row.kind or "approval"),
                "answer": row.answer,
                "checkpoint": dict(row.checkpoint or {}),
                "status": row.status,
                "revision": int(row.revision or 0),
                "attempt_id": str(payload.get("attempt_id") or ""),
                "tool": payload.get("tool", ""),
                "permission_scope": payload.get("permission_scope", ""),
                "command": str(payload.get("command") or ""),
                "workdir": str(payload.get("workdir") or ""),
                "source_call_id": str(payload.get("source_call_id") or ""),
                "sandbox_id": str(payload.get("sandbox_id") or ""),
                # The stored verbatim call arguments — resume executes THIS,
                # not a summary (the run was approved for these exact args).
                "arguments": dict(payload.get("arguments") or {}),
            }
    finally:
        engine.dispose()


def _closed_reason(row: Approval, expected_revision: int, now: datetime) -> str | None:
    if int(row.revision or 0) != int(expected_revision) or row.status != "pending":
        return "stale"
    deadline = _aware(row.deadline)
    if deadline is not None and deadline <= now:
        return "expired"
    return None


def _mark_expired(db: Session, row: Approval) -> None:
    """Expire the ask and leave the session free for another run."""
    row.status = "expired"
    row.revision = int(row.revision or 0) + 1
    run = _lock_run(db, row.tenant_id, row.run_id)
    _append(
        db,
        run,
        "approval.resolved",
        {
            "approval_id": row.id,
            "call_id": row.call_id,
            "decision": "expired",
            "revision": int(row.revision),
        },
    )
    run.status = "cancelled"
    append_run_status(db, run, "cancelled")
    run.lease_owner = None
    run.lease_until = None
    run.revision = int(run.revision or 0) + 1


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
            if row.kind != "approval":
                raise ApprovalStale(row.id)
            current = datetime.now(timezone.utc) if now is None else _now(now)
            reason = _closed_reason(row, expected_revision, current)
            if reason == "expired":
                _mark_expired(db, row)
                db.commit()
                raise ApprovalStale(row.id)
            if reason == "stale":
                raise ApprovalStale(row.id)
            run = _lock_run(db, tenant_id, row.run_id)
            # A late decision must never resurrect a run that already moved
            # on: the only live pairing is run.status == waiting_approval.
            # A cancelled/terminal/re-claimed run makes this ask stale —
            # "approve after cancel" cannot restart the operation.
            if run.status != "waiting_approval":
                raise ApprovalStale(row.id)
            row.status = decision
            row.revision = int(row.revision or 0) + 1
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
            append_run_status(db, run, str(run.status))
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
            reason = _closed_reason(row, expected_revision, current)
            if reason == "expired":
                _mark_expired(db, row)
                db.commit()
                raise ApprovalStale(row.id)
            if reason == "stale":
                raise ApprovalStale(row.id)
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
            append_run_status(db, run, "cancelled")
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
    finally:
        engine.dispose()
    return {"status": "cancelled", "http_status": 200}


def pause_under_lock(
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
    command: str,
    workdir: str,
    write_checkpoint: Callable[[str, str, str], None],
) -> dict[str, Any]:
    """Serialize pauses for one run so a stale epoch cannot overwrite the checkpoint."""
    engine = _engine(database_url)
    lock = engine.connect()
    try:
        lock.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": run_id})
        lock.commit()
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id).with_for_update()
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if run is None or run.tenant_id != tenant_id or not _lease_is_current(
                run, worker_id, epoch, now
            ) or run.status == "cancel_requested":
                raise ApprovalStale(run_id)
            event = db.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq == 1)
            ).one()
            if str(event.payload.get("permission_profile") or "") == "full_auto":
                return {"asked": False, "approval_id": None, "executed": False}
            session_id = str(event.payload["session_id"])
        approval_id = uuid.uuid4().hex
        attempt_id = f"att_{uuid.uuid4().hex}"
        write_checkpoint(session_id, approval_id, attempt_id)
        with Session(engine) as db:
            run = _lock_run(db, tenant_id, run_id)
            if not _lease_is_current(
                run, worker_id, epoch, datetime.now(timezone.utc)
            ) or run.status == "cancel_requested":
                raise ApprovalStale(approval_id)
            stored_arguments = dict(arguments)
            stored_arguments["command"] = command
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
                    "arguments": stored_arguments,
                    "attempt_id": attempt_id,
                    "command": command,
                    "workdir": workdir,
                    "revision": 0,
                },
            )
            run.status = "waiting_approval"
            append_run_status(db, run, "waiting_approval", epoch)
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
            return {"asked": True, "approval_id": approval_id, "executed": False}
    finally:
        try:
            lock.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                {"key": run_id},
            )
            lock.commit()
            lock.close()
        except Exception:
            pass
        engine.dispose()


def prepare_pause(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    worker_id: str,
    epoch: int,
) -> dict[str, str] | None:
    """Confirm tenant and lease before any checkpoint write."""
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id).with_for_update()
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if run is None or run.tenant_id != tenant_id:
                return None
            if not _lease_is_current(run, worker_id, epoch, now):
                return None
            if run.status == "cancel_requested":
                return None
            event = db.scalars(
                select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq == 1)
            ).one()
            return {
                "session_id": str(event.payload["session_id"]),
                "permission_profile": str(event.payload["permission_profile"]),
            }
    finally:
        engine.dispose()


def settle_run(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    worker_id: str,
    epoch: int,
    status: str,
) -> bool:
    """Terminalize only the lease epoch this resume just claimed."""
    if status not in {"succeeded", "cancelled", "failed", "recovery_required"}:
        return False
    engine = _engine(database_url)
    try:
        with Session(engine) as db:
            run = _lock_run(db, tenant_id, run_id)
            now = datetime.now(timezone.utc)
            if not _lease_is_current(run, worker_id, epoch, now):
                return False
            run.status = status
            append_run_status(db, run, status, epoch)
            run.lease_owner = None
            run.lease_until = None
            run.revision = int(run.revision or 0) + 1
            db.commit()
            return True
    finally:
        engine.dispose()
