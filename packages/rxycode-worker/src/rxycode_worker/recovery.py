"""Resume a shell write without repeating an unknown side effect.

The shell runs only through ToolOrchestrator, and only when this worker still
holds the lease, the checkpointer is open, and the journal says execute.
A pending entry means the ACK was lost.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from rxycode_worker.checkpoints import checkpointer_ready

from RxyCode.RxyCode1_1_0.execution.tool_journal import (
    RemoteJournalAdapter,
    ToolJournalError,
    arguments_digest,
    remote_checkpoint_id,
)


def _engine(database_url: str):
    url = database_url
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    return create_engine(url, poolclass=NullPool)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _lock_run(conn, run_id: str):
    return conn.execute(
        text(
            """
            SELECT session_id, status, lease_owner, lease_epoch,
                   lease_until, target_id, tenant_id
            FROM runs
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {"id": run_id},
    ).one_or_none()


def _owns(row, *, tenant_id: str, worker_id: str, epoch: int) -> bool:
    return (
        row is not None
        and str(row.tenant_id) == tenant_id
        and row.lease_owner == worker_id
        and int(row.lease_epoch) == int(epoch)
    )


def _lease_is_current(row, *, tenant_id: str, worker_id: str, epoch: int, now: datetime) -> bool:
    """True only when the lease is still live at `now`, sampled after the row lock."""
    if not _owns(row, tenant_id=tenant_id, worker_id=worker_id, epoch=epoch):
        return False
    if str(row.status) not in {"leased", "running", "cancel_requested"}:
        return False
    until = _aware(row.lease_until)
    return until is not None and until >= now


def _lease_view(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    worker_id: str,
    epoch: int,
) -> tuple[str | None, str]:
    """Return (session_id, kind). kind is live, recovering, or none.

    recovering does not grant another shell. The lease clock is read after the row lock.
    """
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = _lock_run(conn, run_id)
            now = datetime.now(timezone.utc)
            if _lease_is_current(
                row,
                tenant_id=tenant_id,
                worker_id=worker_id,
                epoch=epoch,
                now=now,
            ):
                return str(row.session_id), "live"
            if _owns(row, tenant_id=tenant_id, worker_id=worker_id, epoch=epoch) and str(
                row.status
            ) == "recovery_required":
                return str(row.session_id), "recovering"
    except Exception:
        return None, "none"
    finally:
        engine.dispose()
    return None, "none"


def _persist_unknown(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    attempt_id: str,
    command: str,
    worker_id: str,
    epoch: int,
) -> bool:
    """Mark recovery_required only for the current lease owner and epoch."""
    digest = arguments_digest({"command": command})
    engine = _engine(database_url)
    try:
        with engine.begin() as conn:
            row = _lock_run(conn, run_id)
            now = datetime.now(timezone.utc)
            if not _owns(row, tenant_id=tenant_id, worker_id=worker_id, epoch=epoch):
                return False
            if str(row.status) == "recovery_required":
                target_id = row.target_id
            elif _lease_is_current(
                row,
                tenant_id=tenant_id,
                worker_id=worker_id,
                epoch=epoch,
                now=now,
            ):
                updated = conn.execute(
                    text(
                        """
                        UPDATE runs
                        SET status = 'recovery_required',
                            revision = revision + 1
                        WHERE id = :run_id
                          AND tenant_id = :tenant_id
                          AND lease_owner = :worker
                          AND lease_epoch = :epoch
                        RETURNING target_id
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "worker": worker_id,
                        "epoch": epoch,
                    },
                ).first()
                if updated is None:
                    return False
                target_id = updated[0]
                from rxycode_worker.supervisor import _emit_run_status

                _emit_run_status(
                    conn, run_id, tenant_id, "recovery_required", epoch
                )
            else:
                return False
            conn.execute(
                text(
                    """
                    INSERT INTO tool_invocations (
                        id, run_id, call_id, target_id, attempt_id,
                        journal_state, digest
                    )
                    VALUES (
                        :id, :run_id, :call_id, :target_id, :attempt_id,
                        'unknown', :digest
                    )
                    ON CONFLICT (run_id, call_id)
                    DO UPDATE SET
                        journal_state = 'unknown',
                        attempt_id = EXCLUDED.attempt_id,
                        digest = EXCLUDED.digest,
                        target_id = EXCLUDED.target_id
                    """
                ),
                {
                    "id": uuid.uuid4().hex,
                    "run_id": run_id,
                    "call_id": call_id,
                    "target_id": target_id or "",
                    "attempt_id": attempt_id,
                    "digest": digest,
                },
            )
    except SQLAlchemyError:
        return False
    finally:
        engine.dispose()
    return True


def _looks_executed(text: str) -> bool:
    if "side-effect completed" in text:
        return True
    lowered = text.lower()
    if text.startswith(("[error", "[blocked", "[dry-run")):
        return False
    if "rejected" in lowered or "not executed" in lowered:
        return False
    if "journal unavailable" in lowered or "sandbox_error" in lowered:
        return False
    return True


def _permission_mode(database_url: str, tenant_id: str, run_id: str) -> str:
    """Use the profile stored when the run was accepted. Never upgrade it."""
    engine = _engine(database_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT payload->>'permission_profile'
                    FROM run_events
                    WHERE run_id = :run_id
                      AND tenant_id = :tenant_id
                      AND type = 'run.created'
                    ORDER BY seq
                    LIMIT 1
                    """
                ),
                {"run_id": run_id, "tenant_id": tenant_id},
            ).first()
    except Exception:
        return "confirm_all"
    finally:
        engine.dispose()
    if row is None or not row[0]:
        return "confirm_all"
    return str(row[0])


def _scope_blocked(text: str) -> bool:
    """A guard refused the call. A lost ACK says the side effect already completed."""
    if "side-effect completed" in text:
        return False
    lowered = text.lower()
    return "journal unavailable" in lowered or "outcome unknown" in lowered


async def _execute_through_orchestrator(
    *,
    journal: Any,
    attempt_id: str,
    call_id: str,
    checkpoint_id: str,
    command: str,
    workdir: str,
    permission_mode: str,
) -> str:
    from RxyCode.RxyCode1_1_0.execution.tool_orchestrator import ToolOrchestrator
    from RxyCode.RxyCode1_1_0.tools.bash import bash_tool

    orchestrator = ToolOrchestrator()
    orchestrator.register("bash", bash_tool)
    token = orchestrator.bind_tool_journal(
        journal,
        attempt_id,
        checkpoint_id,
        call_id,
    )
    try:
        return await orchestrator.execute_tool(
            "bash",
            {
                "command": command,
                "description": "journaled shell write",
                "workdir": workdir,
            },
            {
                "safety": {
                    "enabled": True,
                    "permission_mode": permission_mode,
                    "allowed_write_paths": [workdir] if workdir else [],
                },
                "execution": {
                    "workspace_root": workdir,
                    "tool_retry_attempts": 1,
                },
            },
            call_id=call_id,
        )
    finally:
        orchestrator.reset_tool_journal(token)


def _journal_state(journal: Any, attempt_id: str, call_id: str) -> str:
    try:
        return RemoteJournalAdapter(journal).state(
            attempt_id=attempt_id,
            call_id=call_id,
        )
    except (ToolJournalError, ValueError):
        return "unknown"


def _rejected(journal_state: str = "unknown") -> dict[str, object]:
    return {
        "executed": False,
        "acked": False,
        "journal_state": journal_state,
        "run_status": "lease_rejected",
    }


def run_shell_before_ack(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    attempt_id: str,
    command: str,
    workdir: str,
    journal: Any,
    worker_id: str,
    epoch: int,
) -> dict[str, object]:
    """Reserve through ToolOrchestrator and run bash. A lost ACK stays pending."""
    session_id, lease_kind = _lease_view(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        worker_id=worker_id,
        epoch=epoch,
    )
    if lease_kind != "live":
        if lease_kind == "recovering":
            return {
                "executed": False,
                "acked": False,
                "journal_state": "unknown",
                "run_status": "recovery_required",
            }
        return _rejected(_journal_state(journal, attempt_id, call_id))
    if not asyncio.run(
        checkpointer_ready(
            database_url,
            session_id=session_id,
            run_id=run_id,
        )
    ):
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
            worker_id=worker_id,
            epoch=epoch,
        )
        return {
            "executed": False,
            "acked": False,
            "journal_state": "unknown",
            "run_status": "recovery_required",
        }
    before = _journal_state(journal, attempt_id, call_id)
    if before == "unknown":
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
            worker_id=worker_id,
            epoch=epoch,
        )
        return {
            "executed": False,
            "acked": False,
            "journal_state": "unknown",
            "run_status": "recovery_required",
        }
    checkpoint_id = remote_checkpoint_id(run_id)
    text_result = asyncio.run(
        _execute_through_orchestrator(
            journal=journal,
            attempt_id=attempt_id,
            call_id=call_id,
            checkpoint_id=checkpoint_id,
            command=command,
            workdir=workdir,
            permission_mode=_permission_mode(database_url, tenant_id, run_id),
        )
    )
    if _scope_blocked(text_result):
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
            worker_id=worker_id,
            epoch=epoch,
        )
        return {
            "executed": False,
            "acked": False,
            "journal_state": "unknown",
            "run_status": "recovery_required",
            "output": text_result,
        }
    after = _journal_state(journal, attempt_id, call_id)
    acked = after == "completed"
    executed = acked or (
        before == "not_started" and after == "unknown" and _looks_executed(text_result)
    )
    if executed and not acked:
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
            worker_id=worker_id,
            epoch=epoch,
        )
        return {
            "executed": True,
            "acked": False,
            "journal_state": "unknown",
            "run_status": "recovery_required",
            "output": text_result,
        }
    return {
        "executed": executed,
        "acked": acked,
        "journal_state": after,
        "run_status": "running",
        "output": text_result,
    }


def recover_unknown_shell(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    attempt_id: str,
    command: str,
    workdir: str,
    journal: Any,
    worker_id: str,
    epoch: int,
) -> dict[str, object]:
    """Do not run the shell again when the previous ACK is missing."""
    state = _journal_state(journal, attempt_id, call_id)
    session_id, lease_kind = _lease_view(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        worker_id=worker_id,
        epoch=epoch,
    )
    if state == "unknown":
        if lease_kind == "live":
            _persist_unknown(
                database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                call_id=call_id,
                attempt_id=attempt_id,
                command=command,
                worker_id=worker_id,
                epoch=epoch,
            )
            return {
                "executed": False,
                "journal_state": "unknown",
                "run_status": "recovery_required",
            }
        if lease_kind == "recovering":
            return {
                "executed": False,
                "journal_state": "unknown",
                "run_status": "recovery_required",
            }
        return _rejected("unknown")
    if lease_kind != "live":
        return _rejected(state)
    if not asyncio.run(
        checkpointer_ready(
            database_url,
            session_id=session_id,
            run_id=run_id,
        )
    ):
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
            worker_id=worker_id,
            epoch=epoch,
        )
        return {
            "executed": False,
            "journal_state": "unknown",
            "run_status": "recovery_required",
        }
    before = state
    text_result = asyncio.run(
        _execute_through_orchestrator(
            journal=journal,
            attempt_id=attempt_id,
            call_id=call_id,
            checkpoint_id=remote_checkpoint_id(run_id),
            command=command,
            workdir=workdir,
            permission_mode=_permission_mode(database_url, tenant_id, run_id),
        )
    )
    after = _journal_state(journal, attempt_id, call_id)
    if _scope_blocked(text_result) or after == "unknown":
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
            worker_id=worker_id,
            epoch=epoch,
        )
        executed = (
            before == "not_started"
            and after == "unknown"
            and _looks_executed(text_result)
            and not _scope_blocked(text_result)
        )
        return {
            "executed": executed,
            "journal_state": "unknown",
            "run_status": "recovery_required",
        }
    return {
        "executed": after == "completed" and before == "not_started",
        "journal_state": after,
        "run_status": "running",
    }
