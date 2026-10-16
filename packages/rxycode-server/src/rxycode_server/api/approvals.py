"""Run approval routes. The tenant comes from the session, not the body."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.events.store import append_event
from rxycode_server.approvals.service import (
    ApprovalStale,
    decide_approval,
    get_approval,
    list_pending,
)
from rxycode_server.persistence.models import Run

router = APIRouter()


class DecisionIn(BaseModel):
    approval_id: str
    decision: str
    revision: int


class AnswerIn(BaseModel):
    question_id: str
    answer: str


def _owned_run(database_url: str, tenant_id: str, run_id: str) -> None:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    finally:
        engine.dispose()


@router.get("/api/v1/runs/{run_id}/approvals")
def get_approvals(run_id: str, request: Request) -> dict:
    record = current_record(request)
    database_url = request.app.state.database_url
    _owned_run(database_url, record.tenant_id, run_id)
    return {
        "approvals": list_pending(
            database_url,
            tenant_id=record.tenant_id,
            run_id=run_id,
            now=datetime.now(timezone.utc),
        )
    }


@router.post("/api/v1/runs/{run_id}/approvals")
def post_approval(run_id: str, payload: DecisionIn, request: Request) -> dict:
    require_write(request)
    record = current_record(request)
    database_url = request.app.state.database_url
    _owned_run(database_url, record.tenant_id, run_id)
    existing = get_approval(
        database_url,
        tenant_id=record.tenant_id,
        approval_id=payload.approval_id,
    )
    if existing is None or existing["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    try:
        return decide_approval(
            database_url,
            tenant_id=record.tenant_id,
            approval_id=payload.approval_id,
            decision=payload.decision,
            expected_revision=payload.revision,
            now=datetime.now(timezone.utc),
        )
    except ApprovalStale as exc:
        raise HTTPException(status_code=409, detail="APPROVAL_STALE") from exc


@router.post("/api/v1/runs/{run_id}/questions")
def post_question(run_id: str, payload: AnswerIn, request: Request) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    database_url = request.app.state.database_url
    _owned_run(database_url, record.tenant_id, run_id)
    if not payload.question_id.strip():
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    append_event(
        database_url,
        tenant_id=record.tenant_id,
        run_id=run_id,
        event_type="question.resolved",
        payload={"question_id": payload.question_id, "answer": payload.answer},
    )
    return {"status": "accepted"}
