"""Resume a shell write without repeating an unknown side effect.

The shell runs only through ToolOrchestrator, and only when this worker still
holds the lease, the checkpointer is open, and the journal says execute.
A pending entry means the ACK was lost.
"""

from __future__ import annotations

import asyncio
import uuid
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


def _lease_session(
    database_url: str,
    *,
    tenant_id: str,
    run_id: str,
    worker_id: str,
    epoch: int,
) -> str | None:
    """Return session_id when this worker's epoch still owns an unexpired lease."""
    engine = _engine(database_url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT session_id
                    FROM runs
                    WHERE id = :run_id
                      AND tenant_id = :tenant_id
                      AND lease_owner = :worker
                      AND lease_epoch = :epoch
                      AND status IN ('leased', 'running', 'cancel_requested')
                      AND lease_until >= clock_timestamp()
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "worker": worker_id,
                    "epoch": epoch,
                },
            ).first()
    except Exception:
        return None
    finally:
        engine.dispose()
    if row is None:
        return None
    return str(row[0])


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
                      AND status IN ('leased', 'running', 'cancel_requested')
                      AND lease_until >= clock_timestamp()
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
                existing = conn.execute(
                    text(
                        """
                        SELECT target_id
                        FROM runs
                        WHERE id = :run_id
                          AND tenant_id = :tenant_id
                          AND lease_owner = :worker
                          AND lease_epoch = :epoch
                          AND status = 'recovery_required'
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "worker": worker_id,
                        "epoch": epoch,
                    },
                ).first()
                if existing is None:
                    return False
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


async def _execute_through_orchestrator(
    *,
    journal: Any,
    attempt_id: str,
    call_id: str,
    checkpoint_id: str,
    command: str,
    workdir: str,
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
                    "permission_mode": "full_auto",
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
    session_id = _lease_session(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        worker_id=worker_id,
        epoch=epoch,
    )
    if session_id is None:
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
        return {
            "executed": False,
            "acked": False,
            "journal_state": "unknown",
            "run_status": "running",
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
        )
    )
    after = _journal_state(journal, attempt_id, call_id)
    acked = after == "completed"
    executed = acked or (before == "not_started" and after == "unknown" and _looks_executed(text_result))
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
    session_id = _lease_session(
        database_url,
        tenant_id=tenant_id,
        run_id=run_id,
        worker_id=worker_id,
        epoch=epoch,
    )
    if state == "unknown":
        if session_id is not None:
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
        return _rejected("unknown")
    if session_id is None:
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
        )
    )
    after = _journal_state(journal, attempt_id, call_id)
    if after == "unknown":
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
        executed = before == "not_started" and _looks_executed(text_result)
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
