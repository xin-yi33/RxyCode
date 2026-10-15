"""Claim a Run with a fenced lease. A stale epoch cannot commit a terminal status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


class LeaseRejected(Exception):
    """The worker's lease epoch is no longer the one stored in the database."""


_ACTIVE = {"pending", "leased", "running", "cancel_requested"}


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _lock(conn, run_id: str):
    return conn.execute(
        text(
            """
            SELECT status, lease_owner, lease_epoch, lease_until, tenant_id
            FROM runs
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {"id": run_id},
    ).one()


def claim(database_url: str, run_id: str, worker_id: str, *, ttl_seconds: int = 30) -> int | None:
    """Take the Run if it is free or its previous lease has expired."""
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = _lock(conn, run_id)
            now = datetime.now(timezone.utc)
            until = _aware(row.lease_until)
            held = (
                row.lease_owner is not None
                and until is not None
                and until >= now
            )
            if row.status not in _ACTIVE or held:
                return None
            status = "cancel_requested" if row.status == "cancel_requested" else "leased"
            epoch = int(row.lease_epoch) + 1
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :status,
                        lease_owner = :worker,
                        lease_epoch = :epoch,
                        lease_until = :until,
                        revision = revision + 1
                    WHERE id = :run_id
                    """
                ),
                {
                    "status": status,
                    "worker": worker_id,
                    "epoch": epoch,
                    "until": now + timedelta(seconds=ttl_seconds),
                    "run_id": run_id,
                },
            )
    finally:
        engine.dispose()
    if row.status not in _ACTIVE or held:
        return None
    return epoch


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
            row = _lock(conn, run_id)
            now = datetime.now(timezone.utc)
            until = _aware(row.lease_until)
            if (
                row.lease_owner != worker_id
                or int(row.lease_epoch) != epoch
                or row.status not in {"leased", "running", "cancel_requested"}
                or until is None
                or until < now
            ):
                raise LeaseRejected(run_id)
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET lease_until = :until,
                        revision = revision + 1
                    WHERE id = :run_id
                    """
                ),
                {"until": now + timedelta(seconds=ttl_seconds), "run_id": run_id},
            )
    finally:
        engine.dispose()
    return epoch


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
            row = _lock(conn, run_id)
            now = datetime.now(timezone.utc)
            until = _aware(row.lease_until)
            if (
                row.status not in {"leased", "running"}
                or row.lease_owner != worker_id
                or int(row.lease_epoch) != epoch
                or until is None
                or until < now
            ):
                raise LeaseRejected(run_id)
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :status,
                        revision = revision + 1
                    WHERE id = :run_id
                    """
                ),
                {"status": status, "run_id": run_id},
            )
    finally:
        engine.dispose()


def request_cancel(database_url: str, run_id: str) -> str:
    """Record cancel_requested once and notify through the outbox. Do not mark cancelled."""
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'cancel_requested',
                        revision = revision + 1
                    WHERE id = :id
                      AND status IN ('pending', 'leased', 'running')
                    RETURNING tenant_id
                    """
                ),
                {"id": run_id},
            ).first()
            if row is None:
                current = conn.execute(
                    text("SELECT status FROM runs WHERE id = :id"),
                    {"id": run_id},
                ).scalar()
                return str(current)
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
                    "tenant_id": row.tenant_id,
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
            row = _lock(conn, run_id)
            now = datetime.now(timezone.utc)
            until = _aware(row.lease_until)
            current = str(row.status)
            if current in {"cancelled", "recovery_required"}:
                return current
            if (
                current != "cancel_requested"
                or row.lease_owner != worker_id
                or int(row.lease_epoch) != epoch
                or until is None
                or until < now
            ):
                raise LeaseRejected(run_id)
            conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = :status,
                        revision = revision + 1
                    WHERE id = :run_id
                    """
                ),
                {"status": status, "run_id": run_id},
            )
    finally:
        engine.dispose()
    return status


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
