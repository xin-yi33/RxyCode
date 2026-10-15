"""Resume a shell write without repeating an unknown side effect.

The shell runs only when the journal reservation says ``execute``. A pending
entry means the ACK was lost: recovery marks the run ``recovery_required``
and does not start the command again.
"""

from __future__ import annotations

import subprocess
import uuid
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from RxyCode.RxyCode1_1_0.execution.tool_journal import (
    RemoteJournalAdapter,
    ToolJournalError,
    arguments_digest,
)


def _shell_args(command: list[str]) -> dict[str, list[str]]:
    return {"command": list(command)}


def _blocked(journal_state: str = "unknown") -> dict[str, object]:
    return {
        "executed": False,
        "journal_state": journal_state,
        "run_status": "recovery_required" if journal_state == "unknown" else "running",
    }


def _persist_unknown(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    attempt_id: str,
    command: list[str],
) -> None:
    """Record unknown on the owning run. A missing table must not unlock a retry."""
    digest = arguments_digest(_shell_args(command))
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            updated = conn.execute(
                text(
                    """
                    UPDATE runs
                    SET status = 'recovery_required',
                        revision = revision + 1
                    WHERE id = :run_id
                      AND tenant_id = :tenant_id
                      AND status IN (
                          'pending', 'leased', 'running', 'cancel_requested'
                      )
                    RETURNING target_id
                    """
                ),
                {"run_id": run_id, "tenant_id": tenant_id},
            ).first()
            if updated is None:
                existing = conn.execute(
                    text(
                        """
                        SELECT target_id, status FROM runs
                        WHERE id = :run_id AND tenant_id = :tenant_id
                        """
                    ),
                    {"run_id": run_id, "tenant_id": tenant_id},
                ).first()
                if existing is None:
                    return
                target_id = existing[0]
            else:
                target_id = updated[0]
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
        return
    finally:
        engine.dispose()


def run_shell_before_ack(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    attempt_id: str,
    command: list[str],
    journal: Any,
) -> dict[str, object]:
    """Reserve and run the shell. Returning without complete leaves the ACK lost."""
    del database_url, tenant_id, run_id
    adapter = RemoteJournalAdapter(journal)
    reservation = adapter.reserve(
        attempt_id=attempt_id,
        call_id=call_id,
        tool="shell",
        args=_shell_args(command),
    )
    if reservation.action != "execute":
        outcome = _blocked()
        outcome["acked"] = False
        return outcome
    subprocess.run(list(command), check=True, timeout=60)
    return {
        "executed": True,
        "acked": False,
        "journal_state": adapter.state(attempt_id=attempt_id, call_id=call_id),
        "run_status": "running",
    }


def recover_unknown_shell(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    call_id: str,
    attempt_id: str,
    command: list[str],
    journal: Any,
) -> dict[str, object]:
    """Reserve again. Unknown, corrupt, or refused reservations do not run the shell."""
    adapter = RemoteJournalAdapter(journal)
    try:
        reservation = adapter.reserve(
            attempt_id=attempt_id,
            call_id=call_id,
            tool="shell",
            args=_shell_args(command),
        )
    except (ToolJournalError, ValueError):
        _persist_unknown(
            database_url,
            tenant_id=tenant_id,
            run_id=run_id,
            call_id=call_id,
            attempt_id=attempt_id,
            command=command,
        )
        return _blocked("unknown")
    if reservation.action != "execute":
        state = "completed" if reservation.action == "reuse" else "unknown"
        if state == "unknown":
            _persist_unknown(
                database_url,
                tenant_id=tenant_id,
                run_id=run_id,
                call_id=call_id,
                attempt_id=attempt_id,
                command=command,
            )
        return _blocked(state)
    subprocess.run(list(command), check=True, timeout=60)
    adapter.complete(
        attempt_id=attempt_id,
        call_id=call_id,
        tool="shell",
        args=_shell_args(command),
        result="completed",
    )
    return {
        "executed": True,
        "journal_state": "completed",
        "run_status": "running",
    }
