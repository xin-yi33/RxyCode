"""Claim a Run with a fenced lease. A stale epoch cannot commit a terminal status."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


class LeaseRejected(Exception):
    """The worker's lease epoch is no longer the one stored in the database."""


def _engine(database_url: str):
    return create_engine(database_url, poolclass=NullPool)


def claim(database_url: str, run_id: str, worker_id: str, *, ttl_seconds: int = 30) -> int | None:
    """Take the Run if it is free or its previous lease has expired."""
    now = datetime.now(timezone.utc)
    until = now + timedelta(seconds=ttl_seconds)
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
                        lease_until = :until,
                        revision = revision + 1
                    WHERE id = :run_id
                      AND status IN ('pending', 'leased', 'running')
                      AND (lease_owner IS NULL OR lease_until < :now)
                    RETURNING lease_epoch
                    """
                ),
                {"worker": worker_id, "until": until, "now": now, "run_id": run_id},
            ).first()
    finally:
        engine.dispose()
    if row is None:
        return None
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
    now = datetime.now(timezone.utc)
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
                      AND lease_until >= :now
                    RETURNING id
                    """
                ),
                {
                    "status": status,
                    "run_id": run_id,
                    "worker": worker_id,
                    "epoch": epoch,
                    "now": now,
                },
            ).first()
    finally:
        engine.dispose()
    if row is None:
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
