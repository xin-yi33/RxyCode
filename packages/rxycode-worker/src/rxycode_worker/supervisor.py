"""Claim a Run with a fenced lease. A stale epoch cannot commit a terminal status."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


_LOG = logging.getLogger(__name__)

#: In-flight leased-run spans, run_id -> (tracer, span). Opened at claim,
#: closed by the terminal commit/cancel path. Telemetry is best-effort: a
#: run abandoned before its terminal write simply never exports the span.
_OPEN_RUN_SPANS: dict[str, tuple[Any, Any]] = {}


def _open_run_span(
    database_url: str, run_id: str, tenant_id: str, worker_id: str, epoch: int
) -> None:
    """Best-effort worker/run span wrapping the leased execution — opened
    at claim, closed by commit_terminal/confirm_cancel. The remote parent
    is read RUN-SCOPED: the ``traceparent`` persisted inside this run's
    ``run.created`` event (``telemetry.parent_for_run``). The
    process-global ``RXYCODE_TRACEPARENT`` env is deliberately NOT read —
    it could hold another run's context (create A, create B, claim A) or
    be missing entirely in a worker started before it was set. The span's
    own context is still re-published to env so subprocesses and legacy
    readers inherit a sane parent. Never breaks the lease flow."""
    try:
        from rxycode_worker import telemetry

        tracer = telemetry.Tracer(
            telemetry.RunEventsSpanExporter(database_url, tenant_id),
            service="rxycode-worker",
        )
        lookup = telemetry.parent_for_run(database_url, run_id)
        # ``lookup.context`` is None when the run predates persisted
        # traceparents (``run_event_found`` True) AND when the lookup
        # failed / the run.created row is absent (False). Either way this
        # span starts an honest new trace — the process-global env is
        # never read on the claim path, so a stale foreign context can
        # never cross-parent this run's worker span.
        span = tracer.start_span(
            "worker.run",
            kind="worker",
            parent=lookup.context,
            run_id=run_id,
            attrs={"worker.id": worker_id, "worker.epoch": epoch},
        )
        _OPEN_RUN_SPANS[run_id] = (tracer, span)
        telemetry.inject_env(span.context)
    except Exception:
        _LOG.warning("worker.run span open failed", exc_info=True)


def _close_run_span(
    run_id: str, status: str, *, conn=None, run_status: str = ""
) -> None:
    """End the leased run's span. ``conn`` is the caller's OPEN terminal
    transaction: the span event must land atomically with the status write
    — an event appended after the commit would sit post-terminal, which the
    follow-SSE endpoint can never deliver (it stops on terminal status).
    Without a conn the span closes through the normal exporter path.

    Still-open agent/tool spans for this run are swept FIRST: an agent
    that reached FAILED (or was cancelled) without a closing journal event
    leaves its ``graph.agent.*`` / ``tool.*`` span registered forever —
    never exported, parent chain dangling.  Sweeping them here, inside the
    same terminal transaction when ``conn`` is given and BEFORE worker.run
    ends, exports each one with the terminal status (flagged ``unclosed``)
    while keeping the recorded parent chain intact."""
    try:
        from rxycode_worker import agent_events

        agent_events.sweep_open_spans(
            run_id, status, conn=conn, run_status=run_status
        )
    except Exception:
        _LOG.warning("unclosed span sweep failed", exc_info=True)
    pair = _OPEN_RUN_SPANS.pop(run_id, None)
    if pair is None:
        return
    tracer, span = pair
    try:
        from rxycode_worker import telemetry

        payload = tracer.finalize_span(
            span,
            status=status,
            attrs={"run.terminal_status": status},
        )
        # SAVEPOINT isolation lives in export_span_payload: a failed
        # statement propagates out of begin_nested(), the rollback covers
        # the telemetry write alone and the terminal UPDATE survives.
        telemetry.export_span_payload(
            getattr(tracer, "exporter", None), payload, conn=conn
        )
    except Exception:
        _LOG.warning("worker.run span close failed", exc_info=True)


_TERMINAL_SPAN_STATUS = {
    "succeeded": "ok",
    "failed": "error",
    "cancelled": "cancelled",
    "recovery_required": "error",
}


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
    _open_run_span(database_url, run_id, str(row.tenant_id), worker_id, epoch)
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
            # The span event lands in THIS tx — atomically before the
            # terminal status becomes visible — so the follow-SSE stream
            # always delivers it (it stops polling once status is terminal).
            _close_run_span(
                run_id,
                _TERMINAL_SPAN_STATUS.get(status, "ok"),
                conn=conn,
                run_status=status,
            )
        _release_quota(database_url, run_id)
        from rxycode_server.notifications.service import notify_run_terminal

        notify_run_terminal(database_url, run_id, status)
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
                        revision = revision + 1,
                        event_seq = GREATEST(
                            event_seq,
                            COALESCE((SELECT MAX(seq) FROM run_events WHERE run_id = runs.id), 0)
                        ) + 1
                    WHERE id = :id
                      AND status IN ('pending', 'leased', 'running')
                    RETURNING tenant_id, event_seq
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
            seq = int(row.event_seq)
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
            # Atomic with the terminal write — see commit_terminal.
            _close_run_span(
                run_id,
                _TERMINAL_SPAN_STATUS.get(status, "ok"),
                conn=conn,
                run_status=status,
            )
        _release_quota(database_url, run_id)
    finally:
        engine.dispose()
    return status


def _release_quota(database_url: str, run_id: str) -> None:
    """A terminal Run no longer holds its concurrency slot."""
    from rxycode_server.runs.service import release_worker_for_run

    release_worker_for_run(database_url, run_id)


def attempt_tool(
    journal,
    attempt_id: str,
    tool: str,
    args: dict,
    execute,
    *,
    gateway: object | None = None,
    device_id: str = "",
    call_id: str = "",
    ack: bool = True,
    stop_after_chunks: int | None = None,
):
    """Reserve the existing tool journal. A device target goes out on its socket."""
    if gateway is not None and device_id and call_id:
        from rxycode_worker.runner_client import dispatch_device_call

        outcome = dispatch_device_call(
            gateway=gateway,
            device_id=device_id,
            call_id=call_id,
            attempt_id=attempt_id,
            tool=tool,
            args=args,
            ack=ack,
            stop_after_chunks=stop_after_chunks,
        )
        return {
            "executed": outcome.state == "completed",
            "action": outcome.state,
            "run_status": "running" if outcome.state == "completed" else "recovery_required",
            "result": outcome.result,
            "state": outcome.state,
            "chunks": outcome.chunks,
            "truncated": outcome.truncated,
        }
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


def resume_device_tool(gateway, device_id: str, call_id: str, attempt_id: str, resume_from: int):
    """Ask the paired device for chunks after the socket returns."""
    from rxycode_worker.runner_client import dispatch_device_resume

    return dispatch_device_resume(
        gateway=gateway,
        device_id=device_id,
        call_id=call_id,
        attempt_id=attempt_id,
        resume_from=resume_from,
    )


def cancel_device_tool(gateway, device_id: str, call_id: str, attempt_id: str, tool: str, args: dict, started):
    """Tell the paired device to stop the in-flight tool."""
    from rxycode_worker.runner_client import dispatch_device_cancel

    return dispatch_device_cancel(
        gateway=gateway,
        device_id=device_id,
        call_id=call_id,
        attempt_id=attempt_id,
        tool=tool,
        args=args,
        started=started,
    )
