"""Read a run's durable status. The tenant comes from the session."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.persistence.models import Outbox, Run, RunEvent

_DONE = {"succeeded", "failed", "cancelled", "recovery_required"}

router = APIRouter()


@router.get("/api/v1/runs/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, object]:
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != record.tenant_id:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            return {
                "run_id": row.id,
                "status": row.status,
                "session_id": row.session_id,
                "event_seq": int(row.event_seq or 0),
            }
    finally:
        engine.dispose()


@router.post("/api/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str, request: Request) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    database_url = request.app.state.database_url
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == record.tenant_id).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            if row.status in _DONE:
                raise HTTPException(status_code=409, detail="RUN_TERMINAL")
            if row.status != "cancel_requested":
                row.status = "cancel_requested"
                row.revision = int(row.revision or 0) + 1
                retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == row.id))
                seq = max(int(row.event_seq or 0), int(retained or 0)) + 1
                row.event_seq = seq
                event_id = uuid.uuid4().hex
                db.add(
                    RunEvent(
                        event_id=event_id,
                        run_id=row.id,
                        tenant_id=record.tenant_id,
                        seq=seq,
                        type="run.status",
                        payload={"status": "cancel_requested"},
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
    finally:
        engine.dispose()
    return {"status": "cancel_requested"}


@router.post("/api/v1/runs/{run_id}/steer")
async def steer_run(run_id: str, request: Request) -> dict[str, object]:
    """Queue a steer on this run. The event log is the command, not EventStore."""
    require_write(request)
    body = await request.json()
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    record = current_record(request)
    database_url = request.app.state.database_url
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == record.tenant_id).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            if row.status in _DONE:
                raise HTTPException(status_code=409, detail="RUN_TERMINAL")
            retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == row.id))
            seq = max(int(row.event_seq or 0), int(retained or 0)) + 1
            row.event_seq = seq
            row.revision = int(row.revision or 0) + 1
            event_id = uuid.uuid4().hex
            db.add(
                RunEvent(
                    event_id=event_id,
                    run_id=row.id,
                    tenant_id=record.tenant_id,
                    seq=seq,
                    type="steer.accepted",
                    payload={"text": text, "seq": seq},
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
    finally:
        engine.dispose()
    return {"run_id": run_id, "status": "accepted", "text": text}


@router.post("/api/v1/runs/{run_id}/children/{session_id}/cancel")
def cancel_child_run(run_id: str, session_id: str, request: Request) -> dict[str, str]:
    """Record a child cancel. The parent run status stays unchanged."""
    require_write(request)
    record = current_record(request)
    engine = create_engine(request.app.state.database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == record.tenant_id).with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            if row.status in _DONE:
                raise HTTPException(status_code=409, detail="RUN_TERMINAL")
            retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == row.id))
            seq = max(int(row.event_seq or 0), int(retained or 0)) + 1
            row.event_seq = seq
            row.revision = int(row.revision or 0) + 1
            event_id = uuid.uuid4().hex
            db.add(
                RunEvent(
                    event_id=event_id,
                    run_id=row.id,
                    tenant_id=record.tenant_id,
                    seq=seq,
                    type="child.cancel",
                    payload={"session_id": session_id},
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
    finally:
        engine.dispose()
    return {"run_id": run_id, "session_id": session_id, "status": "cancel_requested"}
