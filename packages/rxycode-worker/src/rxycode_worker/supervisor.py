"""Claim a Run with a fenced lease. A stale epoch cannot commit a terminal status."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


class LeaseRejected(Exception):
    """The worker's lease epoch is no longer the one stored in the database."""


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


def claim(database_url: str, run_id: str, worker_id: str, *, ttl_seconds: int = 30) -> int | None:
    """Take the Run if it is free or its previous lease has expired."""
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'leased',
                        lease_owner = :worker,
                        lease_epoch = lease_epoch + 1,
                        lease_until = clock_timestamp() + (:ttl * interval '1 second'),
                        revision = revision + 1
                    WHERE id = :run_id
                      AND status IN ('pending', 'leased', 'running')
                      AND (lease_owner IS NULL OR lease_until < clock_timestamp())
                    RETURNING lease_epoch
                    """
                ),
                {"worker": worker_id, "ttl": ttl_seconds, "run_id": run_id},
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return None
    return int(row[0])


def renew_lease(
    database_url: str,
    run_id: str,
    worker_id: str,
    epoch: int,
    *,
    ttl_seconds: int = 30,
) -> int:
    """Extend the same epoch. A different owner or a stale epoch is rejected."""
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET lease_until = clock_timestamp() + (:ttl * interval '1 second'),
                        revision = revision + 1
                    WHERE id = :run_id
                      AND lease_owner = :worker
                      AND lease_epoch = :epoch
                      AND status IN ('leased', 'running', 'cancel_requested')
                      AND lease_until >= clock_timestamp()
                    RETURNING lease_epoch
                    """
                ),
                {
                    "ttl": ttl_seconds,
                    "run_id": run_id,
                    "worker": worker_id,
                    "epoch": epoch,
                },
            ).first()
    finally:
        engine.dispose()
    if row is None:
        raise LeaseRejected(run_id)
    return int(row[0])


def commit_terminal(
    database_url: str,
    run_id: str,
    worker_id: str,
    epoch: int,
    status: str,
) -> None:
    """Write a terminal status only when this epoch still owns an unexpired lease."""
    if status not in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"terminal status required, got {status}")
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :status,
                        revision = revision + 1
                    WHERE id = :run_id
                      AND lease_owner = :worker
                      AND lease_epoch = :epoch
                      AND status IN ('leased', 'running')
                      AND lease_until >= clock_timestamp()
                    RETURNING id
                    """
                ),
                {
                    "status": status,
                    "run_id": run_id,
                    "worker": worker_id,
                    "epoch": epoch,
                },
            ).first()
    finally:
        engine.dispose()
    if row is None:
        raise LeaseRejected(run_id)


def request_cancel(database_url: str, run_id: str) -> str:
    """Record cancel_requested once and notify through the outbox. Do not mark cancelled."""
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            current = conn.execute(
                text("SELECT status, tenant_id FROM runs WHERE id = :id"),
                {"id": run_id},
            ).one()
            if current.status != "pending" and current.status not in {"leased", "running"}:
                return str(current.status)
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'cancel_requested',
                        revision = revision + 1
                    WHERE id = :id
                      AND status IN ('pending', 'leased', 'running')
                    """
                ),
                {"id": run_id},
            )
            event_id = conn.execute(text("SELECT gen_random_uuid()::text")).scalar()
            seq = conn.execute(
                text("SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = :id"),
                {"id": run_id},
            ).scalar()
            conn.execute(
                text(
                    """
                    INSERT INTO run_events
                        (event_id, run_id, tenant_id, seq, type, payload, at)
                    VALUES
                        (:event_id, :run_id, :tenant_id, :seq, 'cancel_requested',
                         CAST(:payload AS jsonb), clock_timestamp())
                    """
                ),
                {
                    "event_id": event_id,
                    "run_id": run_id,
                    "tenant_id": current.tenant_id,
                    "seq": seq,
                    "payload": '{"kind":"cancel_requested"}',
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO outbox (id, event_id, dispatch_status, attempts)
                    VALUES (gen_random_uuid()::text, :event_id, 'pending', 0)
                    """
                ),
                {"event_id": event_id},
            )
    finally:
        engine.dispose()
    return "cancel_requested"


def confirm_cancel(
    database_url: str,
    run_id: str,
    worker_id: str,
    epoch: int,
    *,
    effects_known: bool,
) -> str:
    """Finish a cancel. Unknown in-flight effects become recovery_required."""
    status = "cancelled" if effects_known else "recovery_required"
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :status,
                        revision = revision + 1
                    WHERE id = :run_id
                      AND lease_owner = :worker
                      AND lease_epoch = :epoch
                      AND status = 'cancel_requested'
                      AND lease_until >= clock_timestamp()
                    RETURNING id
                    """
                ),
                {
                    "status": status,
                    "run_id": run_id,
                    "worker": worker_id,
                    "epoch": epoch,
                },
            ).first()
            if row is not None:
                return status
            current = conn.execute(
                text("SELECT status FROM runs WHERE id = :id"),
                {"id": run_id},
            ).scalar()
    finally:
        engine.dispose()
    if current in {"cancelled", "recovery_required"}:
        return str(current)
    raise LeaseRejected(run_id)


def attempt_tool(journal, attempt_id: str, tool: str, args: dict, execute):
    """Reserve the existing tool journal. A network failure leaves the write pending."""
    binding = journal.binding(attempt_id)
    call = binding.next_call(tool, args)
    reservation = journal.reserve(attempt_id, call)
    if reservation.action != "execute":
        return {
            "executed": False,
            "action": reservation.action,
            "run_status": "recovery_required",
        }
    try:
        result = execute()
    except OSError:
        return {"executed": True, "action": "uncertain", "run_status": "recovery_required"}
    journal.complete(attempt_id, call, result)
    return {"executed": True, "action": "execute", "run_status": "running", "result": result}
