"""Run approval routes. The tenant comes from the session, not the body."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from rxycode_server.api.auth import current_record, require_write
from rxycode_server.persistence.models import Outbox, RunEvent
from rxycode_server.approvals.service import (
    ApprovalStale,
    answer_question,
    decide_approval,
    get_approval,
    list_pending,
    list_pending_questions_durable,
    pending_question,
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


def _owned_run(database_url: str, tenant_id: str, run_id: str) -> str:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != tenant_id:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            return str(row.session_id)
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


def _question_flags(
    database_url: str,
    tenant_id: str,
    run_id: str,
    question_id: str,
) -> tuple[bool, bool]:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            rows = db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.tenant_id == tenant_id,
                    RunEvent.type.in_(("question.requested", "question.resolved")),
                )
            ).all()
            requested = False
            resolved = False
            for row in rows:
                body = row.payload or {}
                if str(body.get("question_id") or "") != question_id:
                    continue
                if row.type == "question.requested":
                    requested = True
                if row.type == "question.resolved":
                    resolved = True
            return requested, resolved
    finally:
        engine.dispose()


def _resume_question(database_url: str, tenant_id: str, run_id: str) -> None:
    from rxycode_server.events.store import append_run_status

    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != tenant_id:
                return
            if row.status in {"leased", "running"}:
                row.status = "pending"
                append_run_status(db, row, "pending")
                row.lease_owner = None
                row.lease_until = None
                row.revision = int(row.revision or 0) + 1
                db.commit()
    finally:
        engine.dispose()


def _resolve_broker(question_id: str, answer: str) -> None:
    try:
        from core.question import get_question_broker
    except ModuleNotFoundError:
        from RxyCode.RxyCode1_1_0.core.question import get_question_broker
    broker = get_question_broker()
    if broker is not None:
        broker.resolve(question_id, answer)


@router.get("/api/v1/runs/{run_id}/questions")
def get_questions(run_id: str, request: Request) -> dict[str, list[dict]]:
    record = current_record(request)
    database_url = request.app.state.database_url
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            row = db.get(Run, run_id)
            if row is None or row.tenant_id != record.tenant_id:
                raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
            session_id = row.session_id
    finally:
        engine.dispose()
    try:
        from core.question import list_pending_questions
    except ModuleNotFoundError:
        from RxyCode.RxyCode1_1_0.core.question import list_pending_questions
    durable = list_pending_questions_durable(
        database_url, tenant_id=record.tenant_id, run_id=run_id
    )
    seen = {item["question_id"] for item in durable}
    in_process = [
        item for item in list_pending_questions(session_id) if item["question_id"] not in seen
    ]
    return {"questions": durable + in_process}


def _append_resolution_once(
    database_url: str,
    tenant_id: str,
    run_id: str,
    question_id: str,
    answer: str,
) -> bool:
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with Session(engine) as db:
            run = db.execute(
                select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
            ).scalar_one_or_none()
            if run is None:
                return False
            rows = db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.tenant_id == tenant_id,
                    RunEvent.type == "question.resolved",
                )
            ).all()
            for row in rows:
                if str((row.payload or {}).get("question_id") or "") == question_id:
                    return False
            retained = db.scalar(select(func.max(RunEvent.seq)).where(RunEvent.run_id == run.id))
            seq = max(int(run.event_seq or 0), int(retained or 0)) + 1
            run.event_seq = seq
            event_id = uuid.uuid4().hex
            db.add(
                RunEvent(
                    event_id=event_id,
                    run_id=run.id,
                    tenant_id=tenant_id,
                    seq=seq,
                    type="question.resolved",
                    payload={"question_id": question_id, "answer": answer},
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
            return True
    finally:
        engine.dispose()


@router.post("/api/v1/runs/{run_id}/questions")
def post_question(run_id: str, payload: AnswerIn, request: Request) -> dict[str, str]:
    require_write(request)
    record = current_record(request)
    database_url = request.app.state.database_url
    session_id = _owned_run(database_url, record.tenant_id, run_id)
    if not payload.question_id.strip():
        raise HTTPException(status_code=400, detail="INVALID_INPUT")
    if pending_question(
        database_url,
        tenant_id=record.tenant_id,
        run_id=run_id,
        question_id=payload.question_id,
    ) is not None:
        # A parked turn's question: the durable answer is the resume. Only
        # this run's own pending row can match, so a stale or foreign id
        # falls through to the in-process channel and is refused there.
        try:
            answer_question(
                database_url,
                tenant_id=record.tenant_id,
                run_id=run_id,
                question_id=payload.question_id,
                answer=payload.answer,
            )
        except ApprovalStale as exc:
            raise HTTPException(status_code=409, detail="QUESTION_STALE") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="INVALID_INPUT") from exc
        return {"status": "accepted"}
    requested, resolved = _question_flags(
        database_url,
        record.tenant_id,
        run_id,
        payload.question_id,
    )
    if resolved:
        raise HTTPException(status_code=409, detail="QUESTION_STALE")
    pending_event = requested and not resolved
    try:
        from core.question import publish_question_answer, question_pending_for_session
    except ModuleNotFoundError:
        from RxyCode.RxyCode1_1_0.core.question import (
            publish_question_answer,
            question_pending_for_session,
        )
    try:
        pending_before = question_pending_for_session(payload.question_id, session_id)
        mailed = publish_question_answer(
            payload.question_id,
            payload.answer,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="INVALID_INPUT") from exc
    if not mailed and (pending_before or not pending_event):
        raise HTTPException(status_code=409, detail="QUESTION_STALE")
    if not _append_resolution_once(
        database_url,
        record.tenant_id,
        run_id,
        payload.question_id,
        payload.answer,
    ):
        raise HTTPException(status_code=409, detail="QUESTION_STALE")
    _resolve_broker(payload.question_id, payload.answer)
    if not mailed:
        _resume_question(database_url, record.tenant_id, run_id)
    return {"status": "accepted"}
