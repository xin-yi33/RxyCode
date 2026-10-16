"""Read a run's durable status. The tenant comes from the session."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record
from rxycode_server.persistence.models import Run

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
