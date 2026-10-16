"""Read a run's durable status. The tenant comes from the session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.events.store import append_event
from rxycode_server.persistence.models import Run

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
                db.commit()
                changed = True
            else:
                changed = False
    finally:
        engine.dispose()
    if changed:
        append_event(
            database_url,
            tenant_id=record.tenant_id,
            run_id=run_id,
            event_type="run.status",
            payload={"status": "cancel_requested"},
        )
    return {"status": "cancel_requested"}
